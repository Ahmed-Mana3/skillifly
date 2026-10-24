"""User activity & retention report behind /user-activity/ (superusers only).

It answers four questions, in this order:

1. Is the product being used?    - active users and how recently everyone was last seen.
2. Do new signups get value?     - setup milestones and retention by signup cohort.
3. Is revenue safe?              - paying customers going quiet, renewals due, recent expiries.
4. Who do we talk to today?      - contact lists plus a filterable, exportable user directory.

What "active" means: ``Profile.last_seen`` is stamped on every signed-in request, but only
the latest time is kept. So "active in the period" (last active on or after the period
start) is exact, while "how many were active in the previous period" can't be known, and
the report never shows a change for it. Last active is the latest of last_seen, last_login
and the signup itself. Retention is measured the same way: "came back after 7+ days" means
their last activity is at least 7 days after they signed up.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.launch import STEPS as LAUNCH_STEPS, XP
from core.models import AnalyticsVisit, CustomUser, Project, Skill, UserPayment
from core.payment_report import (
    PLAN_LABELS, _ago, _bucket_index, _buckets, _delta, _money, _rate, payment_plan, team_user_ids,
)

PERIODS = {'7': 7, '30': 30, '90': 90, 'all': None}
DEFAULT_PERIOD = '30'
AUDIENCES = {'editors': 'Editors', 'all': 'All accounts'}
DEFAULT_AUDIENCE = 'editors'

# Profile.last_seen started being recorded in May 2026. Before that only logins were,
# so very early accounts can look less active than they were.
ACTIVITY_TRACKING_SINCE = date(2026, 5, 10)

# The theme-preview demo account is not a customer.
MOCK_USERNAMES = ('alex_mercer',)

# How recently someone was last active. Every user is in exactly one bucket, ordered
# from most to least engaged. After 30 days we split by whether they ever came back:
# "left on day one" is an onboarding problem, "lapsed" is a retention problem.
RECENCY = [
    ('today', 'Active today', 'Last 24 hours'),
    ('week', 'Active this week', '1 to 7 days ago'),
    ('month', 'Active this month', '7 to 30 days ago'),
    ('lapsed', 'Lapsed', 'Used it, then stopped (30+ days)'),
    ('one_day', 'Left on day one', 'Never came back after signing up'),
]
RECENCY_LABELS = {key: label for key, label, _ in RECENCY}

PLAN_STATES = [
    ('paying', 'Paying', 'Active plan they paid for'),
    ('free_pass', 'Free pass', 'Active plan from a coupon, school or admin'),
    ('expired', 'Expired', 'Had a plan that ran out'),
    ('free', 'Never paid', 'No plan yet'),
]
PLAN_STATE_LABELS = {key: label for key, label, _ in PLAN_STATES}

STEP_LABELS = {
    'personal': 'Added name & title',
    'project': 'Added a first video',
    'theme': 'Picked a theme',
    'skills': 'Added skills',
}
MILESTONES = [
    ('signed_up', 'Signed up'),
    *[(key, STEP_LABELS[key]) for key in LAUNCH_STEPS],
    ('launched', 'Finished setup (100 XP)'),
    ('subscribed', 'Subscribed'),
    ('live', 'Portfolio live'),
]

SORTS = {
    'active': 'Last active',
    'joined': 'Newest signups',
    'visits': 'Most portfolio visits',
    'xp': 'Setup progress',
    'name': 'Name',
}
DEFAULT_SORT = 'active'
PAGE_SIZE = 50

QUIET_DAYS = 14        # a paying customer unseen this long is drifting away
RENEWAL_DAYS = 14      # plans ending this soon are worth a reminder
WINBACK_DAYS = 30      # plans that ran out this recently are still worth a message
UPGRADE_ACTIVE_DAYS = 7
MIN_SAMPLE = 5         # below this many people, a rate is an anecdote

CONTACT_LISTS = [
    {
        'key': 'renewals', 'label': 'Renewals due',
        'blurb': f'Their plan ends in the next {RENEWAL_DAYS} days. A friendly reminder now keeps the renewal.',
        'subject': 'Your Skillifly plan is ending soon',
        'empty': f'No plans end in the next {RENEWAL_DAYS} days.',
    },
    {
        'key': 'quiet', 'label': 'Paying, gone quiet',
        'blurb': f'Paying customers who have not opened Skillifly for {QUIET_DAYS}+ days. '
                 'They are the most likely not to renew.',
        'subject': 'How is your Skillifly portfolio working for you?',
        'empty': 'Every paying customer was active in the last two weeks.',
    },
    {
        'key': 'upgrade', 'label': 'Ready to upgrade',
        'blurb': f'Never paid, active in the last {UPGRADE_ACTIVE_DAYS} days and already added videos. '
                 'Their portfolio is built; it only needs a plan to go live.',
        'subject': 'Your Skillifly portfolio is ready to publish',
        'empty': 'No free users fit this right now.',
    },
    {
        'key': 'winback', 'label': 'Win back',
        'blurb': f'Their plan ran out in the last {WINBACK_DAYS} days and they have not renewed.',
        'subject': 'Your Skillifly portfolio is offline',
        'empty': f'No plans ran out in the last {WINBACK_DAYS} days without a renewal.',
    },
]
CONTACT_KEYS = [c['key'] for c in CONTACT_LISTS]


# ── Period ──────────────────────────────────────────────────────────────────

@dataclass
class Period:
    key: str
    days: int | None
    start: object  # aware datetime, or None for all time
    end: object
    label: str

    @property
    def previous(self):
        if not self.days:
            return None
        return Period(self.key, self.days, self.start - timedelta(days=self.days), self.start,
                      f'previous {self.days} days')


def resolve_period(param, now=None):
    now = now or timezone.now()
    key = param if param in PERIODS else DEFAULT_PERIOD
    days = PERIODS[key]
    if days is None:
        return Period(key, None, None, now, 'All time')
    return Period(key, days, now - timedelta(days=days), now, f'Last {days} days')


def _in_period(qs, field, period):
    if period.start is not None:
        qs = qs.filter(**{f'{field}__gte': period.start})
    return qs.filter(**{f'{field}__lt': period.end})


# ── Loading: one record per person ──────────────────────────────────────────

def _plan_prices():
    from payments.views import PLAN_CATALOGUE  # lazy: payments.views imports core.views
    return {'monthly': Decimal(PLAN_CATALOGUE['monthly'][0]),
            'annual': Decimal(PLAN_CATALOGUE['pro_annual'][0])}


def _paid_payments():
    by_user = defaultdict(list)
    for p in (UserPayment.objects.filter(status='paid', user__isnull=False)
              .select_related('subscription').order_by('date', 'id')):
        by_user[p.user_id].append(p)
    return by_user


def _covered_at(payments, at):
    """A paid plan covered this moment and the user had paid money by then."""
    covered = any(p.date <= at and p.expiration_date and at < p.expiration_date for p in payments)
    return covered and any(p.amount > 0 and p.date <= at for p in payments)


def _plan_info(payments, now, prices):
    ends = [(p.expiration_date, p) for p in payments if p.expiration_date]
    priced = [p for p in payments if p.amount > 0]
    info = {
        'plan_state': 'free', 'plan_end': None, 'plan_key': '', 'plan_label': '',
        'plan_value': None, 'spent': sum((p.amount for p in priced), Decimal('0')),
        'ever_paid': bool(priced), 'first_paid': priced[0].date if priced else None,
    }
    if not ends:
        return info
    end, current = max(ends, key=lambda e: e[0])
    plan_key = payment_plan(current)
    info.update({
        'plan_end': end,
        'plan_key': plan_key,
        'plan_label': PLAN_LABELS[plan_key],
        'plan_value': prices.get(plan_key),
    })
    if end > now:
        info['plan_state'] = 'paying' if priced else 'free_pass'
    else:
        info['plan_state'] = 'expired'
    return info


def _recency(last_active, returned, now):
    age = now - last_active
    if age < timedelta(days=1):
        return 'today'
    if age < timedelta(days=7):
        return 'week'
    if age < timedelta(days=30):
        return 'month'
    return 'lapsed' if returned else 'one_day'


def _initials(name):
    return ''.join(w[0] for w in name.split()[:2]).upper() or '?'


def load_people(audience, exclude_ids, period, now, prices=None):
    prices = prices or _plan_prices()
    qs = CustomUser.objects.exclude(username__in=MOCK_USERNAMES)
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)
    if audience == 'editors':
        # Legacy accounts have no UserAccount row; they are editors.
        qs = qs.filter(Q(user_account__isnull=True) | Q(user_account__account_type='editor'))
    rows = list(qs.values(
        'id', 'username', 'email', 'first_name', 'last_name', 'date_joined', 'last_login',
        'profile__last_seen', 'profile__is_public', 'profile__theme_id',
        'user_account__account_type', 'user_account__launch_status', 'user_account__launch_theme_picked',
        'personal_info__full_name', 'personal_info__title',
    ))

    videos = dict(Project.objects.order_by().values_list('user_id').annotate(n=Count('id')))
    skill_users = set(Skill.objects.order_by().values_list('user_id', flat=True).distinct())
    payments = _paid_payments()
    human = AnalyticsVisit.objects.exclude(user_agent__icontains='bot')
    period_visits = dict(_in_period(human, 'created_at', period).order_by()
                         .values_list('user_id').annotate(n=Count('id')))
    last_visit = dict(human.order_by().values_list('user_id').annotate(m=Max('created_at')))

    people = []
    for r in rows:
        uid = r['id']
        joined = r['date_joined']
        last_active = max(filter(None, (r['profile__last_seen'], r['last_login'], joined)))
        returned = last_active - joined >= timedelta(days=1)
        portfolio_name = (r['personal_info__full_name'] or '').strip()
        name = portfolio_name or f"{r['first_name']} {r['last_name']}".strip() or r['username']
        steps = {
            'personal': bool(portfolio_name and (r['personal_info__title'] or '').strip()),
            'project': videos.get(uid, 0) > 0,
            # Accounts from before the checklist chose their theme themselves.
            'theme': bool(r['user_account__launch_theme_picked']
                          or (not r['user_account__launch_status'] and r['profile__theme_id'])),
            'skills': uid in skill_users,
        }
        plan = _plan_info(payments.get(uid, ()), now, prices)
        public = bool(r['profile__is_public'])
        people.append({
            'id': uid,
            'username': r['username'],
            'email': r['email'],
            'name': name,
            'initials': _initials(name),
            'account_type': r['user_account__account_type'] or 'editor',
            'joined': joined,
            'last_active': last_active,
            'last_active_ago': _ago(last_active, now),
            'never_signed_in_again': not returned,
            'returned': returned,
            'recency': _recency(last_active, returned, now),
            'steps': steps,
            'xp': sum(XP[k] for k, done in steps.items() if done),
            'videos': videos.get(uid, 0),
            'public': public,
            'live': public and plan['plan_state'] in ('paying', 'free_pass'),
            'visits': period_visits.get(uid, 0),
            'last_visit': last_visit.get(uid),
            'payments': payments.get(uid, ()),
            **plan,
        })
    for p in people:
        p['recency_label'] = RECENCY_LABELS[p['recency']]
        p['plan_state_label'] = PLAN_STATE_LABELS[p['plan_state']]
        p['days_quiet'] = (now - p['last_active']).days
        p['plan_days_left'] = (p['plan_end'] - now).days if p['plan_end'] and p['plan_end'] > now else None
    return people


# ── Signups: setup milestones and cohorts ───────────────────────────────────

def _milestones_done(p):
    done = {'signed_up': True, **p['steps']}
    done['launched'] = all(p['steps'].values())
    done['subscribed'] = p['ever_paid']
    done['live'] = p['live']
    return done


def cohort_stats(people, start, end, now):
    members = [p for p in people if (start is None or p['joined'] >= start) and p['joined'] < end]
    n = len(members)
    counts = {key: 0 for key, _ in MILESTONES}
    for p in members:
        for key, done in _milestones_done(p).items():
            counts[key] += done
    eligible = [p for p in members if now - p['joined'] >= timedelta(days=1)]
    returned = sum(1 for p in eligible if p['returned'])
    return {
        'members': members,
        'signups': n,
        'counts': counts,
        'activation': _rate(counts['project'], n),
        'returned': returned,
        'return_eligible': len(eligible),
        'return_rate': _rate(returned, len(eligible)),
    }


def _milestone_rows(stats):
    n = stats['signups']
    rows = [{
        'key': key, 'label': label, 'count': stats['counts'][key],
        'pct': _rate(stats['counts'][key], n),
        'is_step': key in LAUNCH_STEPS,
    } for key, label in MILESTONES]
    steps = [r for r in rows if r['is_step'] and r['pct'] is not None]
    weakest = min(steps, key=lambda r: r['pct']) if steps and n >= MIN_SAMPLE else None
    for r in rows:
        r['is_weakest'] = weakest is not None and r['key'] == weakest['key']
    return rows, weakest


def _heat(pct):
    """0-4 step on one sequential ramp; the cell always prints its number too."""
    if pct is None:
        return None
    if pct >= 60:
        return 4
    if pct >= 40:
        return 3
    if pct >= 20:
        return 2
    return 1 if pct > 0 else 0


def _cohort_cell(members, now, after_days, test):
    eligible = [p for p in members if now - p['joined'] >= timedelta(days=after_days)] if after_days else members
    hits = sum(1 for p in eligible if test(p))
    pct = _rate(hits, len(eligible))
    return {'pct': pct, 'hits': hits, 'n': len(eligible), 'heat': _heat(pct),
            'partial': 0 < len(eligible) < len(members)}


def cohort_table(people, period, now):
    """Signup cohorts, newest first: weekly (Mondays), or monthly for all time."""
    today = timezone.localtime(now).date()
    starts = []
    if period.key == 'all':
        first = min((timezone.localtime(p['joined']).date() for p in people), default=today)
        d = today.replace(day=1)
        while d >= first.replace(day=1) and len(starts) < 12:
            starts.append(d)
            d = (d - timedelta(days=1)).replace(day=1)
        unit = 'month'
    else:
        weeks = 13 if period.key == '90' else 8
        monday = today - timedelta(days=today.weekday())
        starts = [monday - timedelta(weeks=i) for i in range(weeks)]
        unit = 'week'

    tz = timezone.get_current_timezone()
    rows = []
    for i, d in enumerate(starts):
        if unit == 'month':
            nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
            label = d.strftime('%b %Y')
        else:
            nxt = d + timedelta(days=7)
            label = f"{d.day} {d:%b}"
        lo = timezone.make_aware(datetime.combine(d, time.min), tz)
        hi = timezone.make_aware(datetime.combine(nxt, time.min), tz)
        members = [p for p in people if lo <= p['joined'] < hi]
        rows.append({
            'label': label,
            'current': i == 0,
            'signups': len(members),
            'small': 0 < len(members) < MIN_SAMPLE,
            'activated': _cohort_cell(members, now, 0, lambda p: p['steps']['project']),
            'returned': _cohort_cell(members, now, 1, lambda p: p['returned']),
            'week1': _cohort_cell(members, now, 7, lambda p: p['last_active'] - p['joined'] >= timedelta(days=7)),
            'month1': _cohort_cell(members, now, 30, lambda p: p['last_active'] - p['joined'] >= timedelta(days=30)),
            'paid': _cohort_cell(members, now, 0, lambda p: p['ever_paid']),
        })
    while rows and not rows[-1]['signups']:
        rows.pop()  # drop empty weeks before the first signup
    return {'unit': unit, 'rows': rows, 'min_sample': MIN_SAMPLE,
            'has_small': any(r['small'] for r in rows)}


# ── Trend ───────────────────────────────────────────────────────────────────

def trend(people, period, now):
    first = min((p['joined'] for p in people), default=None)
    unit, edges = _buckets(period, first)
    if not edges:
        return {'unit': unit, 'points': []}
    signups = [0] * len(edges)
    activated = [0] * len(edges)
    visits = [0] * len(edges)
    window_start = period.start
    for p in people:
        if (window_start and p['joined'] < window_start) or p['joined'] >= period.end:
            continue
        i = _bucket_index(edges, timezone.localtime(p['joined']).date())
        if i is not None:
            signups[i] += 1
            activated[i] += p['steps']['project']
    ids = {p['id'] for p in people}
    human = AnalyticsVisit.objects.exclude(user_agent__icontains='bot')
    daily = (_in_period(human, 'created_at', period).order_by()
             .annotate(day=TruncDate('created_at')).values_list('day', 'user_id')
             .annotate(n=Count('id')))
    for day, uid, n in daily:
        if uid not in ids:
            continue
        i = _bucket_index(edges, day)
        if i is not None:
            visits[i] += n
    fmt = {'day': '%d %b', 'week': 'Wk of %d %b', 'month': '%b %Y'}[unit]
    return {'unit': unit, 'points': [{
        'label': e.strftime(fmt), 'signups': signups[i], 'activated': activated[i], 'visits': visits[i],
    } for i, e in enumerate(edges)]}


# ── Engagement mix (recency x plan) ─────────────────────────────────────────

def engagement_matrix(people):
    total = len(people)
    grid = {(r, s): 0 for r, _, _ in RECENCY for s, _, _ in PLAN_STATES}
    for p in people:
        grid[(p['recency'], p['plan_state'])] += 1
    rows = []
    for key, label, hint in RECENCY:
        count = sum(grid[(key, s)] for s, _, _ in PLAN_STATES)
        rows.append({
            'key': key, 'label': label, 'hint': hint, 'count': count,
            'pct': _rate(count, total),
            'cells': [{'state': s, 'count': grid[(key, s)]} for s, _, _ in PLAN_STATES],
        })
    totals = [{'state': s, 'count': sum(grid[(r, s)] for r, _, _ in RECENCY)} for s, _, _ in PLAN_STATES]
    return {'rows': rows, 'totals': totals, 'total': total}


# ── Who to contact ──────────────────────────────────────────────────────────

def contact_lists(people, now, prices):
    renew_cut = now + timedelta(days=RENEWAL_DAYS)
    quiet_cut = now - timedelta(days=QUIET_DAYS)
    upgrade_cut = now - timedelta(days=UPGRADE_ACTIVE_DAYS)
    winback_cut = now - timedelta(days=WINBACK_DAYS)

    def entry(p, reason, value):
        return {**p, 'reason': reason, 'value': value}

    def days(n):
        return f'{n} day{"s" if n != 1 else ""}'

    lists = {
        'renewals': [entry(p, 'Ends today' if p['plan_days_left'] == 0 else f'Ends in {days(p["plan_days_left"])}',
                           p['plan_value'])
                     for p in sorted((p for p in people if p['plan_state'] == 'paying' and p['plan_end'] <= renew_cut),
                                     key=lambda p: p['plan_end'])],
        'quiet': [entry(p, f'Not seen for {days(p["days_quiet"])}', p['plan_value'])
                  for p in sorted((p for p in people if p['plan_state'] == 'paying' and p['last_active'] < quiet_cut),
                                  key=lambda p: p['last_active'])],
        'upgrade': [entry(p, f'{p["xp"]} XP · {p["videos"]} video{"s" if p["videos"] != 1 else ""}', prices['monthly'])
                    for p in sorted((p for p in people if p['plan_state'] == 'free' and p['videos']
                                     and p['last_active'] >= upgrade_cut),
                                    key=lambda p: (-p['xp'], -p['videos'], -p['last_active'].timestamp()))],
        'winback': [entry(p, f'Ran out {_ago(p["plan_end"], now)}', p['plan_value'])
                    for p in sorted((p for p in people if p['plan_state'] == 'expired' and p['plan_end'] >= winback_cut),
                                    key=lambda p: p['plan_end'], reverse=True)],
    }
    out = []
    for meta in CONTACT_LISTS:
        rows = lists[meta['key']]
        out.append({
            **meta,
            'rows': rows,
            'count': len(rows),
            'value': _money(sum((r['value'] or 0 for r in rows), Decimal('0'))),
            'emails': [r['email'] for r in rows if r['email']],
        })
    return out


# ── Insights ────────────────────────────────────────────────────────────────

def _plural(n, one, many=None):
    return one if n == 1 else (many or one + 's')


def insights(people, lists, cohort, weakest, traction):
    out = []
    by_key = {c['key']: c for c in lists}

    quiet = by_key['quiet']
    paying = sum(1 for p in people if p['plan_state'] == 'paying')
    if quiet['count']:
        share = round(quiet['count'] / paying * 100) if paying else 0
        out.append({
            'tone': 'risk',
            'title': f'{quiet["count"]} paying {_plural(quiet["count"], "customer")} '
                     f'({share}%) went quiet',
            'body': f'Not seen for {QUIET_DAYS}+ days, so they get little from their plan and may not renew. '
                    'A short personal check-in works better than a discount.',
            'anchor': '#contact-quiet',
        })

    renewals = by_key['renewals']
    if renewals['count']:
        out.append({
            'tone': 'action',
            'title': f'{renewals["count"]} {_plural(renewals["count"], "renewal")} due in {RENEWAL_DAYS} days',
            'body': f'Worth {renewals["value"]} EGP. Send a reminder before the portfolio goes offline.',
            'anchor': '#contact-renewals',
        })

    upgrade = by_key['upgrade']
    if upgrade['count']:
        out.append({
            'tone': 'action',
            'title': f'{upgrade["count"]} free {_plural(upgrade["count"], "user")} ready to upgrade',
            'body': 'Active this week with videos already added. Their portfolio is built and only needs '
                    'a plan to go live.',
            'anchor': '#contact-upgrade',
        })

    winback = by_key['winback']
    if winback['count']:
        out.append({
            'tone': 'risk',
            'title': f'{winback["count"]} {_plural(winback["count"], "plan")} ran out without a renewal',
            'body': f'In the last {WINBACK_DAYS} days. Their portfolio is offline now. Ask what stopped them.',
            'anchor': '#contact-winback',
        })

    n = cohort['signups']
    if n >= MIN_SAMPLE and weakest is not None and weakest['pct'] is not None and weakest['pct'] < 60:
        hints = {
            'personal': 'Ask for the name and title in the first screen after signup.',
            'project': 'Adding a first video is the core value. Make the paste-a-link step impossible to miss.',
            'theme': 'Show theme previews earlier, or pick a strong default and let them confirm it.',
            'skills': 'Offer one-tap suggested skills for video editors.',
        }
        out.append({
            'tone': 'risk',
            'title': f'Only {weakest["pct"]:g}% of new signups {weakest["label"].lower()}',
            'body': f'The weakest setup step for the {n} people who signed up in this period. '
                    + hints.get(weakest['key'], ''),
            'anchor': '#setup',
        })

    eligible = cohort['return_eligible']
    if eligible >= MIN_SAMPLE and cohort['return_rate'] is not None and cohort['return_rate'] < 50:
        gone = eligible - cohort['returned']
        out.append({
            'tone': 'risk',
            'title': f'{100 - round(cohort["return_rate"])}% of new signups never came back',
            'body': f'{gone} of {eligible} people used Skillifly on their signup day only. '
                    'A follow-up email the next day, with a link back to their half-built portfolio, is the usual fix.',
            'anchor': '#cohorts',
        })

    idle = traction['live_no_visits']
    if traction['live'] >= MIN_SAMPLE and idle and idle / traction['live'] >= .3:
        out.append({
            'tone': 'info',
            'title': f'{idle} live {_plural(idle, "portfolio")} got no visitors',
            'body': 'They are online but nobody saw them in this period, which makes a plan hard to justify. '
                    'Nudge them to put the link in their Instagram bio and client emails.',
            'anchor': '#traction',
        })

    order = {'action': 0, 'risk': 1, 'info': 2}
    out.sort(key=lambda i: order[i['tone']])
    return out[:6]


# ── Portfolio traction ──────────────────────────────────────────────────────

def traction(people, period, prev_period):
    live = [p for p in people if p['live']]
    total = sum(p['visits'] for p in people)
    prev_total = None
    if prev_period is not None:
        ids = {p['id'] for p in people}
        per_user = (_in_period(AnalyticsVisit.objects.exclude(user_agent__icontains='bot'),
                               'created_at', prev_period).order_by()
                    .values_list('user_id').annotate(n=Count('id')))
        prev_total = sum(n for uid, n in per_user if uid in ids)
    top = sorted((p for p in people if p['visits']), key=lambda p: (-p['visits'], p['name']))[:8]
    peak = top[0]['visits'] if top else 0
    for p in top:
        p['visits_pct'] = round(p['visits'] / peak * 100) if peak else 0
    return {
        'live': len(live),
        'live_with_visits': sum(1 for p in live if p['visits']),
        'live_no_visits': sum(1 for p in live if not p['visits']),
        'visits': total,
        'visits_delta': _delta(total, prev_total) if prev_total is not None else None,
        'median_live': median([p['visits'] for p in live]) if live else None,
        'top': top,
    }


# ── Directory ───────────────────────────────────────────────────────────────

def filter_people(people, status='', plan='', q='', sort=DEFAULT_SORT):
    rows = people
    if status in RECENCY_LABELS:
        rows = [p for p in rows if p['recency'] == status]
    if plan in PLAN_STATE_LABELS:
        rows = [p for p in rows if p['plan_state'] == plan]
    q = (q or '').strip().lower().lstrip('@')
    if q:
        rows = [p for p in rows if q in p['name'].lower() or q in p['username'].lower()
                or q in (p['email'] or '').lower()]
    keys = {
        'active': lambda p: -p['last_active'].timestamp(),
        'joined': lambda p: -p['joined'].timestamp(),
        'visits': lambda p: (-p['visits'], -p['last_active'].timestamp()),
        'xp': lambda p: (-p['xp'], -p['last_active'].timestamp()),
        'name': lambda p: p['name'].lower(),
    }
    return sorted(rows, key=keys.get(sort, keys[DEFAULT_SORT]))


# ── Report ──────────────────────────────────────────────────────────────────

def build_report(period_param=DEFAULT_PERIOD, audience=DEFAULT_AUDIENCE, include_team=False, now=None):
    now = now or timezone.now()
    period = resolve_period(period_param, now)
    audience = audience if audience in AUDIENCES else DEFAULT_AUDIENCE
    exclude = set() if include_team else team_user_ids()
    prices = _plan_prices()

    people = load_people(audience, exclude, period, now, prices)
    total = len(people)

    cohort = cohort_stats(people, period.start, period.end, now)
    prev = period.previous
    prev_cohort = cohort_stats(people, prev.start, prev.end, now) if prev else None
    milestones, weakest = _milestone_rows(cohort)

    # "Active" needs a window; all time would count everyone, so it falls back to 30 days.
    active_start = period.start or now - timedelta(days=30)
    active_label = 'Active users' if period.start else 'Active, last 30 days'
    active = sum(1 for p in people if p['last_active'] >= active_start)
    today = sum(1 for p in people if p['recency'] == 'today')
    week = sum(1 for p in people if p['last_active'] >= now - timedelta(days=7))

    paying = sum(1 for p in people if p['plan_state'] == 'paying')
    paying_delta = None
    if period.start:
        then = sum(1 for p in people if p['payments'] and _covered_at(p['payments'], period.start))
        paying_delta = _delta(paying, then)

    lists = contact_lists(people, now, prices)
    by_key = {c['key']: c for c in lists}
    traction_data = traction(people, period, prev)

    def d(key, pts=False):
        if not prev_cohort:
            return None
        return _delta(cohort[key], prev_cohort[key], pct_points=pts)

    compare = f'the {prev.label}' if prev else None
    kpis = [
        {'key': 'active', 'label': active_label, 'value': f'{active:,}', 'unit': '',
         'sub': f'{_rate(active, total) or 0:g}% of {total:,} · {today} today · {week} this week',
         'delta': None,
         'help': 'People who opened Skillifly while signed in. Only the latest visit is stored, so '
                 'there is no comparison with the previous period.'},
        {'key': 'signups', 'label': 'New signups', 'value': f'{cohort["signups"]:,}', 'unit': '',
         'sub': f'{cohort["counts"]["launched"]} finished setup',
         'delta': d('signups'), 'delta_note': compare},
        {'key': 'activation', 'label': 'Added a video',
         'value': f'{cohort["activation"]:g}%' if cohort['activation'] is not None else '—', 'unit': '',
         'sub': f'{cohort["counts"]["project"]} of {cohort["signups"]} new signups',
         'delta': d('activation', pts=True), 'delta_note': compare,
         'help': 'Share of the period\'s signups who added at least one video: the moment a portfolio '
                 'becomes worth sharing.'},
        {'key': 'returned', 'label': 'Came back',
         'value': f'{cohort["return_rate"]:g}%' if cohort['return_rate'] is not None else '—', 'unit': '',
         'sub': f'{cohort["returned"]} of {cohort["return_eligible"]} signups used it again after day one',
         'delta': d('return_rate', pts=True), 'delta_note': compare,
         'help': 'Signups older than a day who were active again a day or more after signing up. '
                 'Older signups have had longer to come back.'},
        {'key': 'paying', 'label': 'Paying customers', 'value': f'{paying:,}', 'unit': '',
         'sub': f'{by_key["renewals"]["count"]} renew within {RENEWAL_DAYS} days · '
                f'{by_key["quiet"]["count"]} gone quiet',
         'delta': paying_delta,
         'delta_note': (f'the start of the period ({timezone.localtime(period.start).day} '
                        f'{timezone.localtime(period.start):%b})' if period.start else None),
         'help': 'Customers with a running plan they paid for. Coupon and school plans are not counted.'},
    ]

    return {
        'now': now,
        'period': period,
        'audience': audience,
        'audience_label': AUDIENCES[audience],
        'include_team': include_team,
        'team_excluded': len(exclude),
        'people': people,
        'total_people': total,
        'kpis': kpis,
        'compare_label': prev.label if prev else None,
        'cohort': cohort,
        'milestones': milestones,
        'weakest': weakest,
        'small_sample': 0 < cohort['signups'] < MIN_SAMPLE,
        'engagement': engagement_matrix(people),
        'cohorts': cohort_table(people, period, now),
        'trend': trend(people, period, now),
        'contact_lists': lists,
        'traction': traction_data,
        'insights': insights(people, lists, cohort, weakest, traction_data),
        'activity_since': ACTIVITY_TRACKING_SINCE,
        'has_data': bool(people),
    }
