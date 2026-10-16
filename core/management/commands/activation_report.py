"""
Editor activation funnel report.

Counts only *real* editor signups (no superusers, the demo user, clients,
school admins or accounts that never verified their email) and reports how many
reached each funnel step, with 95% confidence intervals.

Usage:
    python manage.py activation_report --since 2026-05-01 --until 2026-09-30
    python manage.py activation_report --since 2026-05-01 --until 2026-09-30 \
        --compare-since 2026-10-26 --window-days 7
    python manage.py activation_report --since 2026-05-01 --stalled-csv logs/stalled.csv
"""
import csv
import math
import random
import statistics
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import ActivationEvent, CustomUser, PersonalInfo, Project, UserPayment


# ---------------------------------------------------------------------------
# Statistics (standard library only)
# ---------------------------------------------------------------------------

def wilson_interval(successes, n, z=1.96):
    """95% Wilson score interval for a proportion. Returns (low, high) in [0, 1]."""
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def prob_better(new_k, new_n, base_k, base_n, draws=100_000, seed=0):
    """P(new rate > baseline rate) under flat Beta(1, 1) priors, by Monte Carlo."""
    rng = random.Random(seed)
    wins = 0
    for _ in range(draws):
        new = rng.betavariate(1 + new_k, 1 + new_n - new_k)
        base = rng.betavariate(1 + base_k, 1 + base_n - base_k)
        if new > base:
            wins += 1
    return wins / draws


# ---------------------------------------------------------------------------
# Cohort helpers
# ---------------------------------------------------------------------------

def _day(value):
    try:
        return timezone.make_aware(datetime.strptime(value, '%Y-%m-%d'))
    except ValueError:
        raise CommandError(f'Bad date {value!r}; use YYYY-MM-DD.')


def raw_signups(start, end):
    """Every account that joined in [start, end), minus staff and the demo user."""
    qs = CustomUser.objects.filter(date_joined__gte=start).exclude(is_superuser=True).exclude(username='alex_mercer')
    if end is not None:
        qs = qs.filter(date_joined__lt=end)
    return qs


def split_cohort(start, end):
    """Return (raw, clients, school_admins, never_verified, editors) querysets/lists."""
    raw = raw_signups(start, end)
    clients = raw.filter(user_account__account_type='client')
    school_admins = raw.filter(user_account__account_type='school_admin')
    not_editors = raw.filter(user_account__account_type__in=['client', 'school_admin'])
    never_verified = raw.exclude(pk__in=not_editors.values('pk')).filter(is_active=False)
    editors = raw.exclude(pk__in=not_editors.values('pk')).filter(is_active=True)
    return raw, clients, school_admins, never_verified, editors


def _activated_within(user_ids, window_days):
    """Users who created a project within ``window_days`` of joining.

    Projects created before ``created_at`` existed have NULL and cannot be
    placed in time, so they never count here.
    """
    joined = dict(CustomUser.objects.filter(pk__in=user_ids).values_list('pk', 'date_joined'))
    hit = set()
    for uid, created in Project.objects.filter(
        user_id__in=user_ids, created_at__isnull=False,
    ).values_list('user_id', 'created_at'):
        if created <= joined[uid] + timedelta(days=window_days):
            hit.add(uid)
    return hit


def _pct(k, n):
    return f'{(100.0 * k / n):.0f}%' if n else 'n/a'


def _ci(k, n):
    low, high = wilson_interval(k, n)
    return f'{100 * low:.0f}-{100 * high:.0f}%'


class Command(BaseCommand):
    help = 'Report the editor activation funnel for a signup cohort.'

    def add_arguments(self, parser):
        parser.add_argument('--since', required=True, help='First signup date (YYYY-MM-DD).')
        parser.add_argument('--until', help='Last signup date, inclusive (YYYY-MM-DD). Default: today.')
        parser.add_argument('--window-days', type=int, default=7,
                            help='Activation window for the "within N days" metric (default 7).')
        parser.add_argument('--compare-since',
                            help='Start of the post-launch cohort to compare against the baseline.')
        parser.add_argument('--stalled-csv', help='Write the stalled-user outreach list to this CSV path.')
        parser.add_argument('--draws', type=int, default=100_000, help='Monte Carlo draws for --compare-since.')

    def handle(self, *args, **opts):
        start = _day(opts['since'])
        end = _day(opts['until']) + timedelta(days=1) if opts['until'] else None
        window = opts['window_days']

        raw, clients, school_admins, never_verified, editors = split_cohort(start, end)
        editor_ids = list(editors.values_list('pk', flat=True))
        n = len(editor_ids)

        has_theme = CustomUser.objects.filter(pk__in=editor_ids, profile__theme__isnull=False).count()
        has_info = PersonalInfo.objects.filter(user_id__in=editor_ids).values('user_id').distinct().count()
        project_users = set(Project.objects.filter(user_id__in=editor_ids).values_list('user_id', flat=True))
        three_plus = sum(
            1 for uid in editor_ids
            if Project.objects.filter(user_id=uid).count() >= 3
        )
        paid_users = set(UserPayment.objects.filter(
            status='paid', user_id__in=editor_ids,
        ).values_list('user_id', flat=True))
        within = _activated_within(editor_ids, window)

        label_end = opts['until'] or 'today'
        out = self.stdout.write
        out(f'Cohort {opts["since"]} -> {label_end}')
        out(f'  raw signups              {raw.count()}')
        out(f'  - clients                {clients.count()}')
        out(f'  - school admins          {school_admins.count()}')
        out(f'  - never verified         {never_verified.count()}')
        out(f'  = real editors           {n}')
        out(f'  has theme                {has_theme}')
        out(f'  has personal info        {has_info}')
        out(f'  >=1 project (ever)       {len(project_users)}  ({_pct(len(project_users), n)}, 95% CI {_ci(len(project_users), n)})')
        out(f'  >=1 project in {window}d       {len(within)}  ({_pct(len(within), n)}; only projects with a known created_at)')
        out(f'  >=3 projects             {three_plus}  ({_pct(three_plus, n)})')
        out(f'  paid                     {len(paid_users)}  ({_pct(len(paid_users), n)})')
        out(f'  paid, no project         {len(paid_users - project_users)}')

        self._event_funnel(editor_ids, out)

        if opts['compare_since']:
            self._compare(opts, start, end, len(project_users), n, window, out)
        if opts['stalled_csv']:
            self._write_stalled(opts['stalled_csv'], start, end, project_users, paid_users, out)

    # -- sections ----------------------------------------------------------

    def _event_funnel(self, editor_ids, out):
        events = ActivationEvent.objects.filter(user_id__in=editor_ids)
        if not events.exists():
            out('Event funnel: no activation events recorded for this cohort yet.')
            return

        def users(name, **props):
            qs = events.filter(name=name)
            ids = set()
            for uid, p in qs.values_list('user_id', 'props'):
                if all(p.get(k) == v for k, v in props.items()):
                    ids.add(uid)
            return ids

        out('Event funnel (distinct users):')
        out(f'  welcome_viewed                         {len(users("welcome_viewed"))}')
        out(f'  link_previewed (ok)                    {len(users("link_previewed", ok=True))}')
        out(f'  project_created (source=welcome)       {len(users("project_created", source="welcome"))}')
        out(f'  reveal_viewed                          {len(users("reveal_viewed"))}')
        out(f'  welcome_skipped                        {len(users("welcome_skipped"))}')

        first = {}
        first_source = {}
        for uid, p, created in events.filter(name='project_created').order_by('created_at').values_list(
            'user_id', 'props', 'created_at',
        ):
            if uid not in first_source:
                first_source[uid] = p.get('source', 'other')
            if uid not in first and 'seconds_since_signup' in p:
                first[uid] = p['seconds_since_signup']
        if first:
            out(f'  median signup -> first project         {int(statistics.median(first.values()))}s  (n={len(first)})')
        if first_source:
            counts = {}
            for source in first_source.values():
                counts[source] = counts.get(source, 0) + 1
            breakdown = ', '.join(f'{k}={v}' for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
            out(f'  first project by source                {breakdown}')
            if counts.get('concierge'):
                out('    (concierge = set up by hand for the user: not real product activation)')

    def _compare(self, opts, start, end, base_k, base_n, window, out):
        new_start = _day(opts['compare_since'])
        _, _, _, _, new_editors = split_cohort(new_start, None)
        cutoff = timezone.now() - timedelta(days=window)
        eligible = list(new_editors.filter(date_joined__lte=cutoff).values_list('pk', flat=True))
        hit = _activated_within(eligible, window)
        k, n = len(hit), len(eligible)
        out(f'Compare: signups since {opts["compare_since"]} that are at least {window}d old')
        out(f'  activated within {window}d   {k}/{n}  ({_pct(k, n)}, 95% CI {_ci(k, n)})')
        out(f'  baseline (ever)           {base_k}/{base_n}  ({_pct(base_k, base_n)})')
        if n:
            p = prob_better(k, n, base_k, base_n, draws=opts['draws'])
            out(f'  P(new rate > baseline) = {p:.2f}  (Beta-Binomial, {opts["draws"]} draws)')
        else:
            out('  Not enough post-launch signups yet.')

    def _write_stalled(self, path, start, end, project_users, paid_users, out):
        raw, _, _, never_verified, editors = split_cohort(start, end)
        info_users = set(PersonalInfo.objects.values_list('user_id', flat=True))
        rows = []

        def lang_of(u):
            account = getattr(u, 'user_account', None)
            return (account.signup_lang if account else '') or ''

        for u in never_verified.select_related('user_account'):
            rows.append((u, 'never_verified'))
        for u in editors.select_related('user_account'):
            if u.pk in paid_users:
                continue
            if u.pk in project_users:
                rows.append((u, 'uploaded_unpaid'))
            elif u.pk in info_users:
                rows.append((u, 'info_no_project'))
            else:
                rows.append((u, 'no_save'))

        with open(path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['email', 'username', 'first_name', 'date_joined', 'lang', 'segment', 'projects'])
            for u, segment in rows:
                writer.writerow([
                    u.email, u.username, u.first_name, u.date_joined.date().isoformat(),
                    lang_of(u), segment, Project.objects.filter(user=u).count(),
                ])
        out(f'Wrote {len(rows)} stalled users to {path} (contains emails: do not commit).')
