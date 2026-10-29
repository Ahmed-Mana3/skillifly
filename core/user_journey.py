"""One user's whole story, behind /manage/users/ and /manage/users/<id>/ (superusers only).

Built to support a decision about one person, not to browse logs. The profile page answers,
in this order:

1. Who is this and what should we do?   - segment, health score, the next best actions.
2. How far did they get, how fast?      - journey milestones with the time from signup.
3. How engaged are they?                - 13-week activity calendar and actions by area.
4. What exactly did they do?            - every recorded action, newest first, filterable.

Sources (everything that stores a user and a time):
  account    signup, latest sign-in, email verification, Google, survey answer, affiliate,
             coupons, reviews written, school membership
  portfolio  activation events (builder, launch checklist, themes), videos, uploads,
             categories, custom domain
  payments   pricing-page opens and clicks (PaymentTrackingEvent, including clicks made on the
             same browser before signing in), card / wallet / coupon payments, receipts
  ai         AI assistant chats and the changes it made
  emails     onboarding nudges sent and clicked
  traction   visits their public portfolio got (bots excluded), client reviews received

Known gaps, also listed on the page: only the latest sign-in and the latest "seen" time are
stored; skills, experience, education and links carry no timestamps; activation events only
exist from the onboarding v2 rollout on.

Recency, plan state and setup XP use the /user-activity/ definitions (core.activity_report),
so a person reads the same on both pages.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from urllib.parse import quote, urlsplit

from django.db.models import Count, F, Q
from django.utils import timezone

from core import activity_report as ar
from core.launch import STEPS as LAUNCH_STEPS, XP
from core.models import (
    ActivationEvent, AffiliateProfile, AgentConversation, AgentMessage, AnalyticsEvent, AnalyticsVisit,
    ClientReview, CustomDomain, CustomUser, DiscountCode, HeardAboutResponse, ManualPayment, NudgeLog,
    PaymentTrackingEvent, PersonalInfo, Profile, Project, ProjectCategory, Review, SchoolStudent,
    SchoolVideoRating, Skill, UserAccount, UserPayment, Video,
)
from core.payment_report import METHOD_LABELS, PLAN_LABELS, _ago, _money, payment_method, payment_plan

CATEGORIES = [
    ('account', 'Account'),
    ('portfolio', 'Portfolio'),
    ('payments', 'Payments'),
    ('ai', 'AI assistant'),
    ('emails', 'Emails we sent'),
    ('traction', 'Portfolio visitors'),
]
CATEGORY_LABELS = dict(CATEGORIES)
# What the user did themselves. Emails we sent and visits strangers made are context, not activity.
USER_DRIVEN = frozenset({'account', 'portfolio', 'payments', 'ai'})

TIMELINE_LIMIT = 300
CALENDAR_WEEKS = 13
SEARCH_LIMIT = 50
ABANDONED_DAYS = 30    # an unfinished checkout older than this is no longer a hot lead
STALLED_DAYS = 3       # no video this long after signup = stuck, not just new

HEARD_LABELS = {
    'instagram': 'Instagram', 'tiktok': 'TikTok', 'youtube': 'YouTube', 'facebook': 'Facebook',
    'friend': 'a friend', 'google': 'Google search', 'other': 'somewhere else',
}
NUDGE_LABELS = {
    'no_project_1h': 'No video yet (1 hour after signup)',
    'no_project_24h': 'No video yet (day 1)',
    'no_project_72h': 'No video yet (day 3)',
    'no_project_7d': 'No video yet (day 7)',
    'few_projects_48h': 'Add more videos (day 2)',
    'ready_unpaid_3d': 'Portfolio is ready, publish it (day 3)',
}
KIND_LABELS = {
    'personal': 'their name & title', 'skills': 'a skill', 'education': 'education',
    'experience': 'work experience', 'projects': 'a video', 'links': 'a link',
    'creators': 'a creator they follow', 'project_categories': 'a category', 'categories': 'a category',
}
REVEAL_LABELS = {'add': 'Add videos', 'looks': 'Change the look', 'edit': 'Edit', 'live': 'Go live'}
PAGE_LABELS = {
    'payment': 'the pricing page', 'manual_payment': 'the wallet payment page',
    'fawaterk_checkout': 'card checkout', 'payment_success': 'the payment-success page',
    'payment_failure': 'the payment-failed page', 'fawaterk_pending': 'the payment-pending page',
}
CHECKOUT_CLICKS = frozenset({'card_checkout', 'verify_payment'})


# ── Small helpers ───────────────────────────────────────────────────────────

def _plural(n, one, many=None):
    return f'{n:,} {one if n == 1 else (many or one + "s")}'


def _span(delta):
    """'under a minute' / '12 minutes' / '3 hours' / '2 days': one unit, rounded down."""
    s = max(0, int(delta.total_seconds()))
    if s < 60:
        return 'under a minute'
    if s < 3600:
        return _plural(s // 60, 'minute')
    if s < 86400:
        return _plural(s // 3600, 'hour')
    return _plural(s // 86400, 'day')


def _day(dt):
    return timezone.localtime(dt).date()


def _short(text, n=140):
    text = ' '.join((text or '').split())
    return text if len(text) <= n else text[:n - 1].rstrip() + '…'


def _date(dt):
    local = timezone.localtime(dt)
    return f'{local.day} {local:%b %Y}'


def _ev(at, cat, title, detail='', tone='', minor=False):
    """One timeline row. tone: '' | good | bad | warn. Minor rows are routine (page opens, autosaves)."""
    return {'at': at, 'cat': cat, 'title': title, 'detail': detail, 'tone': tone, 'minor': minor}


def _mailto(email, subject):
    return f'mailto:{email}?subject={quote(subject)}' if email else ''


def _display_name(user, info):
    name = (getattr(info, 'full_name', '') or '').strip()
    return name or user.get_full_name().strip() or user.username


# ── Events, one source at a time ────────────────────────────────────────────

def _activation_row(e):
    """Timeline row for one ActivationEvent, or None when another source tells it better."""
    p = e.props or {}
    n, at = e.name, e.created_at
    if n in ('signup_completed', 'project_created', 'nudge_sent'):
        return None  # signup row, Project rows and NudgeLog rows carry more detail
    if n == 'email_verified':
        return _ev(at, 'account', 'Verified their email', tone='good')
    if n == 'dashboard_viewed':
        return _ev(at, 'account', 'Opened the dashboard', minor=True)
    if n == 'welcome_viewed':
        return _ev(at, 'portfolio', 'Opened the welcome screen', minor=True)
    if n == 'welcome_skipped':
        return _ev(at, 'portfolio', 'Skipped the welcome screen', tone='warn')
    if n == 'welcome_submitted':
        return _ev(at, 'portfolio', 'Finished the welcome screen',
                   _plural(int(p.get('links') or 0), 'video link') + ' added')
    if n == 'link_previewed':
        ok = p.get('ok', True)
        provider = (p.get('provider') or '').title()
        return _ev(at, 'portfolio', 'Pasted a video link',
                   provider if ok else f'{provider} · preview failed{": " + str(p["error"]) if p.get("error") else ""}',
                   tone='' if ok else 'bad', minor=ok)
    if n == 'reveal_viewed':
        return _ev(at, 'portfolio', 'Saw their portfolio preview', _plural(int(p.get('projects') or 0), 'video'))
    if n == 'reveal_action':
        label = REVEAL_LABELS.get(p.get('action'), p.get('action') or '')
        return _ev(at, 'portfolio', f'Clicked “{label}” on the preview bar')
    if n == 'theme_switched':
        return _ev(at, 'portfolio', f'Switched theme to {p.get("to") or "a new theme"}',
                   f'from {p["from"]}' if p.get('from') else '')
    if n == 'builder_saved':
        return _ev(at, 'portfolio', 'Saved the portfolio builder',
                   _plural(int(p.get('projects') or 0), 'video') + ' on the portfolio', minor=True)
    if n == 'builder_save_failed':
        sections = ', '.join(p.get('sections') or []) if isinstance(p.get('sections'), list) else ''
        return _ev(at, 'portfolio', 'A builder save failed',
                   f'Invalid: {sections}' if sections else 'The form had errors', tone='bad')
    if n == 'profile_field_added':
        field = (p.get('field') or 'details').replace('_', ' ')
        return _ev(at, 'portfolio', f'Added their {field}', 'Written by AI' if p.get('source') == 'ai' else '')
    if n == 'builder_item_saved':
        noun = KIND_LABELS.get(p.get('kind'), (p.get('kind') or 'an item').replace('_', ' '))
        if p.get('created'):
            return _ev(at, 'portfolio', f'Added {noun}')
        return _ev(at, 'portfolio', f'Edited {noun}', minor=True)
    if n == 'builder_item_save_failed':
        noun = KIND_LABELS.get(p.get('kind'), (p.get('kind') or 'an item').replace('_', ' '))
        return _ev(at, 'portfolio', f'Could not save {noun}', str(p.get('reason') or ''), tone='bad')
    if n == 'builder_item_deleted':
        noun = KIND_LABELS.get(p.get('kind'), (p.get('kind') or 'an item').replace('_', ' '))
        return _ev(at, 'portfolio', f'Deleted {noun}')
    if n == 'nudge_clicked':
        return _ev(at, 'emails', 'Clicked a nudge email', NUDGE_LABELS.get(p.get('key'), p.get('key') or ''),
                   tone='good')
    if n == 'launch_viewed':
        return _ev(at, 'portfolio', 'Opened the launch checklist', f'{p.get("xp", 0)} XP so far', minor=True)
    if n == 'launch_step_completed':
        step = ar.STEP_LABELS.get(p.get('step'), p.get('step') or 'a step')
        return _ev(at, 'portfolio', f'Setup step done: {step}', f'+{p.get("xp", 0)} XP', tone='good')
    if n == 'launch_skipped':
        return _ev(at, 'portfolio', 'Skipped the launch checklist',
                   f'{p.get("done", 0)} of {len(LAUNCH_STEPS)} steps done', tone='warn')
    if n == 'launch_finished':
        return _ev(at, 'portfolio', 'Finished setup (100 XP)', tone='good')
    return _ev(at, 'portfolio', n.replace('_', ' ').capitalize(), minor=True)


def _signup_row(user, signup_props, account, socials):
    google = signup_props.get('method') == 'google' or any(
        s.provider == 'google' and abs(s.date_joined - user.date_joined) < timedelta(minutes=5) for s in socials)
    bits = ['with Google' if google else 'with email']
    lang = signup_props.get('lang') or (account.signup_lang if account else '')
    if lang:
        bits.append('Arabic site' if lang == 'ar' else 'English site')
    if account and account.account_type != 'editor':
        bits.append(f'as {account.get_account_type_display().lower()}')
    if signup_props.get('source'):
        bits.append(f'from {signup_props["source"]}'
                    + (f' ({signup_props["campaign"]})' if signup_props.get('campaign') else ''))
    return _ev(user.date_joined, 'account', 'Signed up', ' · '.join(bits), tone='good'), google


def _account_rows(user, account, signup_props, socials):
    rows = []
    signup, google = _signup_row(user, signup_props, account, socials)
    rows.append(signup)
    for s in socials:
        if abs(s.date_joined - user.date_joined) >= timedelta(minutes=5):
            rows.append(_ev(s.date_joined, 'account', f'Connected {s.provider.title()} sign-in'))
    if user.last_login and user.last_login - user.date_joined > timedelta(minutes=1):
        rows.append(_ev(user.last_login, 'account', 'Signed in',
                        'Latest sign-in. Earlier sign-ins are not stored'))

    heard = HeardAboutResponse.objects.filter(user=user).first()
    if heard:
        where = HEARD_LABELS.get(heard.source, heard.source)
        rows.append(_ev(heard.created_at, 'account', f'Said they found Skillifly through {where}',
                        heard.detail or ''))
    aff = AffiliateProfile.objects.filter(user=user).first()
    if aff:
        rows.append(_ev(aff.created_at, 'account', 'Joined the affiliate program',
                        f'{_money(aff.total_earned)} EGP earned so far'))
    for c in DiscountCode.objects.filter(owner=user):
        rows.append(_ev(c.created_at, 'account', f'Got their own coupon code {c.code}',
                        f'{c.discount_percentage}% off · used {_plural(c.usage_count, "time")}'))
    for r in Review.objects.filter(reviewer=user):
        rows.append(_ev(r.created_at, 'account', f'Reviewed Skillifly ({r.rating}/5)', _short(r.content),
                        tone='good' if r.rating >= 4 else 'bad' if r.rating <= 2 else ''))
    for r in ClientReview.objects.filter(reviewer=user).select_related('user'):
        rows.append(_ev(r.created_at, 'account', f'Reviewed editor @{r.user.username} ({r.rating}/5)',
                        _short(r.content)))
    for s in SchoolStudent.objects.filter(user=user).select_related('school'):
        rows.append(_ev(s.created_at, 'account', f'Joined {s.school.name} as a student'))
    for r in SchoolVideoRating.objects.filter(user=user).select_related('project'):
        rows.append(_ev(r.created_at, 'account', f'Rated a school video', getattr(r.project, 'title', ''),
                        minor=True))
    return rows, google


def _portfolio_rows(user, project_events):
    rows = []
    info = PersonalInfo.objects.filter(user=user).first()
    if info and info.created_at:
        rows.append(_ev(info.created_at, 'portfolio', 'Added their name & title',
                        ' · '.join(filter(None, (info.full_name, info.title)))))

    project_times = []
    for p in Project.objects.filter(user=user).select_related('category').order_by():
        if not p.created_at:
            continue
        project_times.append(p.created_at)
        bits = ['Reel' if p.video_type == 'reel' else 'Long video']
        if p.category_id:
            bits.append(p.category.name)
        rows.append(_ev(p.created_at, 'portfolio', f'Added a video: “{_short(p.title, 70)}”', ' · '.join(bits)))
    # A project_created event with no Project saved within a few seconds = a video they later deleted.
    for e in project_events:
        if not any(abs(e.created_at - t) < timedelta(seconds=10) for t in project_times):
            rows.append(_ev(e.created_at, 'portfolio', 'Added a video (since deleted)',
                            (e.props or {}).get('provider', '').title()))

    for v in Video.objects.filter(user=user):
        size = f'{v.size_bytes / 1_048_576:,.0f} MB' if v.size_bytes else ''
        status = v.get_status_display()
        rows.append(_ev(v.created_at, 'portfolio', 'Uploaded a video file',
                        ' · '.join(filter(None, (_short(v.title, 60), size, status))),
                        tone='bad' if v.status == 'error' else ''))
    for c in ProjectCategory.objects.filter(user=user):
        rows.append(_ev(c.created_at, 'portfolio', f'Created the category “{_short(c.name, 60)}”'))
    domain = CustomDomain.objects.filter(user=user).first()
    if domain and domain.domain:
        rows.append(_ev(domain.created_at, 'portfolio', f'Connected a custom domain: {domain.domain}'))
        if domain.dns_verified_at:
            rows.append(_ev(domain.dns_verified_at, 'portfolio', f'Custom domain verified: {domain.domain}',
                            tone='good'))
    return rows, info


def _payment_rows(user, now):
    rows = []
    # Pricing-page activity, including what this browser did before signing in.
    sessions = set(PaymentTrackingEvent.objects.filter(user=user).exclude(session_id='')
                   .values_list('session_id', flat=True))
    tracking = list(PaymentTrackingEvent.objects
                    .filter(Q(user=user) | Q(user__isnull=True, session_id__in=sessions))
                    .order_by('created_at'))
    from payments.views import PAYMENT_ACTION_LABELS  # lazy: payments.views imports core.views
    for t in tracking:
        before = '' if t.user_id else 'Before signing in'
        plan = PLAN_LABELS.get('annual' if t.plan_type == 'pro_annual' else 'monthly' if t.plan_type else '', '')
        detail = ' · '.join(filter(None, (plan and f'{plan} plan', before)))
        if t.event_type == 'page_view':
            rows.append(_ev(t.created_at, 'payments', f'Opened {PAGE_LABELS.get(t.page, t.page)}', detail,
                            tone='bad' if t.page == 'payment_failure' else ''))
        else:
            label = PAYMENT_ACTION_LABELS.get(t.action, t.action.replace('_', ' '))
            rows.append(_ev(t.created_at, 'payments', f'Clicked “{label}”', detail,
                            tone='warn' if t.action in CHECKOUT_CLICKS else ''))

    payments = list(UserPayment.objects.filter(user=user).select_related('subscription').order_by('date', 'id'))
    paid_priced = 0
    for p in payments:
        plan = PLAN_LABELS[payment_plan(p)]
        method = METHOD_LABELS.get(payment_method(p), payment_method(p))
        coupon = f'coupon {p.discount_code_used}' if p.discount_code_used else ''
        if p.status == 'paid' and p.amount > 0:
            paid_priced += 1
            title = f'Paid {_money(p.amount)} EGP for the {plan.lower()} plan'
            kind = 'Repeat payment' if paid_priced > 1 else 'First payment'
            rows.append(_ev(p.date, 'payments', title, ' · '.join(filter(None, (kind, method, coupon))), tone='good'))
        elif p.status == 'paid':
            rows.append(_ev(p.date, 'payments', f'Got a free {plan.lower()} plan',
                            ' · '.join(filter(None, (method, coupon))), tone='good'))
        elif p.status == 'pending' and p.amount > 0 and payment_method(p) == 'card':
            rows.append(_ev(p.date, 'payments', f'Started a card checkout ({_money(p.amount)} EGP)',
                            f'{plan} plan · not completed', tone='warn'))
        elif p.status == 'pending':
            rows.append(_ev(p.date, 'payments', f'Payment record left pending ({_money(p.amount)} EGP)',
                            f'{plan} plan · {method}', tone='warn'))
        else:
            rows.append(_ev(p.date, 'payments', f'Payment {p.status} ({_money(p.amount)} EGP)', f'{plan} plan',
                            tone='bad'))
    ends = [p.expiration_date for p in payments if p.status == 'paid' and p.expiration_date]
    if ends and max(ends) <= now:
        rows.append(_ev(max(ends), 'payments', 'Plan ran out, portfolio went offline', tone='bad'))

    receipts = list(ManualPayment.objects.filter(user=user).order_by('created_at'))
    for m in receipts:
        tone = {'verified': 'good', 'rejected': 'bad', 'needs_review': 'warn'}.get(m.status, '')
        detail = m.get_status_display()
        if m.status == 'rejected' and m.rejection_reason:
            detail += f': {_short(m.rejection_reason, 100)}'
        rows.append(_ev(m.created_at, 'payments',
                        f'Sent a {m.get_payment_method_display()} receipt ({_money(m.amount_expected)} EGP)',
                        detail, tone=tone))
    return rows, tracking, payments, receipts


def _ai_rows(user):
    rows = []
    convs = list(AgentConversation.objects.filter(user=user).annotate(n=Count('messages')))
    for c in convs:
        rows.append(_ev(c.created_at, 'ai', 'Started a chat with the AI assistant',
                        f'{_short(c.title, 60)} · {_plural(c.n, "message")}'))
    messages = list(AgentMessage.objects.filter(conversation__user=user).order_by('-created_at')[:500])
    ratings = Counter()
    for m in messages:
        if m.sender == 'user':
            rows.append(_ev(m.created_at, 'ai', 'Asked the AI assistant', f'“{_short(m.text)}”'))
        elif m.sender == 'agent' and m.actions_applied:
            n = len(m.actions_applied) if isinstance(m.actions_applied, list) else 1
            rows.append(_ev(m.created_at, 'ai', f'AI assistant changed their portfolio',
                            _plural(n, 'change') + ' applied', tone='good'))
        if m.user_rating:
            ratings[m.user_rating] += 1
            rows.append(_ev(m.created_at, 'ai',
                            'Rated an AI reply helpful' if m.user_rating == 'up' else 'Rated an AI reply unhelpful',
                            f'“{_short(m.text, 100)}”', tone='good' if m.user_rating == 'up' else 'bad'))
    return rows, len(convs), ratings


def _email_rows(user):
    return [_ev(n.sent_at, 'emails', 'We sent a nudge email', NUDGE_LABELS.get(n.key, n.key))
            for n in NudgeLog.objects.filter(user=user)]


def _human_visits(user):
    return AnalyticsVisit.objects.filter(user=user).exclude(user_agent__icontains='bot')


def _traction_rows(user):
    rows = []
    by_day = defaultdict(list)
    for v in _human_visits(user).only('created_at', 'country'):
        by_day[_day(v.created_at)].append(v)
    clicks = Counter(_day(at) for at in AnalyticsEvent.objects.filter(visit__user=user)
                     .exclude(visit__user_agent__icontains='bot').values_list('created_at', flat=True))
    for day, visits in by_day.items():
        countries = Counter(v.country for v in visits if v.country and v.country != 'Unknown')
        bits = [', '.join(f'{c} {n}' for c, n in countries.most_common(3))]
        if clicks.get(day):
            bits.append(_plural(clicks[day], 'video click'))
        rows.append(_ev(max(v.created_at for v in visits), 'traction',
                        f'Portfolio got {_plural(len(visits), "visit")}', ' · '.join(filter(None, bits))))
    for r in ClientReview.objects.filter(user=user):
        rows.append(_ev(r.created_at, 'traction', f'Got a client review ({r.rating}/5) from {r.user_name}',
                        _short(r.content), tone='good' if r.rating >= 4 else ''))
    return rows


# ── Timeline shaping ────────────────────────────────────────────────────────

def _collapse(events):
    """Fold back-to-back repeats on the same day into one row ("Opened the dashboard ×4")."""
    out = []
    for e in events:  # newest first
        prev = out[-1] if out else None
        if (prev and prev['day'] == e['day'] and prev['cat'] == e['cat']
                and prev['title'] == e['title'] and prev['detail'] == e['detail']):
            prev['count'] += 1
            prev['first_at'] = e['at']
            continue
        out.append({**e, 'count': 1, 'first_at': e['at']})
    return out


def _day_label(day, today):
    if day == today:
        return 'Today'
    if day == today - timedelta(days=1):
        return 'Yesterday'
    return f'{day:%a} {day.day} {day:%b %Y}'


def group_by_day(rows, now):
    today = _day(now)
    groups = []
    for r in rows:
        if not groups or groups[-1]['day'] != r['day']:
            groups.append({'day': r['day'], 'label': _day_label(r['day'], today), 'rows': []})
        groups[-1]['rows'].append(r)
    return groups


def _level(n):
    if n <= 0:
        return 0
    if n <= 2:
        return 1
    if n <= 5:
        return 2
    if n <= 10:
        return 3
    return 4


def _calendar(events, last_seen, now):
    """Actions per day over the last 13 weeks, Monday-first columns (GitHub-style)."""
    today = _day(now)
    start = today - timedelta(days=today.weekday(), weeks=CALENDAR_WEEKS - 1)
    counts = Counter(e['day'] for e in events if e['cat'] in USER_DRIVEN and start <= e['day'] <= today)
    if last_seen:
        seen_day = _day(last_seen)
        if start <= seen_day <= today:
            counts[seen_day] = max(counts[seen_day], 1)  # they were active that day even if nothing was logged
    weeks = []
    for w in range(CALENDAR_WEEKS):
        monday = start + timedelta(weeks=w)
        days = []
        for d in range(7):
            day = monday + timedelta(days=d)
            n = counts.get(day, 0)
            days.append({'date': day, 'n': n, 'level': _level(n), 'future': day > today})
        first_of_month = next((x['date'] for x in days if x['date'].day == 1), None)
        label = first_of_month.strftime('%b') if first_of_month else monday.strftime('%b') if w == 0 else ''
        weeks.append({'days': days, 'label': label})
    if len(weeks) > 1 and weeks[1]['label'] and weeks[0]['label']:
        weeks[0]['label'] = ''  # a month starts next week: don't print two labels side by side
    window = [day for day in counts if day > today - timedelta(days=90)]
    return {
        'weeks': weeks,
        'active_days': len(window),
        'actions': sum(counts[day] for day in window),
        'busiest': max(counts.values(), default=0),
    }


# ── Summary: facts, milestones, verdict ─────────────────────────────────────

def _steps(info, videos, has_skills, account, profile):
    """The launch checklist steps, read the same way /user-activity/ reads them."""
    return {
        'personal': bool(info and (info.full_name or '').strip() and (info.title or '').strip()),
        'project': videos > 0,
        'theme': bool(account and account.launch_theme_picked
                      or ((not account or not account.launch_status) and profile and profile.theme_id)),
        'skills': has_skills,
    }


def _milestones(user, raw, facts):
    joined = user.date_joined

    def first(test):
        hits = [e['at'] for e in raw if test(e)]
        return min(hits) if hits else None

    rows = [
        ('signed_up', 'Signed up', joined, True),
        ('verified', 'Verified email', first(lambda e: e['title'] == 'Verified their email'),
         facts['email_verified']),
        ('personal', ar.STEP_LABELS['personal'],
         first(lambda e: e['title'] in ('Added their name & title', 'Setup step done: Added name & title')),
         facts['steps']['personal']),
        ('project', ar.STEP_LABELS['project'],
         first(lambda e: e['title'].startswith('Added a video')), facts['steps']['project']),
        ('launched', 'Finished setup (100 XP)', first(lambda e: e['title'] == 'Finished setup (100 XP)'),
         all(facts['steps'].values())),
        ('pricing', 'Looked at pricing', first(lambda e: e['title'] == 'Opened the pricing page'),
         facts['pricing_opens'] > 0),
        ('checkout', 'Started a payment', facts['first_checkout'], facts['first_checkout'] is not None),
        ('paid', 'First payment', facts['first_paid'], facts['ever_paid']),
        ('renewed', 'Paid again (renewal or upgrade)', facts['first_renewal'], facts['first_renewal'] is not None),
    ]
    out = []
    for key, label, at, done in rows:
        done = bool(done or at)
        out.append({
            'key': key, 'label': label, 'done': done, 'at': at,
            'after': ('at signup' if key == 'signed_up' else f'{_span(at - joined)} after signup') if at else
                     ('date not recorded' if done else ''),
        })
    # Where they are stuck: the first step after their furthest one. A skipped earlier step (say, an
    # unverified email on a paying account) is a gap, not where they stopped.
    furthest = max((i for i, m in enumerate(out) if m['done']), default=0)
    stuck = next((m for m in out[furthest + 1:] if m['key'] != 'renewed'), None)
    for m in out:
        m['is_next'] = stuck is not None and m['key'] == stuck['key']
    return out


def _health(f):
    v = f['visits_30']
    parts = [
        {'label': 'Recent activity', 'max': 40, 'note': f['recency_label'],
         'points': {'today': 40, 'week': 30, 'month': 15}.get(f['recency'], 0)},
        {'label': 'Portfolio setup', 'max': 25, 'note': f'{f["xp"]} of 100 XP', 'points': round(f['xp'] / 4)},
        {'label': 'Plan', 'max': 20, 'note': f['plan_state_label'],
         'points': {'paying': 20, 'free_pass': 12, 'expired': 5}.get(f['plan_state'], 0)},
        {'label': 'Portfolio visitors', 'max': 15, 'note': f'{v} in the last 30 days',
         'points': 15 if v >= 20 else 10 if v >= 5 else 5 if v >= 1 else 0},
    ]
    for p in parts:
        p['pct'] = round(p['points'] / p['max'] * 100)
    score = sum(p['points'] for p in parts)
    band, label = ('strong', 'Strong') if score >= 70 else ('fair', 'Fair') if score >= 40 else ('weak', 'Weak')
    return {'score': score, 'band': band, 'label': label, 'parts': parts}


def _segment(f, now):
    days = lambda n: _plural(n, 'day')  # noqa: E731
    ps = f['plan_state']
    if ps == 'paying':
        if f['days_quiet'] >= ar.QUIET_DAYS:
            return ('at_risk', 'Paying customer at risk', 'risk',
                    f'Paying, but has not opened Skillifly for {days(f["days_quiet"])}. Customers who stop using '
                    'it rarely renew.')
        if f['plan_days_left'] is not None and f['plan_days_left'] <= ar.RENEWAL_DAYS:
            return ('renewal', 'Renewal due', 'action',
                    f'Plan ends {"today" if not f["plan_days_left"] else "in " + days(f["plan_days_left"])} '
                    f'({_date(f["plan_end"])}). Worth {_money(f["plan_value"])} EGP.')
        return ('healthy', 'Healthy paying customer', 'good',
                f'Active plan until {_date(f["plan_end"])} and using the product.')
    if ps == 'free_pass':
        return ('free_pass', 'On a free pass', 'info',
                f'Has a plan from a coupon, school or admin until {_date(f["plan_end"])}. '
                'Convert them before it ends.')
    if ps == 'expired':
        if f['ever_paid'] and f['plan_end'] >= now - timedelta(days=ar.WINBACK_DAYS):
            return ('winback', 'Lapsed customer, worth winning back', 'risk',
                    f'Plan ran out {_ago(f["plan_end"], now)} and they have not renewed. Their portfolio is offline.')
        if f['ever_paid']:
            return ('churned', 'Churned customer', 'risk',
                    f'Plan ran out {_ago(f["plan_end"], now)}. Total paid: {_money(f["spent"])} EGP.')
        return ('pass_ended', 'Free pass ended, never paid', 'info',
                f'Their free plan ran out {_ago(f["plan_end"], now)} and they did not buy one.')
    if f['checkout_open'] and f['last_checkout'] >= now - timedelta(days=ABANDONED_DAYS):
        return ('abandoned', 'Abandoned checkout', 'action',
                f'Started paying {_ago(f["last_checkout"], now)} but did not finish. The warmest kind of lead: '
                'ask what got in the way.')
    if f['videos'] and f['recency'] in ('today', 'week'):
        return ('upgrade', 'Ready to upgrade', 'action',
                f'Active this week with {_plural(f["videos"], "video")} added. The portfolio is built and only '
                'needs a plan to go live.')
    if f['recency'] in ('lapsed', 'one_day'):
        return ('dormant', 'Dormant free user', 'info',
                f'Free user, last active {f["last_active_ago"]}.'
                + ('' if f['returned'] else ' Never came back after signing up.'))
    if not f['videos']:
        stuck = now - f['joined'] >= timedelta(days=STALLED_DAYS)
        return ('stalled' if stuck else 'new', 'Not activated yet' if stuck else 'New signup', 'risk' if stuck else 'info',
                ('Signed up ' + f['joined_ago'] + ' and still has no video. Adding the first video is where a '
                 'portfolio starts to matter.') if stuck else
                f'Signed up {f["joined_ago"]}. No video yet, which is normal in the first days.')
    return ('exploring', 'Building, not paying yet', 'info',
            f'Free user with {_plural(f["videos"], "video")}, last active {f["last_active_ago"]}.')


def _actions(f, segment_key, receipts_to_review, raw, ratings, now):
    email = f['email']
    out = []
    for m in receipts_to_review:
        out.append({'tone': 'action', 'title': 'Review their payment receipt',
                    'body': f'{m.get_payment_method_display()} receipt for {_money(m.amount_expected)} EGP sent '
                            f'{_ago(m.created_at, now)} is waiting for a person to check it.',
                    'cta': 'Open receipt', 'href': f'/admin/core/manualpayment/{m.pk}/change/'})
    by_segment = {
        'at_risk': ('Send a personal check-in', 'Ask how the portfolio is working for them. A short personal '
                    'note works better than a discount.', 'How is your Skillifly portfolio working for you?'),
        'renewal': ('Send a renewal reminder', 'Remind them before the portfolio goes offline.',
                    'Your Skillifly plan is ending soon'),
        'winback': ('Ask what stopped them', 'One question, no pitch. The answer is useful even if they do '
                    'not come back.', 'Your Skillifly portfolio is offline'),
        'churned': ('Ask what stopped them', 'A one-line question about why they left feeds the roadmap.',
                    'Quick question about Skillifly'),
        'abandoned': ('Follow up on the checkout', 'Offer help with the payment method; wallet receipts and '
                      'card errors are the usual blockers.', 'Need a hand finishing your Skillifly payment?'),
        'upgrade': ('Offer the plan', 'Their portfolio is built. Show them what it looks like live.',
                    'Your Skillifly portfolio is ready to publish'),
        'free_pass': ('Plan the conversion', 'Reach out a few days before the free plan ends.',
                      'Keep your Skillifly portfolio online'),
        'stalled': ('Help them add a first video', 'Send the one-step link to paste a YouTube or Drive video.',
                    'Add your first video to Skillifly'),
        'healthy': ('Ask for a review or a referral', 'Happy paying customers are the best source of new ones.',
                    'Would you recommend Skillifly?'),
    }
    if segment_key in by_segment and not (segment_key == 'healthy' and f['wrote_review']):
        title, body, subject = by_segment[segment_key]
        out.append({'tone': 'action', 'title': title, 'body': body, 'cta': 'Email them',
                    'href': _mailto(email, subject)})

    missing = [ar.STEP_LABELS[k].lower() for k, done in f['steps'].items() if not done]
    if missing and segment_key not in ('stalled', 'new', 'dormant', 'churned', 'pass_ended'):
        out.append({'tone': 'info', 'title': 'Setup is not finished',
                    'body': 'Still to do: ' + ', '.join(missing) + '.', 'cta': '', 'href': ''})
    if f['live'] and f['visits_30'] == 0:
        out.append({'tone': 'info', 'title': 'Live, but nobody visited in 30 days',
                    'body': 'Suggest putting the portfolio link in their Instagram bio and client emails.',
                    'cta': '', 'href': ''})
    month_ago = now - timedelta(days=30)
    failures = sum(1 for e in raw if e['at'] >= month_ago and e['tone'] == 'bad'
                   and e['cat'] == 'portfolio')
    if failures:
        out.append({'tone': 'risk', 'title': f'Product signal: {_plural(failures, "error")} in 30 days',
                    'body': 'Failed saves or uploads this person hit. Worth checking the builder for this case.',
                    'cta': 'See them', 'href': '?cat=portfolio#timeline'})
    if ratings.get('down'):
        out.append({'tone': 'risk', 'title': f'Rated {_plural(ratings["down"], "AI reply", "AI replies")} unhelpful',
                    'body': 'Read what they asked to see where the assistant falls short.',
                    'cta': 'Read the chat', 'href': '?cat=ai#timeline'})
    return out[:4]


def _story(f, google, heard, now):
    s = []
    first = f'{f["first_name"]} signed up {f["joined_ago"]} ({_date(f["joined"])})'
    first += ' with Google' if google else ''
    if heard:
        first += f' after hearing about Skillifly through {HEARD_LABELS.get(heard.source, heard.source)}'
    s.append(first + '.')
    if f['first_video']:
        s.append(f'They added their first video {_span(f["first_video"] - f["joined"])} after signing up and now '
                 f'have {_plural(f["videos"], "video")}; setup is at {f["xp"]} of 100 XP.')
    else:
        s.append(f'They have not added a video yet; setup is at {f["xp"]} of 100 XP.')
    if f['ever_paid']:
        plan_now = (f'their plan runs until {_date(f["plan_end"])}' if f['plan_state'] in ('paying', 'free_pass')
                    else f'their plan ran out {_ago(f["plan_end"], now)}' if f['plan_end'] else 'no plan is running')
        s.append(f'They have paid {_money(f["spent"])} EGP over {_plural(f["paid_count"], "payment")}; '
                 f'{plan_now}.')
    elif f['pricing_opens']:
        s.append(f'They opened the pricing page {_plural(f["pricing_opens"], "time")} but have never paid.')
    else:
        s.append('They have never opened the pricing page.')
    s.append(f'Last active {f["last_active_ago"]}'
             + (f'; their portfolio got {_plural(f["visits_30"], "visit")} in the last 30 days.' if f['live'] or
                f['visits_30'] else '; their portfolio is not live.'))
    return s


# ── Public API ──────────────────────────────────────────────────────────────

def build_journey(user, now=None):
    now = now or timezone.now()
    account = UserAccount.objects.filter(user=user).first()
    profile = Profile.objects.filter(user=user).select_related('theme').first()
    from allauth.account.models import EmailAddress
    from allauth.socialaccount.models import SocialAccount
    socials = list(SocialAccount.objects.filter(user=user))

    activation = list(ActivationEvent.objects.filter(user=user).order_by('created_at'))
    signup_props = next((e.props or {} for e in activation if e.name == 'signup_completed'), {})
    project_events = [e for e in activation if e.name == 'project_created']

    account_rows, google = _account_rows(user, account, signup_props, socials)
    portfolio_rows, info = _portfolio_rows(user, project_events)
    payment_rows, tracking, payments, receipts = _payment_rows(user, now)
    ai_rows, chats, ratings = _ai_rows(user)
    raw = (account_rows + portfolio_rows + payment_rows + ai_rows + _email_rows(user) + _traction_rows(user)
           + [r for r in map(_activation_row, activation) if r])
    for e in raw:
        e['day'] = _day(e['at'])
        e['cat_label'] = CATEGORY_LABELS[e['cat']]
    raw.sort(key=lambda e: e['at'], reverse=True)

    # ── Facts ──
    projects = Project.objects.filter(user=user)
    videos = projects.count()
    has_skills = Skill.objects.filter(user=user).exists()
    steps = _steps(info, videos, has_skills, account, profile)
    paid = [p for p in payments if p.status == 'paid']
    plan = ar._plan_info(paid, now, ar._plan_prices())
    priced = [p for p in paid if p.amount > 0]

    own = [e['at'] for e in raw if e['cat'] in USER_DRIVEN]
    last_seen = profile.last_seen if profile else None
    last_active = max(filter(None, (last_seen, user.last_login, user.date_joined, max(own, default=None))))
    returned = last_active - user.date_joined >= timedelta(days=1)
    recency = ar._recency(last_active, returned, now)

    checkout_starts = ([p.date for p in payments if p.status != 'paid' and p.amount > 0]
                       + [m.created_at for m in receipts]
                       + [t.created_at for t in tracking if t.event_type == 'click' and t.action in CHECKOUT_CLICKS])
    last_paid = max((p.date for p in paid), default=None)
    last_checkout = max(checkout_starts, default=None)

    visits = _human_visits(user)
    visits_30 = visits.filter(created_at__gte=now - timedelta(days=30)).count()
    visits_prev = visits.filter(created_at__gte=now - timedelta(days=60), created_at__lt=now - timedelta(days=30)).count()
    project_times = [e['at'] for e in raw if e['title'].startswith('Added a video')]
    public = bool(profile and profile.is_public)
    name = _display_name(user, info)

    facts = {
        'email': user.email,
        'first_name': name.split()[0] if name else user.username,
        'joined': user.date_joined,
        'joined_ago': _ago(user.date_joined, now),
        'tenure_days': (now - user.date_joined).days,
        'last_active': last_active,
        'last_active_ago': _ago(last_active, now),
        'days_quiet': (now - last_active).days,
        'returned': returned,
        'recency': recency,
        'recency_label': ar.RECENCY_LABELS[recency],
        'steps': steps,
        'xp': sum(XP[k] for k, done in steps.items() if done),
        'videos': videos,
        'reels': projects.filter(video_type='reel').count(),
        'first_video': min(project_times, default=None),
        **plan,
        'plan_state_label': ar.PLAN_STATE_LABELS[plan['plan_state']],
        'plan_days_left': (plan['plan_end'] - now).days if plan['plan_end'] and plan['plan_end'] > now else None,
        'paid_count': len(priced),
        'first_renewal': priced[1].date if len(priced) > 1 else None,
        'live': public and plan['plan_state'] in ('paying', 'free_pass'),
        'public': public,
        'visits_30': visits_30,
        'visits_prev': visits_prev,
        'visits_all': visits.count(),
        'pricing_opens': sum(1 for t in tracking if t.event_type == 'page_view' and t.page == 'payment'),
        'first_checkout': min(checkout_starts, default=None),
        'last_checkout': last_checkout,
        'checkout_open': bool(last_checkout and (last_paid is None or last_checkout > last_paid)),
        'email_verified': EmailAddress.objects.filter(user=user, verified=True).exists()
                          or any(e.name == 'email_verified' for e in activation),
        'wrote_review': Review.objects.filter(reviewer=user).exists(),
    }

    seg_key, seg_title, seg_tone, seg_body = _segment(facts, now)
    to_review = [m for m in receipts if m.status in ('needs_review', 'pending')]
    heard = HeardAboutResponse.objects.filter(user=user).first()

    # ── KPIs ──
    delta = None
    if visits_prev or visits_30:
        diff = visits_30 - visits_prev
        delta = {'label': f'{diff:+,}', 'dir': 'good' if diff > 0 else 'bad' if diff < 0 else 'flat'}
    plan_sub = ''
    if plan['plan_state'] in ('paying', 'free_pass'):
        plan_sub = f'{plan["plan_label"]} · ends {_date(plan["plan_end"])} ({_plural(facts["plan_days_left"], "day")})'
    elif plan['plan_state'] == 'expired':
        plan_sub = f'{plan["plan_label"]} · ran out {_date(plan["plan_end"])}'
    elif facts['pricing_opens']:
        plan_sub = f'Opened pricing {_plural(facts["pricing_opens"], "time")}'
    else:
        plan_sub = 'Never opened pricing'
    calendar = _calendar(raw, last_seen, now)
    kpis = [
        {'label': 'Lifetime revenue', 'value': _money(plan['spent']), 'unit': 'EGP',
         'sub': (f'{_plural(len(priced), "payment")} · first on {_date(plan["first_paid"])}'
                 if priced else 'Has not paid yet')},
        {'label': 'Plan', 'value': facts['plan_state_label'], 'unit': '', 'sub': plan_sub},
        {'label': 'Last active', 'value': 'Today' if recency == 'today' else facts['last_active_ago'], 'unit': '',
         'sub': f'Active on {calendar["active_days"]} of the last 90 days'},
        {'label': 'Setup', 'value': str(facts['xp']), 'unit': '/ 100 XP',
         'sub': f'{sum(steps.values())} of {len(steps)} steps · {_plural(videos, "video")}'},
        {'label': 'Portfolio visits', 'value': f'{visits_30:,}', 'unit': 'in 30 days', 'delta': delta,
         'sub': f'{facts["visits_all"]:,} all time' + ('' if facts['live'] else ' · not live now')},
        {'label': 'Customer for', 'value': _plural(facts['tenure_days'], 'day'), 'unit': '',
         'sub': f'Signed up {_date(user.date_joined)}'},
    ]

    # ── Breakdown by area (all time, raw actions) ──
    by_cat = Counter(e['cat'] for e in raw)
    peak = max(by_cat.values(), default=0)
    areas = [{'key': k, 'label': label, 'count': by_cat.get(k, 0),
              'pct': round(by_cat.get(k, 0) / peak * 100) if peak else 0} for k, label in CATEGORIES]

    # ── Inventory, traction, ledger ──
    from core.models import Creator, Education, Experience, Link
    inventory = [
        ('Videos', f'{videos} ({facts["reels"]} reels, {videos - facts["reels"]} long)'),
        ('Uploaded video files', str(Video.objects.filter(user=user).count())),
        ('Categories', str(ProjectCategory.objects.filter(user=user).count())),
        ('Skills', str(Skill.objects.filter(user=user).count())),
        ('Work experience', str(Experience.objects.filter(user=user).count())),
        ('Education', str(Education.objects.filter(user=user).count())),
        ('Links', str(Link.objects.filter(user=user).count())),
        ('Creators they follow', str(Creator.objects.filter(user=user).count())),
        ('Theme', profile.theme.name if profile and profile.theme else 'None'),
        ('Profile photo', 'Yes' if profile and profile.picture else 'No'),
        ('Bio', 'Yes' if info and (info.bio or '').strip() else 'No'),
        ('Booking link', 'Yes' if info and info.booking_url else 'No'),
        ('Custom domain', getattr(CustomDomain.objects.filter(user=user).first(), 'domain', '') or 'None'),
    ]
    countries = Counter(c for c in visits.values_list('country', flat=True) if c and c != 'Unknown')
    referrers = Counter()
    for ref in visits.exclude(referer__isnull=True).exclude(referer='').values_list('referer', flat=True):
        host = urlsplit(ref).netloc.lower().removeprefix('www.')
        if host and 'skillifly' not in host and 'lvh.me' not in host:
            referrers[host] += 1
    last_visit = visits.order_by('-created_at').values_list('created_at', flat=True).first()

    ledger = []
    for p in payments:
        ledger.append({'at': p.date, 'what': f'{PLAN_LABELS[payment_plan(p)]} plan',
                       'method': METHOD_LABELS.get(payment_method(p), payment_method(p)),
                       'amount': p.amount, 'status': p.status,
                       'tone': 'good' if p.status == 'paid' else 'warn' if p.status == 'pending' else 'bad',
                       'note': p.discount_code_used or '',
                       'ends': p.expiration_date if p.status == 'paid' else None})
    for m in receipts:
        ledger.append({'at': m.created_at, 'what': f'{m.get_payment_method_display()} receipt',
                       'method': m.sender_identifier, 'amount': m.amount_expected,
                       'status': m.get_status_display(),
                       'tone': {'verified': 'good', 'rejected': 'bad'}.get(m.status, 'warn'),
                       'note': _short(m.rejection_reason or '', 80), 'ends': None,
                       'href': f'/admin/core/manualpayment/{m.pk}/change/'})
    ledger.sort(key=lambda r: r['at'], reverse=True)

    badges = [(ar.RECENCY_LABELS[recency], 'brand' if recency in ('today', 'week') else 'slate'),
              (facts['plan_state_label'], {'paying': 'good', 'free_pass': 'brand', 'expired': 'bad'}.get(
                  plan['plan_state'], 'slate')),
              ('Portfolio live' if facts['live'] else 'Not live', 'good' if facts['live'] else 'slate')]
    if account and account.account_type != 'editor':
        badges.append((account.get_account_type_display(), 'warn'))
    if google:
        badges.append(('Google sign-in', 'slate'))
    if user.is_superuser or user.is_staff:
        badges.append(('Team account', 'warn'))
    if not user.is_active:
        badges.append(('Deactivated', 'bad'))

    return {
        'now': now,
        'subject': user,
        'name': name,
        'initials': ar._initials(name),
        'phone': (info.phone if info and info.phone else '') or (profile.phone_number if profile else ''),
        'title': info.title if info else '',
        'badges': badges,
        'facts': facts,
        'segment': {'key': seg_key, 'title': seg_title, 'tone': seg_tone, 'body': seg_body},
        'story': _story(facts, google, heard, now),
        'health': _health(facts),
        'actions': _actions(facts, seg_key, to_review, raw, ratings, now),
        'kpis': kpis,
        'milestones': _milestones(user, raw, facts),
        'calendar': calendar,
        'areas': areas,
        'events': raw,
        'inventory': inventory,
        'traction': {'countries': countries.most_common(5), 'referrers': referrers.most_common(5),
                     'last_visit': last_visit},
        'ledger': ledger,
        'chats': chats,
        'mailto': _mailto(user.email, 'Hello from Skillifly'),
    }


def timeline(events, cat='', show_minor=True):
    rows = [e for e in events if (not cat or e['cat'] == cat) and (show_minor or not e['minor'])]
    return _collapse(rows)


# ── Search & directory rows ─────────────────────────────────────────────────

def _directory_rows(users, now):
    users = list(users)
    ids = [u.id for u in users]
    paid = defaultdict(list)
    for p in (UserPayment.objects.filter(user_id__in=ids, status='paid')
              .select_related('subscription').order_by('date', 'id')):
        paid[p.user_id].append(p)
    videos = dict(Project.objects.filter(user_id__in=ids).order_by().values_list('user_id')
                  .annotate(n=Count('id')))
    prices = ar._plan_prices()
    rows = []
    for u in users:
        try:
            info = u.personal_info
        except PersonalInfo.DoesNotExist:
            info = None
        try:
            last_seen = u.profile.last_seen
        except Profile.DoesNotExist:
            last_seen = None
        name = _display_name(u, info)
        last_active = max(filter(None, (last_seen, u.last_login, u.date_joined)))
        returned = last_active - u.date_joined >= timedelta(days=1)
        recency = ar._recency(last_active, returned, now)
        plan = ar._plan_info(paid.get(u.id, ()), now, prices)
        rows.append({
            'id': u.id, 'username': u.username, 'email': u.email, 'name': name,
            'initials': ar._initials(name), 'joined': u.date_joined,
            'last_active': last_active, 'last_active_ago': _ago(last_active, now),
            'recency': recency, 'recency_label': ar.RECENCY_LABELS[recency],
            'plan_state': plan['plan_state'], 'plan_state_label': ar.PLAN_STATE_LABELS[plan['plan_state']],
            'spent': _money(plan['spent']), 'videos': videos.get(u.id, 0),
        })
    return rows


def _base_users():
    return CustomUser.objects.exclude(username__in=ar.MOCK_USERNAMES).select_related('profile', 'personal_info')


def search_users(q, now=None, limit=SEARCH_LIMIT):
    """Match name, username, email, phone, custom domain or id. Exact hits first, then most recently seen."""
    now = now or timezone.now()
    q = (q or '').strip().lstrip('@')[:100]
    if not q:
        return []
    cond = (Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q)
            | Q(last_name__icontains=q) | Q(personal_info__full_name__icontains=q)
            | Q(personal_info__email__icontains=q) | Q(personal_info__phone__icontains=q)
            | Q(profile__phone_number__icontains=q) | Q(custom_domain__domain__icontains=q))
    parts = q.split()
    if len(parts) >= 2:
        cond |= Q(first_name__icontains=parts[0], last_name__icontains=' '.join(parts[1:]))
    if q.isdigit():
        cond |= Q(pk=int(q))
    matches = CustomUser.objects.filter(cond).values('pk')
    users = list(_base_users().filter(pk__in=matches)
                 .order_by(F('profile__last_seen').desc(nulls_last=True), '-date_joined')[:limit])
    low = q.lower()
    users.sort(key=lambda u: 0 if low in (u.username.lower(), u.email.lower()) or str(u.pk) == q else 1)
    return _directory_rows(users, now)


def recent_users(now=None, limit=12):
    """Landing lists for the lookup page: who was just active, and who just signed up."""
    now = now or timezone.now()
    active = _base_users().filter(profile__last_seen__isnull=False).order_by('-profile__last_seen')[:limit]
    newest = _base_users().order_by('-date_joined')[:limit]
    return _directory_rows(active, now), _directory_rows(newest, now)
