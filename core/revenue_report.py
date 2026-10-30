"""Revenue insights behind /revenue-report-exclusive/ (superusers only).

The money view of the business. /manage/payment-tracking/ asks how people get through
checkout; this page answers the questions an owner decides on, in this order:

1. How much came in, and is it growing?         - revenue, pace against the previous period.
2. How much of it repeats?                      - MRR, paying customers, what moved MRR.
3. Will it last?                                - renewal rate, churn, renewals due soon.
4. Where does it come from, and what does it cost? - plan and method mix, discounts, customers.

Definitions (the page prints them too):

* Revenue is confirmed payments (status 'paid') above zero. Free activations (100% coupons,
  school codes, admin grants) are "free passes": counted, never added to revenue.
* MRR (monthly recurring revenue) at a moment: for each customer with a paid plan running,
  what they paid for it spread per 30 days (449 EGP for 365 days -> 36.90 EGP a month).
  When an early renewal overlaps the old plan, only the newest paid plan counts.
* A plan renewed when the same customer paid again before it ended or within RENEWAL_GRACE
  after. Plans still inside that window are undecided and left out of the rate.
* List prices are today's PLAN_CATALOGUE prices. Discount = list price minus what was paid.

Like the other manage reports nothing before REPORT_START_DATE counts, and staff/superuser
accounts are left out unless the team toggle is on. Shared helpers come from payment_report
so the two reports always agree on plans, methods and money formatting.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Q
from django.utils import timezone

from core.models import CustomUser, ManualPayment, Profile, UserPayment
from core.payment_report import (
    METHOD_LABELS, PLAN_LABELS, REPORT_START_DATE, _bucket_index, _buckets, _delta, _money, _rate,
    payment_method, payment_plan, report_start, team_user_ids,
)

PERIODS = {'30': 30, '90': 90, '365': 365, 'all': None}
PERIOD_LABELS = {'30': '30 days', '90': '90 days', '365': '12 months', 'all': 'All time'}
DEFAULT_PERIOD = '90'

RENEWAL_GRACE = timedelta(days=14)   # paying again this soon after a plan ends still counts as renewing
QUIET_DAYS = 14                      # a customer due to renew and unseen this long needs a nudge
FORECAST_WEEKS = 12
MOVEMENT_STEP = timedelta(days=7)    # MRR movement is measured week by week through the period
MIN_RATE_SAMPLE = 5                  # fewer decided plans than this and a rate is an anecdote
SMALL_SAMPLE = 5                     # fewer paid orders than this and every % swings wildly
LEDGER_LIMIT = 100
TOP_CUSTOMERS = 8
ZERO = Decimal('0')

KIND_LABELS = {'new': 'New customer', 'repeat': 'Renewal', 'free': 'Free pass'}
NON_EDITOR_TYPES = ('client', 'school_admin')
MOCK_USERNAMES = ('alex_mercer',)


# ── Period ──────────────────────────────────────────────────────────────────

@dataclass
class Period:
    key: str
    days: int | None
    start: datetime
    end: datetime
    label: str

    @property
    def previous(self):
        """The same-length window just before this one. None when it would reach back before
        the report start: a window cut short there would make every comparison look like growth."""
        if not self.days:
            return None
        start = self.start - timedelta(days=self.days)
        if start < report_start():
            return None
        return Period('previous', self.days, start, self.start, f'previous {self.days} days')


def _day_label(d):
    return f'{d.day} {d:%b %Y}'


def _parse_day(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def resolve_period(param=DEFAULT_PERIOD, start=None, end=None, now=None):
    """A preset (30 / 90 / 365 days / all) or, when start or end is given, a custom date range."""
    now = now or timezone.now()
    floor = report_start()
    first, last = _parse_day(start), _parse_day(end)
    if first or last:
        today = timezone.localdate(now)
        first = max(first or REPORT_START_DATE, REPORT_START_DATE)
        last = min(last or today, today)
        if first <= last:
            begin = timezone.make_aware(datetime.combine(first, time.min))
            stop = min(timezone.make_aware(datetime.combine(last + timedelta(days=1), time.min)), now)
            return Period('custom', (last - first).days + 1, begin, stop,
                          f'{_day_label(first)} – {_day_label(last)}')

    key = param if param in PERIODS else DEFAULT_PERIOD
    days = PERIODS[key]
    since = _day_label(REPORT_START_DATE)
    if days is None:
        return Period(key, None, floor, now, f'All time (since {since})')
    name = 'Last 12 months' if key == '365' else f'Last {days} days'
    begin = now - timedelta(days=days)
    if begin < floor:
        return Period(key, days, floor, now, f'{name} (from {since})')
    return Period(key, days, begin, now, name)


def _in(at, start, end):
    return start <= at < end


# ── Loading: one record per paid payment ────────────────────────────────────

def plan_prices():
    from payments.views import PLAN_CATALOGUE  # lazy: payments.views imports core.views
    return {'monthly': Decimal(PLAN_CATALOGUE['monthly'][0]),
            'annual': Decimal(PLAN_CATALOGUE['pro_annual'][0])}


def _list_price(days, prices):
    if not days:
        return None
    if days >= 300:
        return prices['annual']
    return prices['monthly'] * max(1, round(days / 30))


def _name(user):
    if not user:
        return 'Deleted account'
    return user.get_full_name().strip() or user.username


def _record(p, prices):
    days = p.subscription.days if p.subscription else 0
    amount = p.amount or ZERO
    priced = amount > 0
    list_price = _list_price(days, prices)
    return {
        'id': p.pk,
        'cust': p.user_id or f'deleted-{p.pk}',
        'user': p.user,
        'at': p.date,
        'end': p.expiration_date,
        'days': days,
        'plan': payment_plan(p),
        'method': payment_method(p),
        'amount': amount,
        'priced': priced,
        'list': list_price,
        'discount': max(list_price - amount, ZERO) if priced and list_price else ZERO,
        'free_value': ZERO if priced else (list_price or ZERO),
        # Normalised to 30 days so monthly and annual plans add up on one scale.
        'mrr': (amount * 30 / days) if priced and days else ZERO,
        'code': (p.discount_code_used or '').strip().upper(),
    }


def _load(exclude_ids, prices):
    qs = (UserPayment.objects.filter(status='paid', date__gte=report_start())
          .select_related('subscription', 'user').order_by('date', 'id'))
    if exclude_ids:
        qs = qs.exclude(user_id__in=exclude_ids)
    recs = [_record(p, prices) for p in qs]
    seen = set()
    for r in recs:  # oldest first, so the first priced payment per customer is "new"
        if not r['priced']:
            r['kind'] = 'free'
        elif r['cust'] in seen:
            r['kind'] = 'repeat'
        else:
            r['kind'] = 'new'
            seen.add(r['cust'])
    return recs


# ── Recurring revenue ───────────────────────────────────────────────────────

def running_plans(recs, at):
    """{customer: the newest paid plan running at that moment}."""
    newest = {}
    for r in recs:
        if r['priced'] and r['end'] and r['at'] <= at < r['end']:
            cur = newest.get(r['cust'])
            if cur is None or r['at'] > cur['at']:
                newest[r['cust']] = r
    return newest


def mrr_by_customer(recs, at):
    return {c: r['mrr'] for c, r in running_plans(recs, at).items()}


def _mrr_movement(recs, start, end, end_label):
    """What moved MRR through the period. Measured week by week, so a customer who joined and
    left inside a long period still shows up in both rows. Start + changes = end, exactly."""
    first_paid = {}
    for r in recs:
        if r['priced']:
            first_paid.setdefault(r['cust'], r['at'])
    checkpoints = [start]
    while checkpoints[-1] + MOVEMENT_STEP < end:
        checkpoints.append(checkpoints[-1] + MOVEMENT_STEP)
    checkpoints.append(end)

    amounts = defaultdict(lambda: ZERO)
    counts = defaultdict(int)
    before = first = mrr_by_customer(recs, start)
    for step_start, step_end in zip(checkpoints, checkpoints[1:]):
        after = mrr_by_customer(recs, step_end)
        for c in set(before) | set(after):
            a, b = before.get(c, ZERO), after.get(c, ZERO)
            if not a:
                kind, value = ('new' if first_paid[c] >= step_start else 'reactivated'), b
            elif not b:
                kind, value = 'churned', a
            elif b > a:
                kind, value = 'expansion', b - a
            elif b < a:
                kind, value = 'contraction', a - b
            else:
                continue
            amounts[kind] += value
            counts[kind] += 1
        before = after
    last = before
    start_mrr, end_mrr = sum(first.values(), ZERO), sum(last.values(), ZERO)
    rows = [
        ('start', 'MRR at the start', start_mrr, len(first), 0),
        ('new', 'New customers', amounts['new'], counts['new'], 1),
        ('reactivated', 'Came back', amounts['reactivated'], counts['reactivated'], 1),
        ('expansion', 'Moved to a pricier plan', amounts['expansion'], counts['expansion'], 1),
        ('contraction', 'Moved to a cheaper plan', amounts['contraction'], counts['contraction'], -1),
        ('churned', 'Stopped paying', amounts['churned'], counts['churned'], -1),
        ('end', end_label, end_mrr, len(last), 0),
    ]
    scale = max([start_mrr, end_mrr, *amounts.values(), Decimal('1')])
    return {
        'start': start_mrr, 'end': end_mrr, 'customers_start': len(first), 'customers_end': len(last),
        'amounts': dict(amounts), 'counts': dict(counts),
        'rows': [{
            'key': key, 'label': label, 'value': value, 'value_label': _money(value),
            'count': n, 'sign': sign, 'pct': float(value / scale * 100),
        } for key, label, value, n, sign in rows if sign == 0 or value],
    }


# ── Renewals ────────────────────────────────────────────────────────────────

def renewal_outcomes(recs, now):
    """Every plan that has ended (or is about to), with whether the customer paid again in time.

    'renewed'  - paid again before the end or within RENEWAL_GRACE after it.
    'pending'  - ended less than RENEWAL_GRACE ago with no new payment yet: undecided.
    'lapsed'   - the grace window passed without a payment.
    Free passes use the same rule, and "renewed" means the customer went on to pay.
    """
    priced_by_cust = defaultdict(list)
    for r in recs:
        if r['priced']:
            priced_by_cust[r['cust']].append(r)
    out = []
    for r in recs:
        if not r['end'] or r['end'] > now:
            continue
        later = [x for x in priced_by_cust[r['cust']] if x['at'] > r['at']]
        if any(x['at'] <= r['end'] + RENEWAL_GRACE for x in later):
            state = 'renewed'
        elif r['end'] + RENEWAL_GRACE > now:
            state = 'pending'
        else:
            state = 'lapsed'
        out.append({'rec': r, 'state': state})
    return out


def _rate_of(outcomes):
    renewed = sum(1 for o in outcomes if o['state'] == 'renewed')
    decided = sum(1 for o in outcomes if o['state'] != 'pending')
    return {
        'renewed': renewed, 'decided': decided,
        'lapsed': decided - renewed,
        'pending': len(outcomes) - decided,
        'rate': _rate(renewed, decided),
    }


def _renewals(outcomes, period):
    paid = [o for o in outcomes if o['rec']['priced']]
    in_period = [o for o in paid if _in(o['rec']['end'], period.start, period.end)]
    passes = [o for o in outcomes if not o['rec']['priced'] and _in(o['rec']['end'], period.start, period.end)]
    return {
        'period': _rate_of(in_period),
        'all_time': _rate_of(paid),
        'monthly': _rate_of([o for o in paid if o['rec']['plan'] == 'monthly']),
        'annual': _rate_of([o for o in paid if o['rec']['plan'] == 'annual']),
        'free_passes': _rate_of(passes),
    }


# ── Forecast ────────────────────────────────────────────────────────────────

def _last_seen(user_ids):
    seen = dict(Profile.objects.filter(user_id__in=user_ids).values_list('user_id', 'last_seen'))
    logins = dict(CustomUser.objects.filter(id__in=user_ids).values_list('id', 'last_login'))
    return {uid: max(filter(None, (seen.get(uid), logins.get(uid))), default=None) for uid in user_ids}


def _upcoming(recs, now, renewal_rate):
    """Customers paying today, when their paid-up time runs out, and what they last paid."""
    paying = mrr_by_customer(recs, now)
    by_cust = defaultdict(list)
    for r in recs:
        by_cust[r['cust']].append(r)
    user_ids = [c for c in paying if isinstance(c, int)]
    last_seen = _last_seen(user_ids)
    rows = []
    for cust in paying:
        mine = by_cust[cust]
        due = max(r['end'] for r in mine if r['end'])
        last = max((r for r in mine if r['priced']), key=lambda r: r['at'])
        seen = last_seen.get(cust)
        quiet = seen is None or now - seen > timedelta(days=QUIET_DAYS)
        rows.append({
            'user_id': cust if isinstance(cust, int) else None,
            'name': _name(last['user']), 'email': last['user'].email if last['user'] else '',
            'plan': PLAN_LABELS[last['plan']], 'due': due, 'days_left': max((due - now).days, 0),
            'value': last['amount'], 'value_label': _money(last['amount']),
            'last_seen': seen, 'quiet': quiet,
        })
    rows.sort(key=lambda r: r['due'])

    def window(days):
        hits = [r for r in rows if r['due'] - now <= timedelta(days=days)]
        value = sum((r['value'] for r in hits), ZERO)
        return {'count': len(hits), 'value': value, 'value_label': _money(value),
                'quiet': sum(1 for r in hits if r['quiet'])}

    today = timezone.localdate(now)
    weeks = []
    for i in range(FORECAST_WEEKS):
        lo, hi = today + timedelta(weeks=i), today + timedelta(weeks=i + 1)
        hits = [r for r in rows if lo <= timezone.localtime(r['due']).date() < hi]
        weeks.append({'label': f'Wk of {lo.day} {lo:%b}', 'short': f'{lo.day} {lo:%b}', 'count': len(hits),
                      'value': float(sum((r['value'] for r in hits), ZERO))})
    horizon = today + timedelta(weeks=FORECAST_WEEKS)
    later = [r for r in rows if timezone.localtime(r['due']).date() >= horizon]
    due30 = window(30)
    expected = (due30['value'] * Decimal(str(renewal_rate)) / 100) if renewal_rate is not None else None
    return {
        'rows': rows,
        'next30': due30, 'next60': window(60), 'next90': window(90),
        'expected30': expected, 'expected30_label': _money(expected) if expected is not None else None,
        'weeks': weeks,
        'weeks_due': sum(w['count'] for w in weeks),
        'later_count': len(later),
        'later_value_label': _money(sum((r['value'] for r in later), ZERO)),
    }


# ── Trend & pace ────────────────────────────────────────────────────────────

def _trend(period, recs, now):
    in_period = [r for r in recs if _in(r['at'], period.start, period.end)]
    unit, edges = _buckets(period, in_period[0]['at'] if in_period else None)
    if not edges:
        return {'unit': unit, 'points': []}
    new, repeat = [ZERO] * len(edges), [ZERO] * len(edges)
    orders, passes = [0] * len(edges), [0] * len(edges)
    for r in in_period:
        i = _bucket_index(edges, timezone.localtime(r['at']).date())
        if i is None:
            continue
        if r['kind'] == 'free':
            passes[i] += 1
            continue
        orders[i] += 1
        if r['kind'] == 'new':
            new[i] += r['amount']
        else:
            repeat[i] += r['amount']

    fmt = {'day': '%d %b', 'week': 'Wk of %d %b', 'month': '%b %Y'}[unit]
    points = []
    for i, edge in enumerate(edges):
        nxt = edges[i + 1] if i + 1 < len(edges) else None
        close = (min(timezone.make_aware(datetime.combine(nxt, time.min)), now) if nxt else min(period.end, now))
        mrr = mrr_by_customer(recs, close)
        points.append({
            'label': edge.strftime(fmt),
            'short': edge.strftime('%b' if unit == 'month' else '%d %b'),
            'new': float(new[i]), 'repeat': float(repeat[i]), 'revenue': float(new[i] + repeat[i]),
            'orders': orders[i], 'passes': passes[i],
            'mrr': float(sum(mrr.values(), ZERO)), 'customers': len(mrr),
        })
    return {'unit': unit, 'points': points}


def _cumulative(recs, start, days):
    daily = [ZERO] * days
    for r in recs:
        if r['priced'] and r['at'] >= start:
            i = (r['at'] - start).days
            if 0 <= i < days:
                daily[i] += r['amount']
    out, total = [], ZERO
    for v in daily:
        total += v
        out.append(float(total))
    return out


def _pace(period, recs, now):
    """Cumulative revenue day by day through the period, and the previous period beside it."""
    days = max(1, -(-int((min(period.end, now) - period.start).total_seconds()) // 86400))
    cur = _cumulative(recs, period.start, days)
    prev = _cumulative(recs, period.previous.start, days) if period.previous else None
    first = timezone.localtime(period.start).date()
    return [{
        'label': _day_label(first + timedelta(days=i)),
        'short': f'{(first + timedelta(days=i)).day} {(first + timedelta(days=i)):%b}',
        'day': i + 1, 'cur': cur[i], 'prev': prev[i] if prev else None,
    } for i in range(days)]


# ── Mix: plans, methods, discounts ──────────────────────────────────────────

def _plan_mix(priced, mrr_now_by_plan):
    total = sum((r['amount'] for r in priced), ZERO)
    total_mrr = sum(mrr_now_by_plan.values(), ZERO)
    rows = []
    for key in ('monthly', 'annual', 'other'):
        mine = [r for r in priced if r['plan'] == key]
        if not mine and not mrr_now_by_plan.get(key):
            continue
        revenue = sum((r['amount'] for r in mine), ZERO)
        rows.append({
            'key': key, 'label': PLAN_LABELS[key], 'orders': len(mine),
            'revenue': revenue, 'revenue_label': _money(revenue), 'share': _rate(revenue, total),
            'avg_label': _money(revenue / len(mine)) if mine else '—',
            'mrr_label': _money(mrr_now_by_plan.get(key, ZERO)),
            'mrr_share': _rate(mrr_now_by_plan.get(key, ZERO), total_mrr),
        })
    return rows


def _method_mix(priced):
    total = sum((r['amount'] for r in priced), ZERO)
    rows = []
    for key in ('card', 'wallet', 'coupon', 'school', 'admin'):
        mine = [r for r in priced if r['method'] == key]
        if not mine:
            continue
        revenue = sum((r['amount'] for r in mine), ZERO)
        rows.append({'key': key, 'label': METHOD_LABELS[key], 'orders': len(mine),
                     'revenue_label': _money(revenue), 'share': _rate(revenue, total)})
    return rows


def _discounts(period_recs):
    priced = [r for r in period_recs if r['priced']]
    listed = sum((r['list'] or r['amount'] for r in priced), ZERO)
    given = sum((r['discount'] for r in priced), ZERO)
    free_value = sum((r['free_value'] for r in period_recs if not r['priced']), ZERO)
    codes = defaultdict(lambda: {'uses': 0, 'paid': 0, 'free': 0, 'revenue': ZERO, 'cost': ZERO})
    for r in period_recs:
        if not r['code']:
            continue
        c = codes[r['code']]
        c['uses'] += 1
        if r['priced']:
            c['paid'] += 1
            c['revenue'] += r['amount']
            c['cost'] += r['discount']
        else:
            c['free'] += 1
            c['cost'] += r['free_value']
    rows = sorted(({'code': code, **v, 'revenue_label': _money(v['revenue']), 'cost_label': _money(v['cost'])}
                   for code, v in codes.items()), key=lambda c: (-c['cost'], -c['uses'], c['code']))
    return {
        'listed': listed, 'listed_label': _money(listed),
        'given': given, 'given_label': _money(given),
        'share': _rate(given, listed),
        'discounted_orders': sum(1 for r in priced if r['discount'] > 0),
        'orders': len(priced),
        'free_count': sum(1 for r in period_recs if not r['priced']),
        'free_value': free_value, 'free_value_label': _money(free_value),
        'codes': rows,
    }


# ── Customers ───────────────────────────────────────────────────────────────

def _editor_signups(start, end, exclude_ids):
    qs = (CustomUser.objects.filter(date_joined__gte=max(start, report_start()), date_joined__lt=end)
          .exclude(username__in=MOCK_USERNAMES)
          .exclude(user_account__account_type__in=NON_EDITOR_TYPES))
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)
    return list(qs.values_list('id', 'date_joined'))


def _conversion(period, recs, exclude_ids):
    first_paid = {}
    for r in recs:
        if r['priced']:
            first_paid.setdefault(r['cust'], r['at'])
    signups = _editor_signups(period.start, period.end, exclude_ids)
    paid = sum(1 for uid, _ in signups if uid in first_paid)
    return {'signups': len(signups), 'paid': paid, 'rate': _rate(paid, len(signups))}


def _customers(recs, now):
    priced = [r for r in recs if r['priced']]
    total = sum((r['amount'] for r in priced), ZERO)
    by_cust = defaultdict(list)
    for r in priced:
        by_cust[r['cust']].append(r)
    paying_now = mrr_by_customer(recs, now)
    rows = []
    for cust, mine in by_cust.items():
        revenue = sum((r['amount'] for r in mine), ZERO)
        user = mine[-1]['user']
        rows.append({
            'user_id': cust if isinstance(cust, int) else None,
            'name': _name(user), 'email': user.email if user else '',
            'orders': len(mine), 'revenue': revenue, 'revenue_label': _money(revenue),
            'share': _rate(revenue, total), 'since': mine[0]['at'],
            'plan': PLAN_LABELS[mine[-1]['plan']], 'active': cust in paying_now,
        })
    rows.sort(key=lambda c: (-c['revenue'], c['name']))

    joined = dict(CustomUser.objects.filter(id__in=[c for c in by_cust if isinstance(c, int)])
                  .values_list('id', 'date_joined'))
    waits = [(mine[0]['at'] - joined[c]).days for c, mine in by_cust.items()
             if c in joined and joined[c] >= report_start()]
    top3 = sum((c['revenue'] for c in rows[:3]), ZERO)
    count = len(rows)
    return {
        'top': rows[:TOP_CUSTOMERS],
        'count': count,
        'repeat_count': sum(1 for c in rows if c['orders'] > 1),
        'ltv': (total / count) if count else None,
        'ltv_label': _money(total / count) if count else '—',
        'top3_share': _rate(top3, total),
        'days_to_pay': median(waits) if waits else None,
        'total_label': _money(total),
    }


def _receipts_waiting(exclude_ids):
    qs = ManualPayment.objects.filter(status__in=('pending', 'needs_review'), created_at__gte=report_start())
    if exclude_ids:
        qs = qs.exclude(user_id__in=exclude_ids)
    amounts = list(qs.values_list('amount_expected', flat=True))
    value = sum(amounts, ZERO)
    return {'count': len(amounts), 'value': value, 'value_label': _money(value)}


# ── Narrative ───────────────────────────────────────────────────────────────

def _plural(n, one, many=None):
    return f'{n:,} {one if n == 1 else (many or one + "s")}'


def _pct(value):
    return f'{value:g}%'


def _summary(period, revenue, rev_delta, movement, upcoming, renewals):
    """Three plain sentences an owner can read in ten seconds."""
    if period.key == 'all':
        when = 'since launch'
    elif period.key == 'custom':
        when = f'between {period.label.replace(" – ", " and ")}'
    else:
        when = f'over the {period.label[0].lower()}{period.label[1:]}'
    s1 = f'EGP {_money(revenue)} came in {when}'
    if rev_delta and rev_delta['value'] is not None:
        word = 'up' if rev_delta['value'] > 0 else 'down' if rev_delta['value'] < 0 else 'level'
        s1 += (f', {word} {abs(rev_delta["value"])}% on the {period.previous.label}'
               if word != 'level' else f', level with the {period.previous.label}')
    sentences = [s1 + '.']

    mrr, n = movement['end'], movement['customers_end']
    if n:
        sentences.append(f'Recurring revenue is EGP {_money(mrr)} a month (EGP {_money(mrr * 12)} a year) '
                         f'from {_plural(n, "paying customer")}.')
    else:
        sentences.append('No one has a paid plan running right now.')

    due = upcoming['next30']
    if due['count']:
        line = f'{_plural(due["count"], "renewal")} worth EGP {due["value_label"]} {"is" if due["count"] == 1 else "are"} due in the next 30 days'
        rate = renewals['all_time']
        if upcoming['expected30'] is not None and rate['decided'] >= MIN_RATE_SAMPLE:
            line += f'; at the {_pct(rate["rate"])} renewal rate so far, expect about EGP {upcoming["expected30_label"]}'
        sentences.append(line + '.')
    return sentences


def _insights(ctx):
    """Decisions, not observations: each one says what to do. Most urgent first."""
    out = []
    upcoming, renewals, movement = ctx['upcoming'], ctx['renewals'], ctx['movement']
    discounts, prices = ctx['discounts'], ctx['prices']

    due = upcoming['next30']
    if due['count']:
        body = (f'Their plans end by {_day_label(timezone.localtime(upcoming["rows"][due["count"] - 1]["due"]).date())}. ')
        if due['quiet']:
            body += (f'{_plural(due["quiet"], "of them has", "of them have")} not opened Skillifly for '
                     f'{QUIET_DAYS}+ days, so start with {"that one" if due["quiet"] == 1 else "those"}. ')
        body += 'A personal reminder before the end date is the cheapest revenue you will get this month.'
        out.append({'tone': 'action', 'title': f'Remind {_plural(due["count"], "customer")} to renew '
                                                f'(EGP {due["value_label"]})', 'body': body,
                    'link': '#renewals', 'link_label': 'See who'})

    waiting = ctx['receipts']
    if waiting['count']:
        out.append({'tone': 'action',
                    'title': f'EGP {waiting["value_label"]} is waiting on receipt checks',
                    'body': f'{_plural(waiting["count"], "customer")} sent an InstaPay or Vodafone Cash receipt '
                            'that still needs a human look. Approving them turns it into revenue.',
                    'link': 'review', 'link_label': 'Review receipts'})

    churned = movement['amounts'].get('churned', ZERO)
    if churned:
        n = movement['counts']['churned']
        out.append({'tone': 'risk', 'title': f'{_plural(n, "customer")} stopped paying',
                    'body': f'That is EGP {_money(churned)} a month of recurring revenue gone in this period. '
                            'Their portfolios went private when the plan ended; a win-back message with what '
                            'they lose usually works best in the first month.',
                    'link': 'winback', 'link_label': 'Win-back list'})

    rate = renewals['period']
    if rate['decided'] >= 3 and rate['rate'] is not None and rate['rate'] < 50:
        out.append({'tone': 'risk', 'title': f'Only {_pct(rate["rate"])} of plans that ended were renewed',
                    'body': f'{rate["renewed"]} of {rate["decided"]} renewed. Reminders before the end date and '
                            'a renewal offer inside the dashboard are the two levers to test first.'})

    d = ctx['rev_delta']
    cur_n, prev_n = ctx['orders'], ctx['prev_orders']
    if d and d['value'] is not None and abs(d['value']) >= 15 and cur_n + (prev_n or 0) >= 4:
        aov, prev_aov = ctx['aov'], ctx['prev_aov']
        driver = f'{_plural(cur_n, "paid order")} against {prev_n}'
        if aov and prev_aov:
            driver += f', average order EGP {_money(aov)} against {_money(prev_aov)}'
        if d['value'] < 0:
            out.append({'tone': 'risk', 'title': f'Revenue is down {abs(d["value"])}% on the {ctx["previous_label"]}',
                        'body': f'{driver}. ' + ('Fewer people are paying: check traffic to pricing and checkout drop-off.'
                                                 if cur_n < (prev_n or 0) else
                                                 'As many orders, smaller ones: check which discount codes are in use.'),
                        'link': 'funnel', 'link_label': 'Payment funnel'})
        else:
            out.append({'tone': 'info', 'title': f'Revenue is up {d["value"]}% on the {ctx["previous_label"]}',
                        'body': f'{driver}. Find what changed (a campaign, a partner code, a school) and repeat it.'})

    if discounts['orders'] >= 3 and (discounts['share'] or 0) >= 25:
        top = discounts['codes'][0] if discounts['codes'] else None
        body = f'Paid orders listed at EGP {discounts["listed_label"]} brought in EGP {_money(discounts["listed"] - discounts["given"])}. '
        if top and top['cost'] > 0:
            body += f'{top["code"]} alone cost EGP {top["cost_label"]} over {_plural(top["uses"], "use")}. '
        body += 'Give partner codes an end date or a use limit, and keep the public code smaller.'
        out.append({'tone': 'risk', 'title': f'Discounts took {_pct(discounts["share"])} off list price',
                    'body': body, 'link': 'codes', 'link_label': 'Discount codes'})

    monthly = renewals['monthly']
    if monthly['decided'] >= MIN_RATE_SAMPLE and monthly['rate'] is not None:
        r = min(monthly['rate'], 95) / 100
        worth = prices['monthly'] / Decimal(str(1 - r))
        if worth < prices['annual']:
            out.append({'tone': 'info', 'title': 'Annual is worth more than monthly',
                        'body': f'Monthly plans renew {_pct(monthly["rate"])} of the time, so a monthly customer '
                                f'brings in about EGP {_money(worth)} before leaving. Annual brings EGP '
                                f'{_money(prices["annual"])} on day one. Lead with annual on pricing.'})
        else:
            out.append({'tone': 'info', 'title': 'Monthly customers stay',
                        'body': f'Monthly plans renew {_pct(monthly["rate"])} of the time, worth about EGP '
                                f'{_money(worth)} each, more than an annual plan. Deep annual discounts are not needed.'})

    customers = ctx['customers']
    if customers['count'] >= 5 and (customers['top3_share'] or 0) >= 50:
        out.append({'tone': 'info', 'title': f'3 customers bring {_pct(customers["top3_share"])} of all revenue',
                    'body': 'Losing one of them would show. Treat them as accounts: check in personally before renewal.'})

    passes = renewals['free_passes']
    if passes['decided'] >= 3:
        out.append({'tone': 'info',
                    'title': f'{_pct(passes["rate"] or 0)} of free passes turned into paying customers',
                    'body': f'{passes["renewed"]} of {passes["decided"]} free passes that ended were followed by a payment. '
                            + ('Free passes are working as a trial.' if (passes['rate'] or 0) >= 30 else
                               'Most free users leave when the pass ends: send an offer a week before it does.')})

    order = {'action': 0, 'risk': 1, 'info': 2}
    out.sort(key=lambda i: order[i['tone']])
    return out[:6]


# ── Assembly ────────────────────────────────────────────────────────────────

def _period_totals(recs, period):
    rows = [r for r in recs if _in(r['at'], period.start, period.end)]
    priced = [r for r in rows if r['priced']]
    revenue = sum((r['amount'] for r in priced), ZERO)
    return {
        'rows': rows, 'priced': priced, 'revenue': revenue, 'orders': len(priced),
        'aov': (revenue / len(priced)) if priced else None,
        'new_revenue': sum((r['amount'] for r in priced if r['kind'] == 'new'), ZERO),
        'new_customers': sum(1 for r in priced if r['kind'] == 'new'),
    }


def _ledger_row(r):
    return {
        'date': r['at'], 'name': _name(r['user']), 'email': r['user'].email if r['user'] else '',
        'user_id': r['user'].pk if r['user'] else None,
        'kind': r['kind'], 'kind_label': KIND_LABELS[r['kind']],
        'plan': PLAN_LABELS[r['plan']], 'method': METHOD_LABELS[r['method']], 'code': r['code'],
        'list': r['list'], 'amount': r['amount'], 'discount': r['discount'], 'end': r['end'],
        'amount_label': _money(r['amount']),
        'discount_label': _money(r['discount']) if r['discount'] else '',
    }


def build_report(period_param=DEFAULT_PERIOD, start=None, end=None, include_team=False, now=None):
    now = now or timezone.now()
    period = resolve_period(period_param, start, end, now)
    exclude = set() if include_team else team_user_ids()
    prices = plan_prices()
    recs = _load(exclude, prices)

    cur = _period_totals(recs, period)
    prev = _period_totals(recs, period.previous) if period.previous else None
    outcomes = renewal_outcomes(recs, now)
    renewals = _renewals(outcomes, period)
    prev_renewals = _renewals(outcomes, period.previous)['period'] if period.previous else None
    period_end = min(period.end, now)
    movement = _mrr_movement(recs, period.start, period_end,
                             'MRR now' if now - period_end < timedelta(minutes=1) else 'MRR at the end')
    upcoming = _upcoming(recs, now, renewals['all_time']['rate']
                         if renewals['all_time']['decided'] >= MIN_RATE_SAMPLE else None)
    conversion = _conversion(period, recs, exclude)
    prev_conversion = _conversion(period.previous, recs, exclude) if period.previous else None
    discounts = _discounts(cur['rows'])
    prev_discounts = _discounts(prev['rows']) if prev else None
    customers = _customers(recs, now)

    mrr_now_by_plan = defaultdict(lambda: ZERO)
    for r in running_plans(recs, now).values():
        mrr_now_by_plan[r['plan']] += r['mrr']

    rev_delta = _delta(cur['revenue'], prev['revenue']) if prev else None
    mrr_delta = _delta(movement['end'], movement['start'])
    period_rate = renewals['period']

    kpis = [
        {'key': 'revenue', 'label': 'Revenue', 'value': _money(cur['revenue']), 'unit': 'EGP',
         'sub': (f'{_plural(cur["orders"], "paid order")} · average EGP {_money(cur["aov"])}'
                 if cur['orders'] else 'No paid orders'),
         'delta': rev_delta, 'vs': period.previous.label if period.previous else None},
        {'key': 'mrr', 'label': 'Monthly recurring revenue', 'value': _money(movement['end']), 'unit': 'EGP / mo',
         'sub': f'EGP {_money(movement["end"] * 12)} a year at this rate',
         'delta': mrr_delta, 'vs': 'start of the period'},
        {'key': 'paying', 'label': 'Paying customers', 'value': f'{movement["customers_end"]:,}', 'unit': '',
         'sub': (f'{movement["counts"].get("new", 0)} new · {movement["counts"].get("reactivated", 0)} back · '
                 f'{movement["counts"].get("churned", 0)} left'),
         'delta': _delta(movement['customers_end'], movement['customers_start']), 'vs': 'start of the period'},
        {'key': 'renewal', 'label': 'Renewal rate',
         'value': _pct(period_rate['rate']) if period_rate['rate'] is not None else '—', 'unit': '',
         'sub': (f'{period_rate["renewed"]} of {period_rate["decided"]} plans that ended'
                 + (f' · {period_rate["pending"]} undecided' if period_rate['pending'] else '')
                 if period_rate['decided'] or period_rate['pending'] else 'No paid plan ended in this period'),
         'delta': (_delta(period_rate['rate'], prev_renewals['rate'], pct_points=True)
                   if prev_renewals and period_rate['rate'] is not None and prev_renewals['rate'] is not None else None),
         'vs': period.previous.label if period.previous else None},
        {'key': 'signup', 'label': 'Signups who paid',
         'value': _pct(conversion['rate']) if conversion['rate'] is not None else '—', 'unit': '',
         'sub': f'{conversion["paid"]} of {_plural(conversion["signups"], "editor")} who signed up in the period',
         'delta': (_delta(conversion['rate'], prev_conversion['rate'], pct_points=True)
                   if prev_conversion and conversion['rate'] is not None and prev_conversion['rate'] is not None else None),
         'vs': period.previous.label if period.previous else None},
        {'key': 'discount', 'label': 'Discounts given', 'value': discounts['given_label'], 'unit': 'EGP',
         'sub': (f'{_pct(discounts["share"])} off list price on paid orders'
                 if discounts['share'] is not None else 'No paid orders')
                + (f' · {_plural(discounts["free_count"], "free pass", "free passes")}' if discounts['free_count'] else ''),
         'delta': _delta(discounts['given'], prev_discounts['given']) if prev_discounts else None,
         'vs': period.previous.label if period.previous else None, 'up_is_bad': True},
    ]

    ctx = {
        'upcoming': upcoming, 'renewals': renewals, 'movement': movement, 'discounts': discounts,
        'prices': prices, 'receipts': _receipts_waiting(exclude), 'customers': customers,
        'rev_delta': rev_delta, 'orders': cur['orders'], 'prev_orders': prev['orders'] if prev else None,
        'aov': cur['aov'], 'prev_aov': prev['aov'] if prev else None,
        'previous_label': period.previous.label if period.previous else '',
    }
    ledger = [_ledger_row(r) for r in reversed(cur['rows'])]

    return {
        'period': period,
        'now': now,
        'include_team': include_team,
        'team_excluded': len(exclude),
        'has_data': bool(recs) or ctx['receipts']['count'] > 0,
        'small_sample': 0 < cur['orders'] < SMALL_SAMPLE,
        'revenue': cur['revenue'], 'revenue_label': _money(cur['revenue']),
        'rev_delta': rev_delta,
        'prev_revenue_label': _money(prev['revenue']) if prev else None,
        'summary': _summary(period, cur['revenue'], rev_delta, movement, upcoming, renewals),
        'kpis': kpis,
        'insights': _insights(ctx),
        'pace': _pace(period, recs, now),
        'trend': _trend(period, recs, now),
        'movement': movement,
        'renewals': renewals,
        'upcoming': upcoming,
        'plan_rows': _plan_mix(cur['priced'], mrr_now_by_plan),
        'method_rows': _method_mix(cur['priced']),
        'discounts': discounts,
        'customers': customers,
        'conversion': conversion,
        'receipts': ctx['receipts'],
        'prices': {k: _money(v) for k, v in prices.items()},
        'orders': cur['orders'],
        'new_revenue_label': _money(cur['new_revenue']),
        'repeat_revenue_label': _money(cur['revenue'] - cur['new_revenue']),
        'new_customers': cur['new_customers'],
        'ledger': ledger[:LEDGER_LIMIT],
        'ledger_total': len(ledger),
        'ledger_all': ledger,
        'quiet_days': QUIET_DAYS,
        'grace_days': RENEWAL_GRACE.days,
    }
