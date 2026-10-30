"""Executive overview behind /admin-dashboard-exclusive/ (superusers only).

The page an owner opens first. Each other manage report goes deep on one question (Revenue
insights: money; User activity: usage and who to contact; Payment tracking: checkout). This one
puts the whole business on one screen, in this order, and links into them for the detail:

1. Are we growing?                  - signups, and what became of each one.
2. Does growth turn into money?     - signup -> first video -> setup -> paid, revenue, MRR.
3. Where do the good signups come from? - how they heard about us, signup method and language,
                                       each with how many went on to build and to pay.
4. Is the base healthy?             - how recently editors were active, plan mix, live portfolios.
5. What needs a decision?           - the most urgent items across reports, each with a link.

Every number reuses the deeper reports' code (revenue_report for money, activity_report for
people), so this page and those pages never disagree. Same rules as them: nothing before
REPORT_START_DATE, team accounts left out unless asked, editors only (clients and school admins
don't build portfolios), and the theme-preview demo account never counts.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from allauth.socialaccount.models import SocialAccount
from django.utils import timezone

from core import activity_report as ar
from core import revenue_report as rr
from core.models import HeardAboutResponse, PersonalInfo, Profile, UserAccount
from core.payment_report import _bucket_index, _buckets, _delta, _money, _rate, report_start, team_user_ids

DEFAULT_PERIOD = '30'
PERIOD_LABELS = rr.PERIOD_LABELS
MIN_SAMPLE = 5          # fewer people than this in a group and its rate is an anecdote
SCORECARD_WEEKS = 8
RECENT_LIMIT = 25
ZERO = Decimal('0')

# survey.LABELS are the Arabic answers shown to users; the report is in English.
SOURCE_LABELS = {
    'instagram': 'Instagram', 'tiktok': 'TikTok', 'youtube': 'YouTube', 'facebook': 'Facebook',
    'friend': 'A friend or colleague', 'google': 'Google search', 'other': 'Somewhere else',
}
LANG_LABELS = {'ar': 'Arabic', 'en': 'English'}

# What became of a signup, best outcome first. Every signup is in exactly one.
OUTCOMES = [
    ('paid', 'Paid'),
    ('built', 'Added a video, not paid'),
    ('new', 'No video yet'),
]
FUNNEL = [
    ('signed_up', 'Signed up'),
    ('project', 'Added a first video'),
    ('launched', 'Finished setup'),
    ('subscribed', 'Paid'),
]


def _outcome(p):
    if p['ever_paid']:
        return 'paid'
    return 'built' if p['videos'] else 'new'


def _plural(n, one, many=None):
    return f'{n:,} {one if n == 1 else (many or one + "s")}'


def _pct(value):
    return f'{value:g}%'


def _when(period):
    if period.key == 'all':
        return 'since launch'
    if period.key == 'custom':
        return f'between {period.label.replace(" – ", " and ")}'
    return f'in the {period.label[0].lower()}{period.label[1:]}'


def _aware(day):
    return timezone.make_aware(datetime.combine(day, time.min))


# ── Signups and what became of them ─────────────────────────────────────────

def _signup_trend(period, members):
    unit, edges = _buckets(period, None)
    if not edges:
        return {'unit': unit, 'points': []}
    counts = [{key: 0 for key, _ in OUTCOMES} for _ in edges]
    for p in members:
        i = _bucket_index(edges, timezone.localtime(p['joined']).date())
        if i is not None:
            counts[i][_outcome(p)] += 1
    fmt = {'day': '%a %d %b', 'week': 'Wk of %d %b', 'month': '%B %Y'}[unit]
    return {'unit': unit, 'points': [{
        'label': e.strftime(fmt),
        'short': e.strftime('%b') if unit == 'month' else f'{e.day} {e:%b}',
        'signups': sum(c.values()), **c,
    } for e, c in zip(edges, counts)]}


def _funnel(cohort):
    n = cohort['signups']
    rows = [{'key': key, 'label': label, 'count': cohort['counts'][key], 'pct': _rate(cohort['counts'][key], n)}
            for key, label in FUNNEL]
    rows.append({'key': 'live', 'label': 'Portfolio live now', 'count': cohort['counts']['live'],
                 'pct': _rate(cohort['counts']['live'], n), 'after': True})
    return rows


def _outcome_totals(members):
    n = len(members)
    counts = defaultdict(int)
    for p in members:
        counts[_outcome(p)] += 1
    return [{'key': key, 'label': label, 'count': counts[key], 'pct': _rate(counts[key], n)} for key, label in OUTCOMES]


# ── Where signups come from ─────────────────────────────────────────────────

def _segment_row(label, group, total, key='', muted=False):
    n = len(group)
    built = sum(1 for p in group if p['videos'])
    paid = sum(1 for p in group if p['ever_paid'])
    return {
        'key': key, 'label': label, 'signups': n, 'share': _rate(n, total),
        'built': built, 'built_pct': _rate(built, n), 'paid': paid, 'paid_pct': _rate(paid, n),
        'small': n < MIN_SAMPLE, 'muted': muted,
    }


def segments(members):
    """Signups split three ways, each with how many built a portfolio and how many paid."""
    ids = [p['id'] for p in members]
    total = len(members)
    heard = dict(HeardAboutResponse.objects.filter(user_id__in=ids).values_list('user_id', 'source'))
    google = set(SocialAccount.objects.filter(user_id__in=ids, provider='google').values_list('user_id', flat=True))
    lang = dict(UserAccount.objects.filter(user_id__in=ids).values_list('user_id', 'signup_lang'))

    by_source = defaultdict(list)
    for p in members:
        by_source[heard.get(p['id'], '')].append(p)
    sources = sorted((_segment_row(SOURCE_LABELS.get(k, k.title()), g, total, k)
                      for k, g in by_source.items() if k), key=lambda r: (-r['signups'], r['label']))
    if by_source.get(''):
        sources.append(_segment_row('Did not answer', by_source[''], total, 'none', muted=True))

    methods = [
        _segment_row('Google', [p for p in members if p['id'] in google], total, 'google'),
        _segment_row('Email and password', [p for p in members if p['id'] not in google], total, 'email'),
    ]
    langs = [_segment_row(label, [p for p in members if lang.get(p['id']) == code], total, code)
             for code, label in LANG_LABELS.items()]
    unknown = [p for p in members if lang.get(p['id']) not in LANG_LABELS]
    if unknown:
        langs.append(_segment_row('Not recorded', unknown, total, 'unknown', muted=True))

    answered = total - len(by_source.get('', []))
    return {
        'groups': [
            {'key': 'source', 'label': 'How they heard about us', 'rows': sources},
            {'key': 'method', 'label': 'Signed up with', 'rows': [r for r in methods if r['signups']]},
            {'key': 'lang', 'label': 'Signup language', 'rows': [r for r in langs if r['signups']]},
        ],
        'answered': answered,
        'answered_pct': _rate(answered, total),
        'sources': [r for r in sources if r['key'] != 'none'],
    }


# ── Week by week ────────────────────────────────────────────────────────────

def scorecard(people, recs, now):
    """The last SCORECARD_WEEKS weeks (Monday to Sunday), newest first, whatever the period filter."""
    today = timezone.localtime(now).date()
    monday = today - timedelta(days=today.weekday())
    floor = report_start()
    first_paid = {}
    for r in recs:
        if r['priced']:
            first_paid.setdefault(r['cust'], r['at'])

    rows = []
    for i in range(SCORECARD_WEEKS):
        day = monday - timedelta(weeks=i)
        lo, hi = _aware(day), _aware(day + timedelta(days=7))
        if hi <= floor:
            break
        lo = max(lo, floor)
        members = [p for p in people if lo <= p['joined'] < hi]
        built = sum(1 for p in members if p['videos'])
        revenue = sum((r['amount'] for r in recs if r['priced'] and lo <= r['at'] < hi), ZERO)
        mrr = rr.mrr_by_customer(recs, min(hi, now))
        rows.append({
            'label': f'{day.day} {day:%b}', 'current': i == 0,
            'signups': len(members), 'built': built, 'built_pct': _rate(built, len(members)),
            'new_paying': sum(1 for at in first_paid.values() if lo <= at < hi),
            'revenue': revenue, 'revenue_label': _money(revenue),
            'mrr': sum(mrr.values(), ZERO), 'mrr_label': _money(sum(mrr.values(), ZERO)), 'paying': len(mrr),
        })
    top_signups = max((r['signups'] for r in rows), default=0) or 1
    top_revenue = max((r['revenue'] for r in rows), default=ZERO) or 1
    for r in rows:
        r['signups_w'] = round(r['signups'] / top_signups * 100)
        r['revenue_w'] = round(float(r['revenue'] / top_revenue * 100))
    return rows


# ── The user base today ─────────────────────────────────────────────────────

def base_health(people, now, period, prev):
    eng = ar.engagement_matrix(people)
    total = eng['total']
    week_ago = now - timedelta(days=7)
    traction = ar.traction(people, period, prev)
    return {
        'total': total,
        'recency': [{'key': r['key'], 'label': r['label'], 'hint': r['hint'], 'count': r['count'], 'pct': r['pct']}
                    for r in eng['rows']],
        'plans': [{'key': t['state'], 'label': ar.PLAN_STATE_LABELS[t['state']], 'count': t['count'],
                   'pct': _rate(t['count'], total)} for t in eng['totals']],
        'week': sum(1 for p in people if p['last_active'] >= week_ago),
        'today': sum(1 for p in people if p['recency'] == 'today'),
        'live': traction['live'],
        'live_no_visits': traction['live_no_visits'],
        'visits': traction['visits'],
        'visits_delta': traction['visits_delta'],
        'median_live': traction['median_live'],
    }


# ── Newest signups ──────────────────────────────────────────────────────────

def phones(user_ids):
    """The number they gave us: account profile first, then the portfolio contact details."""
    profile = dict(Profile.objects.filter(user_id__in=user_ids).exclude(phone_number='')
                   .values_list('user_id', 'phone_number'))
    info = dict(PersonalInfo.objects.filter(user_id__in=user_ids).exclude(phone='').values_list('user_id', 'phone'))
    return {uid: profile.get(uid) or info.get(uid) or '' for uid in user_ids}


def signup_rows(members, limit=None):
    rows = sorted(members, key=lambda p: p['joined'], reverse=True)
    if limit:
        rows = rows[:limit]
    ids = [p['id'] for p in rows]
    numbers = phones(ids)
    heard = dict(HeardAboutResponse.objects.filter(user_id__in=ids).values_list('user_id', 'source'))
    google = set(SocialAccount.objects.filter(user_id__in=ids, provider='google').values_list('user_id', flat=True))
    return [{
        **p,
        'phone': numbers.get(p['id'], ''),
        'source': SOURCE_LABELS.get(heard.get(p['id']), ''),
        'method': 'Google' if p['id'] in google else 'Email',
        'outcome': _outcome(p),
        'spent_label': _money(p['spent']),
    } for p in rows]


# ── Narrative ───────────────────────────────────────────────────────────────

def _summary(period, cohort, signups_delta, money, base):
    """Four plain sentences: growth, what became of it, money, and the base."""
    n = cohort['signups']
    s1 = f'{_plural(n, "editor")} signed up {_when(period)}'
    if signups_delta and signups_delta['value'] is not None:
        v = signups_delta['value']
        s1 += (f', {"up" if v > 0 else "down"} {abs(v)}% on the {period.previous.label}' if v
               else f', the same as the {period.previous.label}')
    out = [s1 + '.']
    if n:
        c = cohort['counts']
        out.append(f'{_pct(cohort["activation"])} of them added a first video and {c["subscribed"]:,} '
                   f'({_pct(_rate(c["subscribed"], n))}) have paid so far.')
    line = f'Revenue was EGP {money["revenue_label"]}'
    d = money['rev_delta']
    if d and d['value'] is not None and d['value']:
        line += f' ({"up" if d["value"] > 0 else "down"} {abs(d["value"])}%)'
    mv = money['movement']
    if mv['customers_end']:
        line += (f'; recurring revenue is EGP {_money(mv["end"])} a month from '
                 f'{_plural(mv["customers_end"], "paying customer")}.')
    else:
        line += '; nobody has a paid plan running right now.'
    out.append(line)
    if base['total']:
        out.append(f'{base["week"]:,} of {_plural(base["total"], "editor")} used Skillifly in the last 7 days, '
                   f'and {_plural(base["live"], "portfolio is", "portfolios are")} live.')
    return out


def _insights(ctx):
    """The decisions on the table, most urgent first. Each points at the page with the detail."""
    out = []
    # Money items come from Revenue insights as they are, so both pages say the same thing.
    for item in ctx['money_insights']:
        if item['tone'] in ('action', 'risk'):
            out.append({**item, 'from': 'revenue'})

    lists = {c['key']: c for c in ctx['lists']}
    upgrade = lists['upgrade']
    if upgrade['count']:
        out.append({'tone': 'action', 'from': 'activity', 'link': 'activity_contact', 'link_label': 'See who',
                    'title': f'{_plural(upgrade["count"], "free editor")} {"is" if upgrade["count"] == 1 else "are"} '
                             'ready to upgrade',
                    'body': 'Active this week with videos already added: the portfolio is built and only needs a plan '
                            f'to go live. That is EGP {upgrade["value"]} a month at the monthly price.'})
    quiet = lists['quiet']
    if quiet['count']:
        out.append({'tone': 'risk', 'from': 'activity', 'link': 'activity_contact', 'link_label': 'See who',
                    'title': f'{_plural(quiet["count"], "paying customer")} went quiet',
                    'body': f'Not seen for {ar.QUIET_DAYS}+ days, so they get little from their plan and may not '
                            'renew. A short personal check-in works better than a discount.'})

    d, cohort, prev = ctx['signups_delta'], ctx['cohort'], ctx['prev_cohort']
    if d and d['value'] is not None and abs(d['value']) >= 20 and prev and cohort['signups'] + prev['signups'] >= 10:
        top = ctx['segments']['sources'][0] if ctx['segments']['sources'] else None
        if d['value'] < 0:
            out.append({'tone': 'risk', 'link': 'heard', 'link_label': 'Acquisition answers',
                        'title': f'Signups are down {abs(d["value"])}% on the {ctx["previous_label"]}',
                        'body': f'{cohort["signups"]:,} against {prev["signups"]:,}. Check what stopped: posting, a '
                                'creator partnership, ads. Every later number follows this one.'})
        else:
            body = f'{cohort["signups"]:,} against {prev["signups"]:,}.'
            if top and not top['small']:
                body += f' {top["label"]} is the biggest source this period.'
            out.append({'tone': 'info', 'link': 'heard', 'link_label': 'Acquisition answers',
                        'title': f'Signups are up {d["value"]}% on the {ctx["previous_label"]}',
                        'body': body + ' Find what changed and do more of it.'})

    weakest = ctx['weakest']
    if cohort['signups'] >= MIN_SAMPLE and weakest and weakest['pct'] is not None and weakest['pct'] < 60:
        out.append({'tone': 'risk', 'from': 'activity', 'link': 'activity_setup', 'link_label': 'Setup steps',
                    'title': f'Only {_pct(weakest["pct"])} of new signups {weakest["label"].lower()}',
                    'body': 'The weakest step of the launch checklist this period. People who stall in setup rarely '
                            'pay, so this is the cheapest place to win customers.'})

    if cohort['return_eligible'] >= MIN_SAMPLE and cohort['return_rate'] is not None and cohort['return_rate'] < 50:
        gone = cohort['return_eligible'] - cohort['returned']
        out.append({'tone': 'risk', 'from': 'activity', 'link': 'activity_cohorts', 'link_label': 'Retention',
                    'title': f'{100 - round(cohort["return_rate"])}% of new signups never came back',
                    'body': f'{gone:,} of {cohort["return_eligible"]:,} used Skillifly on their signup day only. A '
                            'next-day email linking back to their half-built portfolio is the usual fix.'})

    seg = ctx['segments']
    overall = _rate(cohort['counts']['subscribed'], cohort['signups'])
    ranked = [r for r in seg['sources'] if not r['small'] and r['paid_pct'] is not None]
    if ranked and overall is not None:
        best = max(ranked, key=lambda r: r['paid_pct'])
        if best['paid'] >= 2 and best['paid_pct'] >= overall + 10:
            out.append({'tone': 'info', 'link': 'heard', 'link_label': 'Acquisition answers',
                        'title': f'{best["label"]} brings the editors who pay',
                        'body': f'{_pct(best["paid_pct"])} of signups who found us there have paid, against '
                                f'{_pct(overall)} overall. Put more of the marketing effort there.'})
    if cohort['signups'] >= 10 and (seg['answered_pct'] or 0) < 30:
        out.append({'tone': 'info', 'link': 'heard', 'link_label': 'Acquisition answers',
                    'title': 'Most signups never say how they found us',
                    'body': f'Only {_pct(seg["answered_pct"] or 0)} answered the question, so the acquisition numbers '
                            'below are a hint, not a measurement. Ask for it during setup.'})

    order = {'action': 0, 'risk': 1, 'info': 2}
    out.sort(key=lambda i: order[i['tone']])
    return out[:6]


# ── Assembly ────────────────────────────────────────────────────────────────

def build_report(period_param=DEFAULT_PERIOD, start=None, end=None, include_team=False, now=None):
    now = now or timezone.now()
    period = rr.resolve_period(period_param, start, end, now)
    prev = period.previous
    exclude = set() if include_team else team_user_ids()
    prices = rr.plan_prices()

    money = rr.build_report(period_param, start=start, end=end, include_team=include_team, now=now)
    recs = rr._load(exclude, prices)
    people = ar.load_people('editors', exclude, period, now, prices)

    cohort = ar.cohort_stats(people, period.start, period.end, now)
    prev_cohort = ar.cohort_stats(people, prev.start, prev.end, now) if prev else None
    members = cohort['members']
    _, weakest = ar._milestone_rows(cohort)
    lists = ar.contact_lists(people, now, prices)
    base = base_health(people, now, period, prev)
    seg = segments(members)

    paid_rate = _rate(cohort['counts']['subscribed'], cohort['signups'])
    prev_paid_rate = _rate(prev_cohort['counts']['subscribed'], prev_cohort['signups']) if prev_cohort else None
    signups_delta = _delta(cohort['signups'], prev_cohort['signups']) if prev_cohort else None
    vs = prev.label if prev else None

    def pts(cur, before):
        return _delta(cur, before, pct_points=True) if cur is not None and before is not None else None

    days = max(1, (min(period.end, now) - period.start).days)
    growth_kpis = [
        {'key': 'signups', 'label': 'New signups', 'value': f'{cohort["signups"]:,}', 'unit': '',
         'sub': f'{cohort["signups"] / days:.1f} a day · {cohort["counts"]["launched"]:,} finished setup',
         'delta': signups_delta, 'vs': vs, 'spark': 'signups'},
        {'key': 'activation', 'label': 'Added a first video',
         'value': _pct(cohort['activation']) if cohort['activation'] is not None else '—', 'unit': '',
         'sub': f'{cohort["counts"]["project"]:,} of {cohort["signups"]:,} new signups',
         'delta': pts(cohort['activation'], prev_cohort['activation'] if prev_cohort else None), 'vs': vs},
        {'key': 'conversion', 'label': 'Signups who paid',
         'value': _pct(paid_rate) if paid_rate is not None else '—', 'unit': '',
         'sub': f'{cohort["counts"]["subscribed"]:,} of {cohort["signups"]:,} have paid so far',
         'delta': pts(paid_rate, prev_paid_rate), 'vs': vs},
        {'key': 'active', 'label': 'Active in the last 7 days', 'value': f'{base["week"]:,}', 'unit': '',
         'sub': f'{_pct(_rate(base["week"], base["total"]) or 0)} of {base["total"]:,} editors · {base["today"]:,} today',
         'delta': None},
    ]
    money_kpis = []
    sparks = {'revenue': 'revenue', 'mrr': 'mrr', 'paying': 'customers'}
    for k in money['kpis']:
        if k['key'] in ('revenue', 'mrr', 'paying', 'renewal'):
            money_kpis.append({**k, 'spark': sparks.get(k['key'])})

    ctx = {
        'money_insights': money['insights'], 'lists': lists, 'signups_delta': signups_delta,
        'cohort': cohort, 'prev_cohort': prev_cohort, 'weakest': weakest, 'segments': seg,
        'previous_label': vs or '',
    }
    return {
        'period': period,
        'now': now,
        'include_team': include_team,
        'team_excluded': len(exclude),
        'has_data': bool(people) or money['has_data'],
        'small_sample': 0 < cohort['signups'] < MIN_SAMPLE,
        'summary': _summary(period, cohort, signups_delta, money, base),
        'growth_kpis': growth_kpis,
        'money_kpis': money_kpis,
        'insights': _insights(ctx),
        'signups': cohort['signups'],
        'signups_delta': signups_delta,
        'prev_signups': prev_cohort['signups'] if prev_cohort else None,
        'trend': _signup_trend(period, members),
        'outcomes': _outcome_totals(members),
        'funnel': _funnel(cohort),
        'days_to_pay': money['customers']['days_to_pay'],
        'return_rate': cohort['return_rate'],
        'segments': seg,
        'base': base,
        'scorecard': scorecard(people, recs, now),
        'recent': signup_rows(members, RECENT_LIMIT),
        'members': members,
        'money_trend': money['trend'],
        'revenue_label': money['revenue_label'],
        'receipts': money['receipts'],
        'upcoming30': money['upcoming']['next30'],
        'min_sample': MIN_SAMPLE,
    }
