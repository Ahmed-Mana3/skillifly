"""Payment funnel & revenue report behind /manage/payment-tracking/.

Two sources, and the report never mixes up which one a number comes from:

* ``PaymentTrackingEvent`` - what visitors *did* (page opens, button clicks).
  It measures intent: who reached pricing, picked a plan, started checkout.
* ``UserPayment`` / ``ManualPayment`` - what was actually *paid*. Every money
  number comes from here. The success page can be opened (or refreshed)
  without a verified payment behind it, so page views never count as sales.

The funnel counts people, not page loads: a visitor who opens pricing five
times is one visitor. A guest who signs in mid-flow is merged with their
account, so they are not counted twice.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from core.models import CustomUser, ManualPayment, PaymentTrackingEvent, Profile, UserPayment

PERIODS = {'7': 7, '30': 30, '90': 90, 'all': None}
DEFAULT_PERIOD = '30'

# Funnel stages, in order. A person counts in a stage when they got at least
# that far, so every stage is a subset of the one before it.
STAGES = [
    (1, 'pricing', 'Saw pricing'),
    (2, 'picked', 'Picked a plan'),
    (3, 'checkout', 'Started checkout'),
    (4, 'paid', 'Subscribed'),
]
STAGE_LABELS = {n: label for n, _, label in STAGES}
# "...left before they <verb>": how the drop after each step reads.
NEXT_VERBS = {'pricing': 'picked a plan', 'picked': 'started checkout', 'checkout': 'paid'}

CHECKOUT_PAGES = {'manual_payment', 'fawaterk_checkout', 'payment_success',
                  'payment_failure', 'fawaterk_pending'}

METHOD_LABELS = {
    'card': 'Card (Fawaterk)',
    'wallet': 'InstaPay / Vodafone Cash',
    'coupon': 'Free with coupon',
    'school': 'School code',
    'admin': 'Added by admin',
}
PLAN_LABELS = {'monthly': 'Monthly', 'annual': 'Annual', 'other': 'Other'}

# Below this many people at a step, rates swing too much to act on.
MIN_SAMPLE = 20
# A card checkout still pending after this long was abandoned, not slow.
CARD_PENDING_GRACE = timedelta(hours=1)
# A payment can be recorded a moment before the event that led to it.
PAYMENT_MATCH_SLACK = timedelta(minutes=5)


# Nothing before this date counts anywhere on the report ("All time" starts here).
# Earlier payments are test/launch-era records that would distort the numbers.
REPORT_START_DATE = date(2026, 5, 1)


def report_start():
    """REPORT_START_DATE at midnight in the project's timezone."""
    return timezone.make_aware(datetime.combine(REPORT_START_DATE, time.min))


@dataclass
class Period:
    key: str
    days: int | None
    start: object  # aware datetime, never before report_start()
    end: object
    label: str

    @property
    def previous(self):
        """The same-length window just before this one, cut at the report start."""
        if not self.days:
            return None
        floor = report_start()
        if self.start <= floor:
            return None
        start = max(self.start - timedelta(days=self.days), floor)
        return Period(self.key, self.days, start, self.start, f'previous {self.days} days')


def resolve_period(param, now=None):
    now = now or timezone.now()
    key = param if param in PERIODS else DEFAULT_PERIOD
    days = PERIODS[key]
    floor = report_start()
    since = f'{REPORT_START_DATE.day} {REPORT_START_DATE:%b %Y}'
    if days is None:
        return Period(key, None, floor, now, f'All time (since {since})')
    start = now - timedelta(days=days)
    if start < floor:
        return Period(key, days, floor, now, f'Last {days} days (from {since})')
    return Period(key, days, start, now, f'Last {days} days')


def team_user_ids():
    """Staff and superusers: their test runs through checkout aren't demand."""
    return set(CustomUser.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
               .values_list('id', flat=True))


def _in_period(qs, field, period):
    if period.start is not None:
        qs = qs.filter(**{f'{field}__gte': period.start})
    return qs.filter(**{f'{field}__lt': period.end})


def _device(user_agent):
    ua = (user_agent or '').lower()
    if not ua:
        return 'Unknown'
    if 'ipad' in ua or 'tablet' in ua or ('android' in ua and 'mobile' not in ua):
        return 'Tablet'
    if 'mobi' in ua or 'iphone' in ua or 'android' in ua:
        return 'Mobile'
    return 'Desktop'


def payment_method(payment):
    """Where a UserPayment came from, read off the key each flow stamps on it."""
    key = payment.fawaterk_intent_key or ''
    if not key:
        return 'admin'
    if key.startswith('MANUAL-SCHOOL-'):
        return 'school'
    if key.startswith(('MANUAL-COUPON-', 'MANUAL-MASTER-')):
        return 'coupon'
    if key.startswith('MANUAL-'):
        return 'wallet'
    return 'card'


def payment_plan(payment):
    days = payment.subscription.days if payment.subscription else None
    if not days:
        return 'other'
    return 'annual' if days >= 300 else 'monthly'


# ── Events → people ────────────────────────────────────────────────────────

def _load_events(period, exclude_ids):
    rows = list(
        _in_period(PaymentTrackingEvent.objects.all(), 'created_at', period)
        .order_by('created_at')
        .values_list('session_id', 'user_id', 'event_type', 'page', 'action',
                     'plan_type', 'created_at', 'user_agent')
    )
    if exclude_ids:
        # A team member's guest-phase events share their visitor id; drop those too.
        team_sessions = {r[0] for r in rows if r[1] in exclude_ids}
        rows = [r for r in rows if r[1] not in exclude_ids and r[0] not in team_sessions]
    return rows


def _plan_from(action, plan_type):
    if plan_type in ('monthly', 'pro_monthly'):
        return 'monthly'
    if plan_type == 'pro_annual':
        return 'annual'
    if action == 'plan_monthly':
        return 'monthly'
    if action == 'plan_annual':
        return 'annual'
    return ''


def _people(rows):
    """Fold events into one record per person (account if known, else visitor id)."""
    session_user = {}
    for sid, uid, *_ in rows:
        if uid and sid not in session_user:
            session_user[sid] = uid

    people = {}
    for sid, uid, etype, page, action, plan_type, created, ua in rows:
        uid = uid or session_user.get(sid)
        if uid:
            key = f'u{uid}'
        elif sid and sid != 'anon':
            key = f's{sid}'
        else:
            continue  # legacy rows with no identity can't be counted as people
        p = people.get(key)
        if p is None:
            p = people[key] = {
                'key': key, 'user_id': uid, 'stage': 0, 'first': created,
                'last': created, 'opens': 0, 'clicks': 0, 'plan': '',
                'device': _device(ua), 'pricing_opens': 0,
            }
        p['user_id'] = p['user_id'] or uid
        p['last'] = created
        if etype == 'page_view':
            p['opens'] += 1
        else:
            p['clicks'] += 1

        stage = 0
        if page == 'payment':
            stage = 1
            if etype == 'page_view':
                p['pricing_opens'] += 1
            if etype == 'click' and action.startswith('plan_'):
                stage = 2
        elif page in CHECKOUT_PAGES:
            stage = 3
        p['stage'] = max(p['stage'], stage)
        plan = _plan_from(action, plan_type)
        if plan:
            p['plan'] = plan
    return people


# ── Ledger ──────────────────────────────────────────────────────────────────

def _load_payments(period, exclude_ids):
    qs = _in_period(UserPayment.objects.select_related('subscription', 'user'), 'date', period)
    if exclude_ids:
        qs = qs.exclude(user_id__in=exclude_ids)
    return list(qs.order_by('date'))


def _first_paid_ids(user_ids):
    """The id of each user's first-ever paid payment (to tell new from renewal)."""
    first = {}
    for pk, uid in (UserPayment.objects.filter(user_id__in=user_ids, status='paid')
                    .order_by('date', 'id').values_list('id', 'user_id')):
        first.setdefault(uid, pk)
    return first


def _ledger(payments):
    paid = [p for p in payments if p.status == 'paid']
    revenue = sum((p.amount for p in paid), Decimal('0'))
    priced = [p for p in paid if p.amount > 0]
    first = _first_paid_ids({p.user_id for p in paid if p.user_id})
    new = sum(1 for p in paid if p.user_id and first.get(p.user_id) == p.id)

    by_method, by_plan = defaultdict(lambda: [0, Decimal('0')]), defaultdict(lambda: [0, Decimal('0')])
    for p in paid:
        for bucket, key in ((by_method, payment_method(p)), (by_plan, payment_plan(p))):
            bucket[key][0] += 1
            bucket[key][1] += p.amount

    return {
        'paid': paid,
        'revenue': revenue,
        'subscriptions': len(paid),
        'paying_customers': len({p.user_id for p in priced if p.user_id}),
        'priced_count': len(priced),
        'free_count': len(paid) - len(priced),
        'new_count': new,
        'renewal_count': len(paid) - new,
        'aov': (revenue / len(priced)) if priced else None,
        'by_method': by_method,
        'by_plan': by_plan,
    }


def _mark_paid(people, paid):
    """A person subscribed if one of their paid payments came after their first visit."""
    by_user = defaultdict(list)
    for p in paid:
        if p.user_id:
            by_user[p.user_id].append(p.date)
    matched = set()
    for person in people.values():
        dates = by_user.get(person['user_id'], ())
        if any(d >= person['first'] - PAYMENT_MATCH_SLACK for d in dates):
            person['stage'] = 4
            matched.add(person['user_id'])
    return matched


def _funnel(people):
    counts = {n: sum(1 for p in people.values() if p['stage'] >= n) for n, _, _ in STAGES}
    top = counts[1]
    steps = []
    for i, (n, key, label) in enumerate(STAGES):
        count = counts[n]
        nxt = counts[STAGES[i + 1][0]] if i + 1 < len(STAGES) else None
        steps.append({
            'n': n, 'key': key, 'label': label, 'count': count,
            'pct_of_start': round(count / top * 100, 1) if top else None,
            'next_label': STAGES[i + 1][2] if nxt is not None else None,
            'next_verb': NEXT_VERBS.get(key),
            'lost': (count - nxt) if nxt is not None else None,
            'lost_pct': round((count - nxt) / count * 100) if nxt is not None and count else None,
            'continue_pct': round(nxt / count * 100) if nxt is not None and count else None,
        })
    return steps, counts


def _rate(part, whole):
    return round(float(part) / float(whole) * 100, 1) if whole else None


def _pct(value):
    """33.3 -> '33.3%', 50.0 -> '50%'."""
    return f'{value:g}%'


def _core(period, exclude_ids):
    rows = _load_events(period, exclude_ids)
    people = _people(rows)
    payments = _load_payments(period, exclude_ids)
    ledger = _ledger(payments)
    matched = _mark_paid(people, ledger['paid'])
    steps, counts = _funnel(people)
    return {
        'rows': rows,
        'people': people,
        'payments': payments,
        'ledger': ledger,
        'matched_users': matched,
        'steps': steps,
        'counts': counts,
        'visitors': counts[1],
        'checkouts': counts[3],
        'conversion': _rate(counts[4], counts[1]),
        'checkout_rate': _rate(counts[3], counts[1]),
    }


# ── Presentation helpers ────────────────────────────────────────────────────

def _delta(current, previous, *, pct_points=False):
    """Change vs the previous period, or None when there's nothing to compare to."""
    if current is None or previous is None:
        return None
    current, previous = float(current), float(previous)
    if pct_points:
        diff = round(current - previous, 1)
        return {'value': diff, 'label': f'{diff:+.1f} pts', 'dir': _dir(diff)}
    if previous == 0:
        return None if current == 0 else {'value': None, 'label': 'new', 'dir': 'up'}
    diff = round((current - previous) / previous * 100)
    return {'value': diff, 'label': f'{diff:+d}%', 'dir': _dir(diff)}


def _dir(v):
    return 'up' if v > 0 else 'down' if v < 0 else 'flat'


def _money(value):
    return f'{int(round(value or 0)):,}'


def _buckets(period, first_seen):
    """Bucket size + edges for the trend: daily up to 31 days, weekly, then monthly."""
    end = timezone.localtime(period.end)
    start = timezone.localtime(period.start) if period.start else (
        timezone.localtime(first_seen) if first_seen else end - timedelta(days=30))
    span = (end.date() - start.date()).days + 1
    if span <= 31:
        unit, size = 'day', 1
    elif span <= 26 * 7:
        unit, size = 'week', 7
    else:
        unit, size = 'month', None
    edges = []
    if unit == 'month':
        d = start.date().replace(day=1)
        while d <= end.date():
            edges.append(d)
            d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        # Weeks count from the period's first day, so no bucket starts before it.
        d = start.date()
        while d <= end.date():
            edges.append(d)
            d += timedelta(days=size)
    return unit, edges


def _bucket_index(edges, day):
    lo, hi = 0, len(edges) - 1
    if day < edges[0]:
        return None
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if edges[mid] <= day:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _trend(period, core, tracking_since=None):
    first_seen = core['rows'][0][6] if core['rows'] else None
    if core['payments'] and (first_seen is None or core['payments'][0].date < first_seen):
        first_seen = core['payments'][0].date
    unit, edges = _buckets(period, first_seen)
    if not edges:
        return {'unit': unit, 'points': []}
    visitors = [set() for _ in edges]
    checkouts = [set() for _ in edges]
    subs = [0] * len(edges)
    revenue = [Decimal('0')] * len(edges)

    session_user = {}
    for sid, uid, *_ in core['rows']:
        if uid and sid not in session_user:
            session_user[sid] = uid
    for sid, uid, etype, page, action, plan_type, created, ua in core['rows']:
        i = _bucket_index(edges, timezone.localtime(created).date())
        if i is None:
            continue
        uid = uid or session_user.get(sid)
        key = f'u{uid}' if uid else (f's{sid}' if sid and sid != 'anon' else None)
        if not key:
            continue
        if page == 'payment' and etype == 'page_view':
            visitors[i].add(key)
        if page in CHECKOUT_PAGES:
            checkouts[i].add(key)
    for p in core['ledger']['paid']:
        i = _bucket_index(edges, timezone.localtime(p.date).date())
        if i is not None:
            subs[i] += 1
            revenue[i] += p.amount

    fmt = {'day': '%d %b', 'week': 'Wk of %d %b', 'month': '%b %Y'}[unit]
    # Buckets that ended before tracking existed have unknown traffic, not zero.
    since = timezone.localtime(tracking_since).date() if tracking_since else None
    nexts = edges[1:] + [None]
    points = [{
        'tracked': since is None or nexts[i] is None or nexts[i] > since,
        'label': e.strftime(fmt),
        'short': e.strftime('%d' if unit != 'month' else '%b'),
        'visitors': len(visitors[i]),
        'checkouts': len(checkouts[i]),
        'subscriptions': subs[i],
        'revenue': float(revenue[i]),
    } for i, e in enumerate(edges)]
    return {'unit': unit, 'points': points}


def _segments(core):
    """Conversion by sign-in state and device. Checkout needs an account, so guests stall."""
    def row(label, members):
        n = len(members)
        checkout = sum(1 for p in members if p['stage'] >= 3)
        paid = sum(1 for p in members if p['stage'] >= 4)
        return {'label': label, 'visitors': n, 'checkout_pct': _rate(checkout, n),
                'paid_pct': _rate(paid, n), 'paid': paid}

    people = list(core['people'].values())
    rows = [
        row('Signed in', [p for p in people if p['user_id']]),
        row('Guest (never signed in)', [p for p in people if not p['user_id']]),
    ]
    by_device = defaultdict(list)
    for p in people:
        by_device[p['device']].append(p)
    for name in ('Mobile', 'Desktop', 'Tablet', 'Unknown'):
        if by_device.get(name):
            rows.append(row(name, by_device[name]))
    return [r for r in rows if r['visitors']]


def _plan_mix(core):
    interest = Counter(p['plan'] for p in core['people'].values() if p['plan'] and p['stage'] >= 2)
    by_plan = core['ledger']['by_plan']
    total_interest = sum(interest.values())
    total_rev = sum((v[1] for v in by_plan.values()), Decimal('0'))
    total_subs = sum(v[0] for v in by_plan.values())
    rows = []
    for key in ('monthly', 'annual', 'other'):
        count, rev = by_plan.get(key, (0, Decimal('0')))
        if key == 'other' and not count:
            continue
        rows.append({
            'key': key, 'label': PLAN_LABELS[key],
            'interest': interest.get(key, 0),
            'interest_pct': _rate(interest.get(key, 0), total_interest),
            'subscriptions': count,
            'subs_pct': _rate(count, total_subs),
            'revenue': rev, 'revenue_label': _money(rev),
            'revenue_pct': _rate(rev, total_rev),
        })
    return rows


def _method_mix(core):
    by_method = core['ledger']['by_method']
    total = sum(v[0] for v in by_method.values())
    rows = []
    for key in ('card', 'wallet', 'coupon', 'school', 'admin'):
        count, rev = by_method.get(key, (0, Decimal('0')))
        if not count:
            continue
        rows.append({'key': key, 'label': METHOD_LABELS[key], 'count': count,
                     'pct': _rate(count, total), 'revenue': rev, 'revenue_label': _money(rev)})
    return rows


def _health(period, core, now):
    """Card checkouts that never completed and receipts waiting on a human."""
    card = [p for p in core['payments'] if payment_method(p) == 'card']
    card_paid = sum(1 for p in card if p.status == 'paid')
    card_failed = sum(1 for p in card if p.status == 'failed')
    card_abandoned = sum(1 for p in card if p.status == 'pending' and now - p.date > CARD_PENDING_GRACE)
    card_settled = card_paid + card_failed + card_abandoned

    receipts = _in_period(ManualPayment.objects.all(), 'created_at', period)
    receipt_counts = Counter(receipts.values_list('status', flat=True))
    wallet_split = Counter(receipts.filter(status='verified').values_list('payment_method', flat=True))
    return {
        'card_started': len(card),
        'card_paid': card_paid,
        'card_failed': card_failed,
        'card_abandoned': card_abandoned,
        'card_success_pct': _rate(card_paid, card_settled),
        'receipts_verified': receipt_counts.get('verified', 0),
        'receipts_rejected': receipt_counts.get('rejected', 0),
        'receipts_review_period': receipt_counts.get('needs_review', 0) + receipt_counts.get('pending', 0),
        # The review queue is a backlog, not a period stat: show all of it.
        'receipts_review_total': ManualPayment.objects.filter(
            status__in=('needs_review', 'pending'), created_at__gte=report_start()).count(),
        'instapay': wallet_split.get('instapay', 0),
        'vodafone': wallet_split.get('vodafone', 0),
    }


def _active_user_ids(user_ids):
    active = set()
    for p in (UserPayment.objects.filter(user_id__in=user_ids, status='paid')
              .select_related('subscription')):
        if p.is_active:
            active.add(p.user_id)
    return active


def _ago(dt, now):
    """'just now' / '3 hours ago' / '15 days ago': one unit, and days stay exact up to two
    months, so a follow-up list can tell 15 days from 18 (timesince would say "2 weeks")."""
    seconds = (now - dt).total_seconds()
    for limit, size, unit in ((3600, 60, 'minute'), (86400, 3600, 'hour'), (60 * 86400, 86400, 'day')):
        if seconds < limit:
            n = int(seconds // size)
            return 'just now' if n < 1 else f'{n} {unit}{"s" if n != 1 else ""} ago'
    months = int(seconds // (30 * 86400))
    return f'{months} months ago'


def _freshness(dt, now):
    """How warm a lead is, as (key, label). Shown with a text label, never colour alone."""
    age = now - dt
    if age < timedelta(days=1):
        return 'today', 'Active today'
    if age < timedelta(days=7):
        return 'week', 'This week'
    if age < timedelta(days=30):
        return 'month', 'This month'
    return 'cold', 'Gone quiet'


def lead_summary(leads):
    """Header numbers for the follow-up list: how many, how warm, and what they're worth."""
    return {
        'checkout': sum(1 for r in leads if r['stage'] == 3),
        'picked': sum(1 for r in leads if r['stage'] == 2),
        'warm': sum(1 for r in leads if r['freshness'][0] in ('today', 'week')),
        'value': _money(sum((r['plan_value'] or 0 for r in leads), Decimal('0'))),
        'emails': [r['email'] for r in leads if r['email']],
    }


def _leads(core):
    """Signed-in people who picked a plan or started checkout and haven't paid."""
    candidates = [p for p in core['people'].values()
                  if p['user_id'] and p['stage'] in (2, 3)]
    ids = {p['user_id'] for p in candidates}
    active = _active_user_ids(ids)
    users = {u.id: u for u in CustomUser.objects.filter(id__in=ids)}
    # Profile.last_seen is touched on every signed-in request, so it shows when
    # they were last on Skillifly at all, not just on the payment pages.
    site_seen = dict(Profile.objects.filter(user_id__in=ids).values_list('user_id', 'last_seen'))
    pending_card = set(UserPayment.objects.filter(user_id__in=ids, status='pending')
                       .exclude(fawaterk_intent_key__startswith='MANUAL-')
                       .exclude(fawaterk_intent_key__isnull=True)
                       .values_list('user_id', flat=True))
    from payments.views import PLAN_CATALOGUE  # lazy: payments.views imports core.views
    prices = {'monthly': Decimal(PLAN_CATALOGUE['monthly'][0]),
              'annual': Decimal(PLAN_CATALOGUE['pro_annual'][0])}
    now = timezone.now()
    leads = []
    for p in candidates:
        u = users.get(p['user_id'])
        if not u or p['user_id'] in active:
            continue
        last_seen = max(filter(None, (site_seen.get(u.id), u.last_login, p['last'])))
        name = u.get_full_name().strip() or u.username
        leads.append({
            'user_id': u.id,
            'name': name,
            'initials': ''.join(w[0] for w in name.split()[:2]).upper() or '?',
            'plan_value': prices.get(p['plan']),
            'freshness': _freshness(last_seen, now),
            'username': u.username,
            'email': u.email,
            'stage': p['stage'],
            'stage_label': STAGE_LABELS[p['stage']],
            'plan': PLAN_LABELS.get(p['plan'], ''),
            'plan_key': p['plan'],
            'pricing_opens': p['pricing_opens'],
            'last_seen': last_seen,
            'last_seen_ago': _ago(last_seen, now),
            'last_payment_visit': p['last'],
            'last_payment_visit_ago': _ago(p['last'], now),
            'card_pending': u.id in pending_card,
        })
    leads.sort(key=lambda r: (-r['stage'], -r['last_seen'].timestamp()))
    return leads, len(active)


def _renewal_visitors(core):
    ids = {p['user_id'] for p in core['people'].values() if p['user_id']}
    return len(_active_user_ids(ids)) if ids else 0


def worst_step(steps):
    """The step that loses the biggest share of its people (needs a few people to mean anything)."""
    leaky = [s for s in steps[:-1] if s['count'] >= 5 and s['lost_pct']]
    return max(leaky, key=lambda s: s['lost_pct']) if leaky else None


def _insights(core, plan_rows, health, leads, segments):
    """Plain-language takeaways, most important first. Each says what to do."""
    out = []
    visitors = core['visitors']

    worst = worst_step(core['steps'])
    if worst:
        hints = {
            'pricing': 'Test the pricing page itself: headline, price framing, trust signals.',
            'picked': 'Picking a plan asks for sign-in and email verification. Check that step for friction.',
            'checkout': 'People start paying but don\'t finish. Review the payment methods and the receipt upload.',
        }
        out.append({
            'tone': 'risk', 'title': f'Biggest drop: {worst["label"].lower()} → {worst["next_label"].lower()}',
            'body': f'{worst["lost_pct"]}% of the {worst["count"]} people who '
                    f'{worst["label"].lower()} went no further. {hints.get(worst["key"], "")}',
        })

    if leads:
        checkout_leads = sum(1 for lead in leads if lead['stage'] == 3)
        out.append({
            'tone': 'action', 'title': f'{len(leads)} signed-in {"person" if len(leads) == 1 else "people"} to follow up',
            'body': 'They have an account but no active plan'
                    + (f', and {checkout_leads} of them already started checkout' if checkout_leads else '')
                    + '. Send a personal email or a discount code. The list and a CSV export are below.',
            'anchor': '#leads',
        })

    if health['receipts_review_total']:
        n = health['receipts_review_total']
        out.append({
            'tone': 'action', 'title': f'{n} payment receipt{"s" if n != 1 else ""} waiting for review',
            'body': 'These customers sent money and are waiting on us. Review them in the admin.',
            'href': 'review',
        })

    if health['card_started'] >= 3 and health['card_success_pct'] is not None and health['card_success_pct'] < 60:
        out.append({
            'tone': 'risk', 'title': f'Only {_pct(health["card_success_pct"])} of card checkouts complete',
            'body': f'{health["card_abandoned"]} left pending and {health["card_failed"]} failed. '
                    'Check the Fawaterk page on mobile and the payment errors.',
        })

    guest = next((s for s in segments if s['label'].startswith('Guest')), None)
    if guest and visitors and guest['visitors'] / visitors >= 0.4 and guest['visitors'] >= 5:
        out.append({
            'tone': 'info', 'title': f'{round(guest["visitors"] / visitors * 100)}% of visitors are not signed in',
            'body': 'Checkout needs an account, so these visitors have to sign up first. '
                    'A shorter signup from pricing would help.',
        })

    rows = {r['key']: r for r in plan_rows}
    annual, monthly = rows.get('annual'), rows.get('monthly')
    if annual and monthly and annual['subs_pct'] is not None:
        enough_picks = (annual['interest'] + monthly['interest']) >= 5
        gap = (annual['interest_pct'] or 0) - (annual['subs_pct'] or 0)
        if enough_picks and gap >= 15:
            out.append({
                'tone': 'info', 'title': 'Annual gets clicks but not purchases',
                'body': f'Annual gets {_pct(annual["interest_pct"])} of plan picks but only '
                        f'{_pct(annual["subs_pct"])} of subscriptions. The price jump may stop people at checkout.',
            })
        elif (annual['revenue_pct'] or 0) >= 50 and annual['subscriptions'] + monthly['subscriptions'] >= 3:
            out.append({
                'tone': 'info', 'title': f'Annual brings in {_pct(annual["revenue_pct"])} of revenue',
                'body': 'Make annual the default choice on the pricing page.',
            })

    order = {'action': 0, 'risk': 1, 'info': 2}
    out.sort(key=lambda i: order[i['tone']])
    return out[:4]


def _actions(core):
    stats = defaultdict(lambda: {'clicks': 0, 'people': set()})
    session_user = {}
    for sid, uid, *_ in core['rows']:
        if uid and sid not in session_user:
            session_user[sid] = uid
    for sid, uid, etype, page, action, plan_type, created, ua in core['rows']:
        if etype != 'click':
            continue
        s = stats[(page, action)]
        s['clicks'] += 1
        uid = uid or session_user.get(sid)
        s['people'].add(f'u{uid}' if uid else f's{sid}')
    return sorted(
        ({'page': k[0], 'action': k[1], 'clicks': v['clicks'], 'people': len(v['people'])}
         for k, v in stats.items()),
        key=lambda r: (-r['people'], -r['clicks']),
    )


def build_report(period_param='30', include_team=False, now=None):
    now = now or timezone.now()
    period = resolve_period(period_param, now)
    exclude = set() if include_team else team_user_ids()

    core = _core(period, exclude)
    prev = _core(period.previous, exclude) if period.previous else None
    ledger = core['ledger']

    plan_rows = _plan_mix(core)
    method_rows = _method_mix(core)
    health = _health(period, core, now)
    leads, _ = _leads(core)
    segments = _segments(core)

    def d(key, *, src='core', pts=False):
        if not prev:
            return None
        if src == 'ledger':
            return _delta(ledger[key], prev['ledger'][key], pct_points=pts)
        return _delta(core[key], prev[key], pct_points=pts)

    paid_users = {p.user_id for p in ledger['paid'] if p.user_id}
    untracked = len(paid_users - core['matched_users'])
    first_event = (PaymentTrackingEvent.objects.filter(created_at__gte=report_start())
                   .order_by('created_at').values_list('created_at', flat=True).first())
    trend = _trend(period, core, first_event)

    kpis = [
        {'key': 'revenue', 'label': 'Revenue', 'value': _money(ledger['revenue']), 'unit': 'EGP',
         'sub': f'{ledger["priced_count"]} paid order{"s" if ledger["priced_count"] != 1 else ""}',
         'delta': d('revenue', src='ledger'), 'good_up': True},
        {'key': 'subs', 'label': 'New subscriptions', 'value': f'{ledger["subscriptions"]:,}', 'unit': '',
         'sub': f'{ledger["new_count"]} new · {ledger["renewal_count"]} renewal'
                + (f' · {ledger["free_count"]} free' if ledger['free_count'] else ''),
         'delta': d('subscriptions', src='ledger'), 'good_up': True},
        {'key': 'conversion', 'label': 'Visitor → subscriber',
         'value': f'{core["conversion"]}%' if core['conversion'] is not None else '—', 'unit': '',
         'sub': f'{core["counts"][4]} of {core["visitors"]} people who saw pricing',
         'delta': d('conversion', pts=True), 'good_up': True},
        {'key': 'aov', 'label': 'Average order', 'value': _money(ledger['aov']) if ledger['aov'] else '—',
         'unit': 'EGP' if ledger['aov'] else '', 'sub': 'Revenue ÷ paid orders',
         'delta': d('aov', src='ledger'), 'good_up': True},
        {'key': 'visitors', 'label': 'Pricing visitors', 'value': f'{core["visitors"]:,}', 'unit': '',
         'sub': f'{core["checkouts"]} started checkout',
         'delta': d('visitors'), 'good_up': True},
    ]

    recent_payments = [{
        'date': p.date,
        'name': (p.user.get_full_name().strip() or p.user.username) if p.user else 'Deleted user',
        'email': p.user.email if p.user else '',
        'plan': PLAN_LABELS[payment_plan(p)],
        'method': METHOD_LABELS[payment_method(p)],
        'amount': _money(p.amount),
        'is_free': p.amount <= 0,
    } for p in reversed(ledger['paid'][-12:])]

    return {
        'period': period,
        'include_team': include_team,
        'team_excluded': len(exclude),
        'kpis': kpis,
        'steps': core['steps'],
        'worst_step': (worst_step(core['steps']) or {}).get('key'),
        'funnel_top': core['visitors'],
        'small_sample': 0 < core['visitors'] < MIN_SAMPLE,
        'conversion': core['conversion'],
        'untracked_subs': untracked,
        'trend': trend,
        'plan_rows': plan_rows,
        'method_rows': method_rows,
        'health': health,
        'leads': leads,
        'lead_summary': lead_summary(leads),
        'segments': segments,
        'insights': _insights(core, plan_rows, health, leads, segments),
        'renewal_visitors': _renewal_visitors(core),
        'actions': _actions(core),
        'recent_payments': recent_payments,
        'revenue_total': ledger['revenue'],
        'tracking_since': first_event,
        # A waiting receipt is reason enough to show the page: someone paid.
        'has_data': bool(core['rows'] or core['payments'] or health['receipts_review_total']
                         or health['receipts_verified'] or health['receipts_rejected']),
        'core': core,
    }
