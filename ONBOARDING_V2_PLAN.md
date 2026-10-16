# Onboarding v2: Implementation Plan

**Goal:** raise "uploaded at least one project" from **28% to at least 40%** of new editor signups (stretch target: 50%).

**Approach:**
- Make "paste one video link" the first step after signup.
- Show users their own portfolio right after that.
- Ask for everything else later.

**Status:** **implemented** (all seven PRs), 2026-10-16, on top of `main` @ `7489b3a`. See
[Implementation status](#implementation-status) below for what exists, the switches, and where the build
deviates from the plan. Nothing is switched on yet: every user-visible change is behind a Site Settings flag.

---

## Implementation status

| PR | Built | Where |
|---|---|---|
| PR-1 | `ActivationEvent` + `core.activation.track`, `post_save` signal for projects, signup/verify/builder events, `created_at` on Project/PersonalInfo, `activation_report` command (Wilson CI, Beta-Binomial compare, stalled CSV), admin, optional Clarity | `core/activation.py`, `core/signals.py`, `core/management/commands/activation_report.py` |
| PR-2 | Name/title pre-fill, default theme, first-project -> own portfolio, first-run dashboard, checklist order, link hint copy, OTP hardening (send failure, 5-attempt cap, 30-min life) | `core/onboarding.py`, `builder/views.py`, `core/views.py`, dashboard templates |
| PR-3 | Link lookup with SSRF-safe thumbnail download | `core/oembed.py` |
| PR-4 | `/welcome/` + `/ar/welcome/`, live preview endpoint, reveal bar, routing, reserved usernames | `core/views.py`, `templates/onboarding/` |
| PR-5 | Six nudges, quiet hours, unsubscribe, systemd units | `core/nudges.py`, `send_onboarding_nudges`, `deploy/systemd/` |
| PR-6 | Deferred email verification + honeypot + signup rate limit | `core/views.py` (`_editor_signup`), `core/onboarding.py` |
| PR-7 | Theme chips on the bar, projects-first builder + "Client-ready x/3", one-click AI bio, next-step card, short signup | `builder_v2.js`, `core/views.py`, signup templates |

**Switches** (Admin -> Site Settings, all default off): `onboarding_v2_enabled`, `defer_email_verification`,
`nudges_enabled`, `default_editor_theme`. The pre-fill, default-theme, redirect-to-portfolio, OTP-hardening,
reserved-username and tracking changes are *not* switched: they are safe on their own.

**Deviations from this plan**

| Plan said | Built | Why |
|---|---|---|
| One switch for everything | Separate `defer_email_verification` and `nudges_enabled` flags | Email verification and outbound email are the riskiest changes; they should be turned on independently |
| Signup rate limit 5/IP/hour | 10/IP/hour, only while verification is deferred | Egyptian ISPs and school labs share IPs; 5 would block real users |
| Nudge windows e.g. 1-23 h, 24-71 h | Contiguous half-open windows (1-24 h, 24-72 h, ...) | A late run could otherwise skip a user in the gap |
| Short signup form always | Only when `onboarding_v2_enabled` | Keeps the classic form untouched until launch; the form accepts both post shapes |
| "Work showcase first" via template edits | One-line change in `builder_v2.js` `ORDERS_BY_CATEGORY` | The builder already reordered sections per theme category; `ensure_default_theme` is what puts new editors in the video-editor order |
| (not in plan) | AI-bio 30 s cooldown; reserved-name check on profile rename; `?embed=1` hides the theme-preview bar | Found while testing: LLM cost abuse, route shadowing via rename, "Apply Theme" bar inside the welcome demo |
| (not in plan) | Fixed the signup help text that told users their URL was `portfoliobuilder.com/...` (and localised it on the Arabic page) | Wrong domain, pre-existing |
| (not in plan) | The builder's progress bar now refreshes while typing (was: only on add/remove/submit), and the first section opens without scrolling the page | The "Client-ready x/3" counter is pointless if it only moves on save; found by driving the real builder in a browser |
| (not in plan) | A nonexistent YouTube video (HTTP **400** from oEmbed) is refused; for TikTok/others a 400 is only a warning | Found by calling the live endpoints. YouTube's answer is reliable; TikTok's can mean "valid link oEmbed doesn't cover" |
| Concierge: "wrap admin/shell creation in `source('concierge')`" | `manage.py add_concierge_projects` + a "first project by source" line in `activation_report` | Makes hand-set-up portfolios easy to create and impossible to mistake for real activation |

**Running the tests**
```powershell
D:\skillifly_dev\venv\Scripts\python.exe manage.py test core.test_activation core.test_onboarding core.test_onboarding_extras core.test_nudges core.test_oembed core.test_concierge builder.test_builder_onboarding
# Real-browser checks (Playwright + Chromium, needs network for the Tailwind CDN); screenshots go to logs/onboarding-shots
$env:SKILLIFLY_BROWSER_TESTS = "1"; D:\skillifly_dev\venv\Scripts\python.exe manage.py test core.test_onboarding_browser
```
Baseline before this work: the full suite had 2 failures in `agent.tests` (reply-text assertions), unrelated.

---

## Contents

1. [Scope and principles](#1-scope-and-principles)
2. [Delivery overview](#2-delivery-overview)
3. [PR-1 Measurement foundation](#3-pr-1--measurement-foundation)
4. [PR-2 Quick wins](#4-pr-2--quick-wins)
5. [PR-3 Video link lookup service](#5-pr-3--video-link-lookup-service)
6. [PR-4 Welcome flow and reveal bar](#6-pr-4--welcome-flow-and-reveal-bar)
7. [PR-5 Nudge emails](#7-pr-5--nudge-emails)
8. [PR-6 Deferred email verification (conditional)](#8-pr-6--deferred-email-verification-conditional)
9. [PR-7 Follow-ups](#9-pr-7--follow-ups)
10. [Copy deck (EN + AR drafts)](#10-copy-deck)
11. [Analytics: events, report, decision rule](#11-analytics)
12. [QA matrix](#12-qa-matrix)
13. [Rollout, monitoring, rollback](#13-rollout-monitoring-rollback)
14. [Open decisions](#14-open-decisions)

---

## 1. Scope and principles

**Who it applies to:** editor accounts only, meaning `UserAccount.account_type == 'editor'` or legacy users with no `UserAccount`. Client accounts, school admins and the `alex_mercer` demo user behave exactly as they do today.

**Principles:**
- **Nothing between signup and the first project.** Every field before it costs uploads.
- **Never block the user.** If a link lookup, thumbnail download or email fails, fall back to manual entry. No error pages.
- **One switch for behavior changes.** Every behavior change sits behind `SiteSettings.onboarding_v2_enabled`, which you can toggle in admin without a deploy. Safe fixes (pre-fill, copy text, email-code hardening) ship without it.
- **Arabic twins.** Every user-facing page ships with an `/ar/` version and a `ROUTE_MAP` entry in `core/middleware.py:128`.
- **Additive database changes only.** No column removals or renames, so rolling back never needs a reverse migration.
- **Measure before changing anything.** PR-1 ships first.

**Out of scope:**
- Pricing or paywall changes.
- CV, LinkedIn or GitHub import.
- Uploading video files during onboarding.
- Rewriting the builder.

---

## 2. Delivery overview

| PR | Title | Behind switch | Effort | Depends on | Target |
|---|---|---|---|---|---|
| PR-1 | Measurement foundation (database changes, events, report) | — | 1–1.5 d | — | Days 1–2 |
| PR-2 | Quick wins (pre-fill, default theme, redirect to portfolio, empty-dashboard state, copy, email-code hardening) | Partly | 1–1.5 d | PR-1 | Days 2–3 |
| PR-3 | Video link lookup service (`core/oembed.py`) | — | 0.5–1 d | — | Day 3 (can run in parallel with PR-2) |
| PR-4 | Welcome page, reveal bar, routing new users to welcome | Yes | 2–2.5 d | PR-1, PR-2, PR-3 | Days 4–6 |
| PR-5 | Nudge emails and a scheduled job | Own switch | 2–3 d | PR-1 | Week 2 |
| PR-6 | Deferred email verification | Yes | 1 d | Baseline query result | Week 3, only if needed |
| PR-7 | Follow-ups (theme switcher, builder reorder, AI bio, shorter signup) | Yes | 3–4 d | PR-4 | Weeks 3–4 |

**Critical path:** PR-1 → PR-2 → PR-4, with PR-3 alongside PR-2. That's about **5–6.5 developer days**, i.e. roughly one focused week.

**Migrations:**
- `0082_onboarding_foundation` (PR-1) carries all schema for PR-1 and PR-2.
- `0083_nudges` (PR-5).

The latest existing migration is `0081_profile_theme_settings`.

**Definition of done for every PR:**
1. `D:\skillifly_dev\venv\Scripts\python.exe manage.py test` passes.
2. The English and Arabic pages have both been checked in a browser at `http://lvh.me:8000`.
3. With the switch **off**, behavior is identical to today, except for the fixes listed as unswitched.
4. New events appear in Django admin under **Activation events**.

---

## 3. PR-1: Measurement foundation

**Why first:** today there's no way to measure time to first project. `Project` and `PersonalInfo` have no `created_at`, and the admin "signups" figure counts every user (`core/views.py:2767`): clients, school admins and accounts that never verified their email.

### T1.1 Schema: `core/models.py` + migration `0082_onboarding_foundation`

```python
# Project (core/models.py:228) and PersonalInfo (core/models.py:163)
created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
# null=True: existing rows stay NULL ("unknown") and makemigrations won't prompt for a default.

# UserAccount (core/models.py:71)
signup_lang = models.CharField(max_length=2, blank=True, default='')  # 'en' | 'ar'

# EmailOTP (core/models.py:103), used by the brute-force fix in T2.6
attempts = models.PositiveSmallIntegerField(default=0)

# SiteSettings (core/models.py:471)
onboarding_v2_enabled = models.BooleanField(
    default=False,
    help_text="New editor onboarding: welcome page, first-run dashboard, reveal bar.",
)
default_editor_theme = models.ForeignKey(
    'Theme', null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    help_text="Theme auto-assigned to new editors. Must not need a profile photo "
              "(not Animated / Animated Dark / Creative White). Empty = Video Editor › Creative.",
)

# New model
class ActivationEvent(models.Model):
    """One step of the editor activation funnel (signup → first project → paid)."""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='activation_events')
    name = models.CharField(max_length=40, db_index=True)
    props = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['name', 'created_at'])]

    def __str__(self):
        return f"{self.name} · {self.user_id}"
```

**Risk:** production runs MySQL (`mysqlclient` in `requirements.txt`). All of these are plain column additions with no data migration, so this is safe.

### T1.2 Tracking helper: new `core/activation.py`

This follows the flat-module style of `core/ai.py` and `core/cloudflare_stream.py`.

```python
"""
Activation tracking for the editor onboarding funnel.

Best-effort and server-side: a tracking failure must never break a page.
Event names are whitelisted so a typo can't silently start a new series.
"""
import contextvars
import logging
from contextlib import contextmanager

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('core')

EVENTS = frozenset({
    'signup_completed', 'email_verified', 'dashboard_viewed',
    'welcome_viewed', 'link_previewed', 'welcome_skipped', 'welcome_submitted',
    'project_created', 'reveal_viewed', 'reveal_action', 'theme_switched',
    'builder_saved', 'builder_save_failed', 'profile_field_added',
    'nudge_sent', 'nudge_clicked',
})

_source = contextvars.ContextVar('activation_source', default='other')


@contextmanager
def source(name):
    """Label every Project created inside this block (builder / welcome / agent)."""
    token = _source.set(name)
    try:
        yield
    finally:
        _source.reset(token)


def current_source():
    return _source.get()


def is_editor(user):
    account = getattr(user, 'user_account', None)  # RelatedObjectDoesNotExist is an AttributeError
    return account is None or account.account_type == 'editor'


def seconds_since_signup(user):
    return max(0, int((timezone.now() - user.date_joined).total_seconds()))


def track(user, name, **props):
    if name not in EVENTS:
        logger.warning('Unknown activation event %r', name)
        return
    if user is None or not getattr(user, 'pk', None) or user.username == 'alex_mercer':
        return
    try:
        from core.models import ActivationEvent
        # Own savepoint: a failure here must not poison an outer atomic block
        # (save_portfolio_data runs inside @transaction.atomic).
        with transaction.atomic():
            ActivationEvent.objects.create(user=user, name=name, props=props)
    except Exception:
        logger.debug('Failed to record activation event %s', name, exc_info=True)
```

### T1.3 "Project created" signal: new `core/signals.py` + `core/apps.py`

Projects are created in several places: the builder (`builder/views.py` `_update_or_create`, around line 614), the AI agent (`agent/tools.py:264`, `:409`), and later the welcome page. A single `post_save` signal catches all of them. The `source()` context var labels where each one came from.

```python
# core/signals.py
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from core import activation
from core.models import Project


@receiver(post_save, sender=Project, dispatch_uid='activation_project_created')
def project_created(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    src = activation.current_source()  # captured now; on_commit runs later
    user = instance.user
    url = instance.url or ''

    def _record():
        activation.track(
            user, 'project_created',
            source=src,
            nth=Project.objects.filter(user=user).count(),
            provider=_provider_of(url),  # swap for oembed.detect_provider after PR-3
            seconds_since_signup=activation.seconds_since_signup(user),
        )

    # Only count projects that actually committed.
    transaction.on_commit(_record)
```

```python
# core/apps.py
class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        from core import signals  # noqa: F401
```

**Labelling the source:**
- Wrap the builder saves in `with activation.source('builder'):` at `builder/views.py:257` and `:407`.
- Wrap the AI agent's tool dispatch (the caller of `agent/tools.py:264`, `:409`) in `with activation.source('agent'):`.

### T1.4 Where each event is recorded

| Event | Where | Details stored |
|---|---|---|
| `signup_completed` | `core/views.py:1141` (EN) and `:1174` (AR), right after `UserAccount.objects.create`. Also set `signup_lang`. | `method='email'`, `lang`, `account_type='editor'` |
| `signup_completed` | `core/adapters.py:67` `save_user`. Language comes from the `skillifly_lang` cookie. | `method='google'`, `lang`, `account_type` |
| `signup_completed` | Client and school-admin signup views | `account_type` (lets the report exclude them) |
| `email_verified` | `core/views.py:1566` success branch of `verify_otp_view` | `minutes_since_signup` |
| `dashboard_viewed` | `dashboard_view` (`:1784`) / `arabic_dashboard_view` (`:1794`) | `projects`, `first_run` (bool) |
| `builder_saved` | Success branches at `builder/views.py:257` and `:407` | `flow` (`builder` / `update`), `projects` |
| `builder_save_failed` | Failure branches at `builder/views.py:268` and `:418`, next to the existing `logger.warning` | `flow`, `sections`: names of the formsets that had errors |
| `project_created` | Signal (T1.3) | `source`, `nth`, `provider`, `seconds_since_signup` |

### T1.5 Admin

In `core/admin.py`, register `ActivationEvent`:
- `list_display = ('created_at', 'user', 'name', 'props')`
- `list_filter = ('name',)`
- `search_fields = ('user__username', 'user__email')`
- `date_hierarchy = 'created_at'`
- All fields read-only.

### T1.6 Report command: `core/management/commands/activation_report.py`

```
python manage.py activation_report --since 2026-05-01 [--until 2026-09-30] [--window-days 7]
                                   [--compare-since 2026-10-26] [--stalled-csv logs/stalled.csv]
```

**Who counts as a real signup:**
- Joined within the date range.
- Not a superuser, not `alex_mercer`.
- `is_active=True`.
- Not a client or school admin.

**Output** (plain text, so you can paste it into notes):

```
Cohort 2026-05-01 → 2026-09-30
  raw signups              81
  − clients                 x
  − school admins           x
  − never verified          x
  = real editors            N
  has theme                 …
  has personal info         …
  ≥1 project (ever)         …  (…%, 95% CI …–…)
  ≥1 project within 7 days  …  (only users whose project has created_at)
  ≥3 projects               …
  paid                      …   (paid with no project: …)
Event funnel (users with events):
  welcome_viewed → link_previewed(ok) → project_created(source=welcome) → reveal_viewed
  median signup → first project: …s
--compare-since: P(new rate > baseline) = 0.93   (Beta-Binomial, 100k draws)
```

**Implementation notes:**
- Reuse the ORM filters from the diagnostic query in the analysis.
- Compute the confidence interval with a small Wilson function (standard library only).
- For `P(new > baseline)`, draw from both distributions with `random.betavariate` and count how often the new one wins (Monte Carlo).

**`--stalled-csv` output:** the outreach list for section 7.4.
- **Columns:** `email, username, first_name, date_joined, lang, segment, projects`.
- **`segment`** is one of `never_verified`, `no_save`, `info_no_project`, `uploaded_unpaid`.
- The file contains emails, so write it under `logs/` (already gitignored) and never commit it.

### T1.7 Session recordings (optional, recommended)

- **Setting:** `settings.CLARITY_PROJECT_ID = os.environ.get("CLARITY_PROJECT_ID", "")`.
- **Exposing it:** add it to the template context through `core/context_processors.py`, and load the Microsoft Clarity snippet in `templates/core/base.html` (inside the `extra_head` area, before line 468).
- **Where it runs:** only for signed-in users, and only on signup, dashboard, builder and welcome pages.
- **Privacy:**
  - Keep Clarity's default input masking.
  - Add one sentence to the privacy policy (`templates/legal/`).

### T1.8 Tests (`core/tests.py`)

- `track()` ignores unknown names, ignores `alex_mercer`, and never raises (patch `ActivationEvent.objects.create` to throw).
- `track()` inside `transaction.atomic()` with a forced failure leaves the outer transaction usable.
- The signal records `project_created` with `source='builder'` when posting to `update_portfolio`. Wrap the request in `self.captureOnCommitCallbacks(execute=True)`; `TestCase` doesn't run on-commit callbacks otherwise.
- The signal doesn't fire when an existing project is updated.
- `activation_report` runs on an empty database and on fixtures with backdated `date_joined`. The existing tests already backdate this way: `User.objects.filter(id=…).update(date_joined=…)`.

### Acceptance and handoff

1. Deploy, then run `activation_report --since 2026-05-01 --until 2026-09-30 --stalled-csv logs/stalled.csv` on production.
2. Record the real-signup baseline in [§11.4](#114-baseline-fill-in-after-pr-1).
3. Count failed builder saves since May: `journalctl -u skillifly --since 2026-05-01 | grep -c "validation failed"`. The `builder.views` logger isn't configured in `LOGGING`, so these warnings go to the console (journald), not to `logs/django.log`.
4. **Go/no-go for PR-6:** if 5 or more real signups are "never verified", schedule PR-6.

---

## 4. PR-2: Quick wins

### T2.1 Pre-fill name and title in the builder (no switch)

**Problem:** signup already collects first and last name, but the builder asks for "Full name" again and requires a job title (`builder/views.py:436-446`). `_builder_flow`'s GET request (`:284`) doesn't pre-fill anything at all.

**Fix:** add helpers in a new `core/onboarding.py` (it also holds T2.3 and PR-4 logic):

```python
DEFAULT_TITLES = {  # keyed by normalized theme category
    'video_editor': ('Video Editor', 'مونتير فيديو'),
    'developer': ('Software Developer', 'مطوّر برمجيات'),
}

def default_title(user, arabic=False):
    profile = getattr(user, 'profile', None)
    category = (profile.theme.category.name if profile and profile.theme and profile.theme.category else 'Video Editor')
    en, ar = DEFAULT_TITLES.get(category.lower().replace(' ', '_'), DEFAULT_TITLES['video_editor'])
    return ar if arabic else en
```

```python
# builder/views.py
def _personal_initial(user, personal_info, arabic=False):
    if personal_info:
        return {...existing mapping from lines 438-445...}
    return {
        'fullname': user.get_full_name().strip(),
        'title': default_title(user, arabic),
    }
```

- Use it in both `_update_flow` (replacing lines 436-446) and `_builder_flow` (line 284: `PersonalInfoForm(initial=_personal_initial(...))`).
- **Don't** pre-fill the contact email: it's shown publicly, so the user should choose to add it.

**Tests:** a new user's GET on `update_portfolio` contains `value="First Last"` and `value="Video Editor"`; the Arabic version contains `مونتير فيديو`.

### T2.2 After the first project, go to the user's portfolio, not the dashboard (no switch)

In `_update_flow` (`builder/views.py:407-416`) and `_builder_flow` (`:257-266`):

```python
had_projects = Project.objects.filter(user=user).exists()
with activation.source('builder'):
    save_portfolio_data(...)
...
if not had_projects and Project.objects.filter(user=user).exists():
    return redirect(onboarding.reveal_url(user, arabic))
return redirect("arabic_dashboard" if arabic else "dashboard")
```

```python
# core/onboarding.py
def reveal_url(user, arabic=False):
    url = reverse('preview', kwargs={'username': user.username}) + '?welcome=1'
    return url + '&lang=ar' if arabic else url
```

Until PR-4 adds the reveal bar, `?welcome=1` has no visible effect. The user simply lands on their own portfolio, which is already the improvement.

**Tests:**
- The first save with a project redirects to `/<username>/?welcome=1`.
- A later save redirects to the dashboard.
- A save that adds no project redirects to the dashboard.

### T2.3 Default video-editor theme (no switch)

**Problem:** new users have no theme, so their preview falls back to `portfolios/developer/developer_minimal.html` (`portfolios/views.py:404`), a developer layout.

```python
# core/onboarding.py
PICTURE_REQUIRED_THEMES = {'animated', 'animated dark', 'creative white'}  # see builder.html:126
FALLBACK_THEME = ('video editor', 'creative')  # most-used editor theme (use_num 147 in dev DB)

def default_editor_theme():
    settings_row = SiteSettings.objects.select_related('default_editor_theme__category').first()
    theme = settings_row.default_editor_theme if settings_row else None
    if theme and theme.name.lower() not in PICTURE_REQUIRED_THEMES:
        return theme
    return Theme.objects.filter(category__name__iexact=FALLBACK_THEME[0],
                                name__iexact=FALLBACK_THEME[1]).first()

def ensure_default_theme(user):
    """Give editors without a theme the default one. Idempotent; never raises."""
    if not activation.is_editor(user):
        return None
    profile, _ = Profile.objects.get_or_create(user=user)
    if profile.theme_id:
        return profile.theme
    theme = default_editor_theme()
    if theme is None:
        logger.warning('No default editor theme available')
        return None
    profile.theme = theme
    profile.save(update_fields=['theme', 'updated_at'])
    return theme  # don't bump Theme.use_num: auto-assignment isn't a user choice
```

**Where to call it:**
- `dashboard_view` / `arabic_dashboard_view`, before `_dashboard_context`. This also covers the backlog of stalled users the next time they sign in.
- `_update_flow` / `_builder_flow` on GET requests.
- The welcome views (PR-4).

**Side effect to expect:** the dashboard's "Pick your theme" card becomes "Your theme: Creative", and the checklist's theme item starts out ticked. That's intended: users see progress straight away.

**Tests:**
- Editor gets Creative.
- A client gets nothing.
- An existing theme is never overwritten.
- If `default_editor_theme` is set to Animated, it falls back to Creative.
- If the theme is missing from the database, it returns `None` without crashing.

### T2.4 Theme picker redirect (no switch)

Once every editor has a theme, the "first theme" branch in `themes()` (`core/views.py:2426-2449`, Arabic version at `:2476-2498`) never runs again. Replace the redirect logic:

```python
# English version (themes); the Arabic version (arabic_themes) uses the arabic_* names.
if not Project.objects.filter(user=request.user).exists():
    if onboarding.onboarding_enabled():          # added in PR-4, once the route exists
        return redirect('welcome')
    return redirect('builder')
return redirect('preview', username=request.user.username)  # always show the new look
```

Keep the existing success message. In PR-2, ship it without the `onboarding_enabled()` branch.

### T2.5 Link hint copy (no switch)

The project model already embeds Instagram Reels, Google Drive and Facebook (`core/models.py:298-309`), and the reels/detail templates handle TikTok. The builder hint only mentions YouTube, Vimeo and TikTok. Update:

- `templates/dashboard/builder.html:493-494` and `:1009-1010`
- `templates/dashboard/arabic_builder_v2.html:537-538` and `:1053-1054`

New text: see copy keys `builder.link_placeholder`, `builder.link_hint` and `builder.drive_hint` in [§10](#10-copy-deck).

### T2.6 Harden the email-code step (no switch)

| Issue | Where | Fix |
|---|---|---|
| If sending the code fails (SMTP down), signup shows a 500 error after the inactive user is already created | `_send_otp_email` (`core/views.py:1095`) uses `fail_silently=False`, called at `:1142`, `:1175` | Wrap the `send_mail` in try/except. Log it, still redirect to `verify_otp`, and show "We couldn't send the code. Tap Resend." |
| No limit on wrong codes: a 6-digit code can be brute-forced within its lifetime | `verify_otp_view` (`:1552`) | Add 1 to `EmailOTP.attempts` on each wrong code. After 5, reject and require Resend. Resend (`:1600`) resets attempts. |
| 10-minute expiry is short when email is slow | `EmailOTP.is_expired` (`core/models.py:108`) | Extend to 30 minutes, **only together with** the attempt limit |

**Tests:**
- A failing `send_mail` (patched) still redirects to `verify_otp` with no 500.
- The 6th wrong code is rejected even if it's correct.
- Resend resets attempts.
- A code at 29 minutes works; at 31 minutes it's expired.

### T2.7 Empty dashboard for new users (behind switch)

**Context:** in `_dashboard_context` (`core/views.py:2283`) add:

```python
is_first_run = onboarding.onboarding_enabled() and projects_count == 0 and plan_state == 'free'
context['is_first_run'] = is_first_run
# PR-2: the welcome route doesn't exist yet, so point at the builder's projects panel.
# PR-4 changes this to reverse('welcome') + '?from=dashboard_card'.
context['welcome_url'] = reverse('update_portfolio') + '#projects'
```

The `plan_state == 'free'` check makes sure people whose subscription expired still see billing.

**Ordering trap:** don't call `reverse('welcome')` anywhere in PR-2. The route arrives in PR-4, and `NoReverseMatch` would break the dashboard for every user. The same goes for T2.4's welcome branch: ship it as `builder` in PR-2 and switch it to `welcome` in PR-4.

**Template changes,** `dashboard.html` and `arabic_dashboard.html`:

| Element | EN location | AR location | When `is_first_run` |
|---|---|---|---|
| Offer banner (`{% if not has_active_payment and site_settings.banner_is_active %}`) | just above line 150 | line 302 | Add `and not is_first_run` |
| Header greeting "Welcome back" / "أهلاً بعودتك" | line 191 | line 344 | "Welcome" / "أهلاً بك" |
| Status strip `#visibility` (Private/Unlock, Visits, Membership) | lines 218-306 | line 371+ | Replace with the first-run card below |
| Membership card `.sf-member` | lines 456-495 | line 611+ | Hide |
| Tools & settings list (Upload video, Reviews, Analytics, SEO, Domain) | lines 389-449 | twin | Hide (irrelevant before the first video, and "Upload a video" may say "under development") |

```django
{% if is_first_run %}
<section class="sf-card reveal mb-8 p-6 sm:p-8" style="--d:70ms" aria-labelledby="first-run-title">
  <p class="sf-cap mb-2 !text-violet-600">Step 1</p>
  <h2 id="first-run-title" class="text-[22px] font-bold text-black" style="font-family:'Syne',sans-serif;">Add your first video</h2>
  <p class="text-slate-700 font-medium mt-1.5 text-[15px]">Paste a link and your portfolio builds itself around it. Takes under a minute.</p>
  <a href="{{ welcome_url }}" class="btn-primary mt-5 inline-flex items-center gap-2">
    Add a video <i data-lucide="arrow-right" class="!h-4 !w-4 rtl:rotate-180"></i>
  </a>
</section>
{% else %}
  … existing status strip …
{% endif %}
```

**Layout risk:** at ≥1280px the dashboard uses a CSS grid where `.sf-member` and `.sf-side` occupy fixed grid areas (`dashboard.html:14-25`). Hiding `.sf-member` can leave an empty cell. Check at 1280px and 1440px; if needed, add `.dash-grid.is-first-run .sf-side { grid-area: 2 / 2; }`.

### T2.8 Put projects first in the checklist (no switch)

In `_dashboard_context` (`core/views.py:2348`), reorder `checklist_items` to: `projects, personal, theme, skills, publish`. When `is_first_run`, the `projects` item links to `welcome_url` instead of `update_portfolio#projects` (`dashboard.html:548`).

### PR-2 acceptance

**With the switch off:**
- New users get a pre-filled builder and the Creative theme.
- They land on their own portfolio after adding their first project.
- The dashboard looks like today's, apart from the checklist order.

**With the switch on:** new users with no projects see only the first-run card on the dashboard.

---

## 5. PR-3: Video link lookup service

New module `core/oembed.py`. It needs no new dependencies (`requests` and `Pillow` are already installed) and no API keys.

### Contract

```python
@dataclass
class VideoMeta:
    url: str                     # normalized link that gets stored on Project.url
    provider: str = 'other'      # youtube | vimeo | tiktok | instagram | drive | facebook | other
    title: str = ''
    thumbnail_url: str = ''      # safe to show in the browser preview card
    thumbnail_candidates: list = field(default_factory=list)  # tried in order when downloading
    video_type: str = 'long'     # 'reel' | 'long'
    ok: bool = True
    error: str = ''              # '', 'invalid', 'private', 'not_found', 'timeout', 'network', 'provider_error'

def normalize_url(raw) -> str | None
def detect_provider(url) -> str
def fetch(url) -> VideoMeta                       # cached 24h, never raises
def download_thumbnail(meta) -> ContentFile | None  # never raises
```

### Behavior

| Step | Rule |
|---|---|
| Normalize | Trim. Reject empty input, anything over 500 characters (`Project.url` max length), or anything containing spaces. Add `https://` if missing. Accept only `http`/`https` with a dotted hostname. Rejects `javascript:` and `data:` links. |
| Detect provider | By hostname suffix: `youtube.com`/`youtu.be`, `vimeo.com`, `tiktok.com`, `instagram.com`, `drive.google.com`, `facebook.com`/`fb.watch` |
| TikTok short links | For `vm.tiktok.com` / `vt.tiktok.com`: one `HEAD` request (3 s timeout) to follow the redirect. Accept the result only if it lands on `tiktok.com`. |
| YouTube Shorts | Query oEmbed with the `watch?v=<id>` form, but store the original link. Mark it as a reel. |
| Lookup endpoints | YouTube `https://www.youtube.com/oembed` · Vimeo `https://vimeo.com/api/oembed.json` · TikTok `https://www.tiktok.com/oembed`. Parameters `url=…&format=json`, timeout 3 s, user agent `SkilliflyBot/1.0`. |
| Providers without a public lookup | Instagram, Drive, Facebook and others: return `ok=True` with an empty title and no thumbnail. The user types the title. |
| Errors | 401/403 → `private` · 404 → `not_found` · timeout → `timeout` · connection error → `network` · anything else or bad JSON → `provider_error` |
| Reel vs long | Reel for TikTok, YouTube `/shorts/` and Instagram `/reel/`, or when the lookup reports `height > width`. Long otherwise. |
| YouTube thumbnails | Try `https://i.ytimg.com/vi/<id>/maxresdefault.jpg` first (1280×720), then the lookup's `hqdefault`. The browser card shows `hqdefault`, which always exists. |
| Cache | `django.core.cache` with key `oembed:<sha1(url)>`, 24 h. No `CACHES` setting exists, so this is per-process memory. That's fine: it mainly saves repeat lookups between the preview and the submit. |

### Thumbnail download (security-sensitive)

This is the one place the server downloads a URL that comes from a third party, so it needs guardrails against server-side request forgery (SSRF):

- **Allowed hosts only,** https only. Hostname must end in `.ytimg.com`, `.vimeocdn.com`, `.tiktokcdn.com`, `.tiktokcdn-us.com`, `.tiktokcdn-eu.com` or `.ibyteimg.com`. Anything else is ignored.
- **`allow_redirects=False`**, so a redirect can't bounce the request to an internal address.
- **Streamed, 4 s timeout, 3 MB cap.** Abort once the cap is exceeded.
- **Must really be an image:** `Content-Type` must start with `image/`, and Pillow must be able to open and verify the bytes. Only JPEG, PNG and WebP are accepted.
- **Saved as** `ContentFile(data, name=f"oembed_{uuid4().hex[:12]}.{ext}")` into `Project.image` (`upload_to='projects/'`). Themes then render it through `image_thumb` like any other thumbnail.
- **TikTok thumbnail links are signed and expire,** so always keep a downloaded copy rather than storing their link.

### Tests: `core/test_oembed.py`, all with `requests` patched, no real network

- YouTube `watch`, `youtu.be`, `m.youtube.com`, a link with `&t=` / `&list=`, and `/shorts/` (reel) all parse correctly.
- Vimeo; TikTok (reel); `vm.tiktok.com` resolves to a `tiktok.com` link; an expansion to another host is rejected.
- Instagram reel: `ok`, reel, no network call made.
- Drive: `ok`, long, no network call made.
- 401 gives `private`, 404 gives `not_found`, a timeout gives `timeout`, bad JSON gives `provider_error`.
- `javascript:alert(1)`, a link with spaces, and a 501-character link are all rejected by `normalize_url`.
- A thumbnail from a non-allowed host is never requested.
- A redirecting response yields `None`; a 4 MB body yields `None`; a non-image body yields `None`.
- Maxres 404 falls back to `hqdefault`.
- The second `fetch()` of the same link uses the cache (one HTTP call in total).

---

## 6. PR-4: Welcome flow and reveal bar

### T4.1 Routes

In `core/urls.py`, which is included before the `portfolios` catch-all:

```python
path('welcome/', views.welcome_view, name='welcome'),
path('ar/welcome/', views.arabic_welcome_view, name='arabic_welcome'),
path('welcome/preview-link/', views.welcome_preview_link, name='welcome_preview_link'),  # POST JSON
path('welcome/skip/', views.welcome_skip, name='welcome_skip'),                          # POST
```

In `core/middleware.py` `ROUTE_MAP` (`:128`), add `'/welcome/': '/ar/welcome/'` and `'/ar/welcome/': '/welcome/'`.

### T4.2 Reserved usernames

`/welcome/` would hide the portfolio of any user named `welcome`, and nothing currently stops people registering usernames that match existing routes (`dashboard`, `hire`, …).

1. Add `RESERVED_USERNAMES` to `settings.py`: `welcome, dashboard, builder, signup, signin, logout, themes, profile, payment, preview, examples, hire, review, ar, blog, manage, admin, accounts, videos, email, static, media, api, sw.js`.
2. Set `ACCOUNT_USERNAME_BLACKLIST = RESERVED_USERNAMES`. allauth applies it on the Google username step.
3. Add a `clean_username` to `RegisterForm` (`core/forms.py:13`) that rejects names in that list, case-insensitively.
4. **Before deploying,** check production: `CustomUser.objects.filter(username__in=RESERVED_USERNAMES)`. Any existing `welcome` user needs handling first.

### T4.2b Point PR-2's links at the welcome page

- `_dashboard_context`: `welcome_url = reverse('welcome') + '?from=dashboard_card'`. Arabic: `reverse('arabic_welcome')`.
- `themes()` / `arabic_themes()`: add the `onboarding_enabled()` → welcome branch from T2.4.

### T4.3 Views (`core/views.py`)

```python
@login_required
def welcome_view(request):
    return _welcome_flow(request, arabic=False)


@login_required(login_url='arabic_signin')
def arabic_welcome_view(request):
    return _welcome_flow(request, arabic=True)


def _welcome_flow(request, arabic=False):
    from core import activation, onboarding
    user = request.user
    dashboard = 'arabic_dashboard' if arabic else 'dashboard'

    if not onboarding.onboarding_enabled():
        return redirect('arabic_update_portfolio' if arabic else 'update_portfolio')
    if not activation.is_editor(user):
        return redirect(dashboard)  # dashboard_view forwards clients / school admins

    adding = (request.GET.get('add') or request.POST.get('add')) == '1'
    if user.projects.exists() and not adding:
        return redirect(dashboard)

    onboarding.ensure_default_theme(user)
    row_errors = {}

    if request.method == 'POST':
        created, row_errors = onboarding.create_projects_from_links(user, request.POST, arabic=arabic)
        if created:
            onboarding.ensure_personal_info(user, arabic=arabic)
            activation.track(user, 'welcome_submitted', links=len(created), adding=adding)
            request.session['welcome_done'] = True
            return redirect(onboarding.reveal_url(user, arabic))
    else:
        activation.track(user, 'welcome_viewed', entry=request.GET.get('from', 'direct'), adding=adding,
                         nudge=request.GET.get('utm_campaign', ''))

    return render(request, 'onboarding/arabic_welcome.html' if arabic else 'onboarding/welcome.html', {
        'is_arabic_page': arabic,
        'adding': adding,
        'row_errors': row_errors,
        'posted': request.POST if request.method == 'POST' else None,
        'max_links': onboarding.MAX_LINKS,
        'demo_preview_url': onboarding.demo_preview_url(),
    })
```

```python
@login_required
@require_POST
def welcome_preview_link(request):
    """Live preview for one pasted link: {ok, provider, title, thumbnail_url, video_type, error, message}."""
    from core import activation, oembed, onboarding
    if not onboarding.allow_preview(request):  # session counter: 30 lookups/hour
        return JsonResponse({'ok': False, 'error': 'rate_limited'}, status=429)
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'invalid'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'ok': False, 'error': 'invalid'}, status=400)
    arabic = data.get('lang') == 'ar'
    url = oembed.normalize_url(data.get('url'))
    if not url:
        return JsonResponse({'ok': False, 'error': 'invalid', 'message': onboarding.error_message('invalid', arabic)})
    meta = oembed.fetch(url)
    activation.track(request.user, 'link_previewed', provider=meta.provider, ok=meta.ok, error=meta.error)
    return JsonResponse({
        'ok': meta.ok, 'url': meta.url, 'provider': meta.provider, 'title': meta.title,
        'thumbnail_url': meta.thumbnail_url, 'video_type': meta.video_type,
        'error': meta.error, 'message': onboarding.error_message(meta.error, arabic) if meta.error else '',
        'duplicate': request.user.projects.filter(url=meta.url).exists(),
    })


@login_required
@require_POST
def welcome_skip(request):
    from core import activation
    activation.track(request.user, 'welcome_skipped')
    request.session['welcome_routed'] = True
    return redirect('arabic_dashboard' if request.POST.get('lang') == 'ar' else 'dashboard')
```

### T4.4 Logic (`core/onboarding.py`)

```python
MAX_LINKS = 3

def onboarding_enabled():
    row = SiteSettings.objects.only('onboarding_v2_enabled').first()
    return bool(row and row.onboarding_v2_enabled)

def ensure_personal_info(user, arabic=False):
    """Create PersonalInfo from signup data so the builder never asks for it first."""
    PersonalInfo.objects.get_or_create(user=user, defaults={
        'full_name': user.get_full_name().strip() or user.username,
        'title': default_title(user, arabic),
        'email': '', 'phone': '', 'bio': '',
    })

def create_projects_from_links(user, data, arabic=False):
    """Create up to MAX_LINKS projects from the welcome form. Returns (created, {row: error})."""
    urls = data.getlist('url')[:MAX_LINKS]
    titles, types = data.getlist('title'), data.getlist('video_type')
    existing = set(Project.objects.filter(user=user).values_list('url', flat=True))
    created, errors = [], {}
    with activation.source('welcome'):
        for i, raw in enumerate(urls):
            if not (raw or '').strip():
                continue
            url = oembed.normalize_url(raw)
            if not url:
                errors[i] = 'invalid'
                continue
            if url in existing:
                continue  # double-submit / already added
            meta = oembed.fetch(url)  # usually a cache hit from the preview call
            if meta.error == 'private':
                errors[i] = 'private'  # would never play for visitors
                continue
            title = (titles[i] if i < len(titles) else '').strip()[:500] or meta.title or default_video_title(arabic)
            vtype = types[i] if i < len(types) and types[i] in ('long', 'reel') else meta.video_type
            project = Project(user=user, title=title, url=url, video_type=vtype)
            thumb = oembed.download_thumbnail(meta)
            if thumb:
                project.image.save(thumb.name, thumb, save=False)
            project.save()
            existing.add(url)
            created.append(project)
    return created, errors
```

**Notes:**
- Thumbnails download while the form submits: at most 3 downloads with a 4 s timeout each. No Celery is needed; this also avoids depending on whether a Celery worker runs in production.
- New projects get `order=0`, so they keep insertion (id) order, the same as the builder.

### T4.5 Send new editors to welcome (`core/views.py:1784`, `:1794`)

```python
def _route_to_welcome(request, arabic=False):
    from core import activation, onboarding
    if request.session.get('welcome_routed') or not onboarding.onboarding_enabled():
        return None
    user = request.user
    if not activation.is_editor(user) or user.projects.exists():
        return None
    request.session['welcome_routed'] = True  # once per session, so it never traps anyone
    return redirect(reverse('arabic_welcome' if arabic else 'welcome') + '?from=dashboard')
```

In `dashboard_view`, after the client and school-admin redirects:

```python
response = _route_to_welcome(request)
if response:
    return response
```

Do the same in `arabic_dashboard_view` with `arabic=True`.

**Why the dashboard:** every entry point ends there.
- Email signup → code check → `next_url`, which defaults to `dashboard`.
- Google signup → `LOGIN_REDIRECT_URL = 'dashboard'`.
- Sign-in → `dashboard`.

### T4.6 Welcome page templates

New files: `templates/onboarding/welcome.html` and `templates/onboarding/arabic_welcome.html`. Both extend `core/base.html`, using the `title`, `extra_head`, `ambient_orbs` (empty) and `content` blocks. The JavaScript is inline, following the project's convention.

**Layout:** one centered column on mobile. On desktop (≥1024px), two columns: the form, plus a live demo preview.

```
┌──────────────────────────────────────────────┬──────────────────────────┐
│ STEP 1 OF 2                                  │  ┌────────────────────┐  │
│ Start with your best edit                    │  │ live demo iframe   │  │
│ Paste a link and we'll build your portfolio… │  │ /preview/creative/ │  │
│                                              │  │ ?embed=1 (scaled)  │  │
│ [ Paste a YouTube, Vimeo, TikTok… link    ]  │  └────────────────────┘  │
│ ┌──────────────────────────────────────────┐ │  Yours will look like    │
│ │ [thumb] Title: [Nike – Urban Run      ]  │ │  this.                   │
│ │         ( Long video | Reel )            │ │                          │
│ └──────────────────────────────────────────┘ │                          │
│ + Add another video                          │                          │
│ [ Build my portfolio → ]                     │                          │
│ My work isn't online yet · Skip for now      │                          │
└──────────────────────────────────────────────┴──────────────────────────┘
```

**Form markup:** a normal `POST` form, so it works without JavaScript.
- Repeated fields `url`, `title`, `video_type` (up to 3 rows); a hidden `add` field when adding more.
- `{% csrf_token %}`.
- Link inputs have `dir="ltr"` on the Arabic page.

**Script behavior:**
1. **On paste or input in a link field:**
   - Wait 400 ms for typing to stop, then `fetch(POST /welcome/preview-link/)` with `{url, lang}` and the `X-CSRFToken` header.
   - Show a skeleton card while waiting.
2. **If the lookup succeeds:** show the thumbnail (`<img src=thumbnail_url>`; no Content-Security-Policy is set, so no changes needed), a pre-filled editable title, and the Reel/Long toggle preset from `video_type`. If `duplicate`, show "Already in your portfolio".
3. **If it fails:**
   - **Private:** show the message and don't count that row as valid.
   - **Timeout, network or provider error:** show "Couldn't load a preview…" and focus the title field. The row is still valid.
4. **Drive links:** also show the "Anyone with the link" sharing hint.
5. **Instagram and Facebook links:** focus the title field.
6. **Submit button:** enabled once any row is valid. On submit, disable it and show a "Building your portfolio…" spinner (prevents double submits).
7. **"+ Add another video":** clones a row; hidden once there are 3 rows.
8. **"Skip for now":** a small POST form to `welcome_skip` with `lang`.
9. **Demo iframe:** loads lazily, only when `matchMedia('(min-width: 1024px)')` matches, to save mobile data. It's scaled with CSS `transform: scale(.5)`, the same approach as the landing page showcase (`showcase_zoom`).
10. **Accessibility:** the preview card is `aria-live="polite"`, errors use `role="alert"`, every input has a label, and tap targets are at least 44px.

**When adding more videos (`adding` is true):** heading "Add more videos", no step label, and the button reads "Add to my portfolio".

### T4.7 Reveal bar (`portfolios/views.py`)

Change the start of `_inject_preview_bar` (`:151`):

```python
def _inject_preview_bar(request, response, profile, user):
    if user.username != 'alex_mercer':
        if (request.GET.get('welcome') == '1'
                and request.user.is_authenticated and request.user.pk == user.pk):
            return _inject_welcome_bar(request, response, user)
        return response
    … existing alex_mercer logic unchanged …
```

```python
def _inject_welcome_bar(request, response, user):
    from django.template.loader import render_to_string
    from core import activation
    arabic = request.GET.get('lang') == 'ar' or request.COOKIES.get('skillifly_lang') == 'ar'
    info = PersonalInfo.objects.filter(user=user).first()
    projects = Project.objects.filter(user=user).count()
    ready = {
        'videos': projects >= 3,
        'title': bool(info and info.title and info.title not in ('Video Editor', 'مونتير فيديو')),
        'contact': bool(info and (info.booking_url or info.phone)),
    }
    bar = render_to_string('onboarding/_welcome_bar.html', {
        'arabic': arabic, 'first_name': user.first_name or user.username,
        'projects': projects, 'ready': ready, 'ready_count': sum(ready.values()),
    }, request=request)
    activation.track(user, 'reveal_viewed', projects=projects)
    content = response.content.decode('utf-8')
    content = content.replace('</body>', bar + '</body>', 1) if '</body>' in content else content + bar
    response.content = content.encode('utf-8')
    return response
```

**Use a template, not an f-string.** The existing preview bar builds its HTML with f-strings, which is fine for admin-controlled theme names. `first_name` is user-controlled, so the bar **must** go through `render_to_string`, which escapes it, to avoid cross-site scripting (XSS).

**`templates/onboarding/_welcome_bar.html`:**
- Fixed to the bottom of the page, styled like the existing preview bar (`portfolios/views.py:180-233`). Uses its own CSS class prefix (`sfw-`) so it can't clash with theme styles.
- Collapses to a single column under 640px, and gets `dir="rtl"` when the page is Arabic.
- **Left side:** "This is your portfolio, {first_name}. Only you can see it for now." plus the checklist "Client-ready {ready_count}/3".
- **Actions**, each with `?ra=<action>` so a click can be recorded as `reveal_action` when the target page loads:
  - **Add more videos** → `/welcome/?add=1`
  - **Try another look** → `/themes/` (inline switcher comes in PR-7)
  - **Edit name & title** → `/builder/update/#identity`
  - **Go live** (main button) → `/payment/` (already tracked by `PaymentTrackingEvent`)
- **Dismiss (×):** hides the bar for that page view only.

**Visibility:** the bar only shows when the viewer is the owner. If the owner shares a link that still contains `?welcome=1`, other visitors see nothing extra (and see the 403 page until the portfolio is paid).

### T4.8 Tests (`core/tests_onboarding.py`)

| Test | Expectation |
|---|---|
| Switch off: `GET /welcome/` | Redirects to `update_portfolio`; the dashboard doesn't redirect |
| Switch on: new editor `GET /dashboard/` | Redirects to `/welcome/?from=dashboard`, once per session |
| Switch on: editor with projects | No redirect; `/welcome/` → dashboard; `/welcome/?add=1` returns 200 |
| Client or school admin | Never redirected; `/welcome/` → their dashboard |
| POST with a valid YouTube link (oEmbed patched) | Creates a project with title, image and type; `PersonalInfo` created; theme set; redirects to `/<username>/?welcome=1` |
| POST with the same link twice | One project |
| POST with a private link | No project; error shown in that row |
| POST with a lookup timeout | Project created with the typed title, no image |
| POST with 4 links | Only 3 created |
| `/ar/welcome/` | Arabic template, `dir="rtl"`; redirects to `&lang=ar` |
| Owner GET `/<username>/?welcome=1` | Bar present; `reveal_viewed` recorded |
| Another user or logged-out visitor with `?welcome=1` | No bar (logged-out visitor gets the 403 page while unpaid) |
| `first_name = '<script>'` | Escaped in the bar |
| Preview endpoint | Requires login and POST; 31st call in an hour returns 429 |
| Reserved username `welcome` | Rejected by `RegisterForm` |

### PR-4 acceptance

1. Deploy with the switch **off**.
2. Smoke-test on production with a test account: turn the switch on → sign up → paste a link → see your portfolio → turn the switch off.
3. Delete the test account (so it doesn't count toward the metrics), then turn the switch on for real.
4. Write the **launch date** in §11.4. It becomes the `--compare-since` value.

---

## 7. PR-5: Nudge emails

The app currently sends only email codes and password resets. There's no Celery scheduler and no systemd timer (`README_PROD.md` only covers gunicorn and nginx). Nudges therefore run as a management command, triggered by a systemd timer.

### T5.1 Schema (`0083_nudges`)

```python
class NudgeLog(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='nudges')
    key = models.CharField(max_length=40)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'key'], name='uniq_nudge_user_key')]

# UserAccount
email_opt_out = models.BooleanField(default=False)
```

### T5.2 Rules

Each run sends **at most one email per user**, and each email (`key`) is sent to a user at most once. The age windows mean the first deploy doesn't email every historical user; the backlog is handled personally instead (T5.6).

| Key | Account age | Condition | Subject (EN) | Main button |
|---|---|---|---|---|
| `no_project_1h` | 1 h – 23 h | 0 projects | Your portfolio is 60 seconds away | `/welcome/` |
| `no_project_24h` | 24 h – 71 h | 0 projects | See what other editors built | `/examples/` + `/welcome/` |
| `no_project_72h` | 72 h – 6 d | 0 projects | Quick question | reply to the email (plain text from the founder) |
| `no_project_7d` | 7 d – 8 d | 0 projects | Last note from Skillifly | `/welcome/` |
| `few_projects_48h` | 48 h – 6 d | 1–2 projects | Add 2 more videos to make it client-ready | `/welcome/?add=1` |
| `ready_unpaid_3d` | 3 d – 10 d | 3+ projects, no paid `UserPayment` | Your portfolio is ready to go live | `/payment/` |

**Who's eligible:** `is_active`, editor, `email_opt_out=False`, not a superuser, not `alex_mercer`.

**Quiet hours:** skip the run when the time in Cairo (`zoneinfo.ZoneInfo('Africa/Cairo')`; `TIME_ZONE` is UTC) is between 22:00 and 09:00. The windows are wide enough that a delayed email still lands inside them.

**Language:** use `UserAccount.signup_lang`. If it's empty, send a bilingual email (Arabic block first, then English).

**Links:** absolute URLs built from a new `settings.SITE_BASE_URL` (env, default `https://skillifly.cloud`), plus `?utm_source=nudge&utm_campaign=<key>`.
- The welcome and dashboard views record `nudge_clicked` when `utm_source=nudge` is present.
- Signed-out users are bounced to sign in first, and the `next` parameter brings them back with the tracking intact.

### T5.3 Command: `core/management/commands/send_onboarding_nudges.py`

Follows the structure of `reap_abandoned_uploads.py` (`--dry-run`, summary output).

```
python manage.py send_onboarding_nudges [--dry-run] [--limit 50] [--only no_project_1h] [--ignore-quiet-hours]
```

For each eligible user (joined in the last 11 days), check the rules in table order and pick the first match with no `NudgeLog` entry. Then:
1. Render `templates/emails/nudges/<key>.{html,txt}` (or `<key>_ar.*`).
2. Send with `EmailMultiAlternatives`, adding a `List-Unsubscribe` header.
3. Create a `NudgeLog` entry.
4. Record `nudge_sent`.
5. Wrap each email in try/except so one bad address doesn't stop the run.

### T5.4 Unsubscribe

- **Token:** `django.core.signing.dumps(user.pk, salt='nudge-unsub')`, no expiry.
- **Route:** `path('email/unsubscribe/<str:token>/', views.email_unsubscribe, name='email_unsubscribe')`. `email` is already on the reserved list.
- **GET:** shows a confirm page.
- **POST:** sets `email_opt_out=True`.
- **Footer:** every nudge email includes the unsubscribe link.

### T5.5 Scheduling on the VPS

```ini
# /etc/systemd/system/skillifly-nudges.service
[Unit]
Description=Skillifly onboarding nudges

[Service]
Type=oneshot
User=<app user>
WorkingDirectory=<path>/skillifly
ExecStart=<path>/venv/bin/python manage.py send_onboarding_nudges
```

```ini
# /etc/systemd/system/skillifly-nudges.timer
[Unit]
Description=Run Skillifly onboarding nudges hourly

[Timer]
OnCalendar=hourly
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
```

**Commands:**
- Enable: `sudo systemctl daemon-reload && sudo systemctl enable --now skillifly-nudges.timer`
- Check: `systemctl list-timers | grep skillifly` and `journalctl -u skillifly-nudges`

`settings.py` loads `.env` itself (`load_dotenv` at line 21), so no `EnvironmentFile` is needed.

**Optional:** add a matching timer for `reap_abandoned_uploads`. Its docstring says it should run periodically, but nothing schedules it today.

### T5.6 Deliverability, then the backlog

**Before the first send:**
1. Check SPF, DKIM and DMARC for `skillifly.cloud` with Hostinger (the SMTP host is `smtp.hostinger.com`).
2. Send one of each email to mail-tester.com and fix anything below 8/10.
3. Spam-foldered email codes would also explain part of the signup drop-off.

**Backlog (personal outreach, starting on day 1, independent of this PR):**
- Use `logs/stalled.csv` from T1.6.
- Send plain-text emails from your own address, per segment (copy in §10.3).
- Make the "reply with your links and I'll set it up" offer.
- Record each portfolio you set up for someone as a project created with `source='concierge'` (wrap the admin or shell creation in `activation.source('concierge')`), so the report shows those separately.

### T5.7 Tests

- Rule selection uses backdated `date_joined`: 2 h → `no_project_1h`; 30 h → `no_project_24h`; 30 h with 1 project → nothing; 50 h with 1 project → `few_projects_48h`.
- Running twice sends one email.
- Opted-out users, clients and school admins get nothing.
- `--dry-run` leaves `mail.outbox` empty and creates no `NudgeLog`.
- Quiet hours skip the run unless `--ignore-quiet-hours`.
- An Arabic user gets the Arabic template; a user with no language gets the bilingual one.
- An unsubscribe token for user A can't be altered to unsubscribe user B; GET doesn't unsubscribe, POST does.

---

## 8. PR-6: Deferred email verification (conditional)

**Only do this if** the PR-1 report shows **5 or more** real editor signups that never verified.

| Step | Change |
|---|---|
| Signup | `editor_signup_view` / Arabic version (`core/views.py:1137-1144`): create the user with `is_active=True` and `EmailAddress(verified=False, primary=True)`. Send the code (hardened per T2.6), log the user in, redirect to `dashboard`, which forwards to welcome. |
| Reminder | Dashboard and reveal bar show: "Verify your email to go live. We sent a code to {email}. [Enter code] [Resend]" |
| Verify page | `verify_otp_view` also accepts a signed-in user (use `request.user` when `verification_user_id` isn't in the session). On success, set `EmailAddress.verified=True`. |
| Gates | `activate_portfolio` (`:2384`) and the payment entry views (`payments/views.py` `pricing_view` checkout POSTs and the manual-payment submit) redirect unverified users to the verify page with `next` |
| Legacy | Existing inactive accounts still go through `signin_view`'s inactive branch (`:1495-1498`) as today |
| Abuse protection | A hidden honeypot field on the signup form, and a limit of 5 signups per IP per hour (`cache` counter) |

**Tests:**
- Signup logs the user in without a code.
- An unverified user can add projects but can't publish or reach checkout.
- Verifying unlocks both.
- The honeypot blocks signup.

---

## 9. PR-7: Follow-ups (weeks 3–4)

| ID | Item | Effort | Spec |
|---|---|---|---|
| T7.1 | Theme switcher in the reveal bar | 1.5 d | Three theme chips (the most-used editor themes that don't need a photo: Creative, Pro, Minimal). Each POSTs to a new `welcome/theme/` endpoint, which sets `Profile.theme`, records `theme_switched`, and reloads with `?welcome=1`. |
| T7.2 | Projects first in the builder (video editors) | 0.5–1 d | Reorder the sidebar items and panel sections in `builder.html` / `arabic_builder_v2.html` so Work showcase is section 1. Renumber the "Section N" labels. Replace `#bx-progress-label` "0 of 7 sections" with "Client-ready x/3". Check `static/js/builder_v2.js` navigation, which moves between panels using `data-nav-key` order. |
| T7.3 | One-click AI bio | 0.5 d | Dashboard prompt "Write my bio". POSTs to an endpoint that calls `core.ai.write_bio(user, language)` (falls back to a template if no AI provider is available), saves `PersonalInfo.bio`, and records `profile_field_added(field='bio', source='ai')`. |
| T7.4 | One "next best step" card on the dashboard | 0.5 d | The first true item among: fewer than 3 videos → add videos; no booking link or phone → "Add WhatsApp so clients can reach you in one tap"; no bio → AI bio; no skills → skills. |
| T7.5 | Shorter signup | 0.5–1 d | `RegisterForm`: a single "Full name" field split into `first_name` / `last_name` at the first space; remove `password2` (subclass and override `clean_password2`) and add a show/hide toggle; suggest a username from the name, still editable. Update `auth/signup.html` and `auth/arabic_signup.html`. |

---

## 10. Copy deck

The Arabic strings are drafts, written to match the existing UI's tone (e.g. "أهلاً بعودتك"). **Have a native speaker review them before launch.**

### 10.1 Product UI

| Key | EN | AR (draft) |
|---|---|---|
| `welcome.step` | Step 1 of 2 | الخطوة 1 من 2 |
| `welcome.title` | Start with your best edit | ابدأ بأقوى فيديو في أعمالك |
| `welcome.sub` | Paste a link and we'll build your portfolio around it. Takes under a minute. | الصق الرابط وسنبني معرض أعمالك حوله. أقل من دقيقة. |
| `welcome.placeholder` | Paste a YouTube, Vimeo, TikTok, Instagram Reel or Google Drive link | الصق رابط يوتيوب أو فيميو أو تيك توك أو ريلز إنستجرام أو جوجل درايف |
| `welcome.title_label` | Video title | عنوان الفيديو |
| `welcome.type_long` / `type_reel` | Long video / Reel | فيديو طويل / ريلز |
| `welcome.add_row` | + Add another video | + أضف فيديو آخر |
| `welcome.submit` | Build my portfolio → | ابنِ معرض أعمالي ← |
| `welcome.submitting` | Building your portfolio… | جارٍ بناء معرض أعمالك… |
| `welcome.not_online` | My work isn't online yet | أعمالي غير مرفوعة على الإنترنت بعد |
| `welcome.skip` | Skip for now | تخطَّ الآن |
| `welcome.demo_caption` | Yours will look like this. | هكذا سيبدو معرضك. |
| `welcome.add_title` | Add more videos | أضف فيديوهات أخرى |
| `welcome.add_submit` | Add to my portfolio | أضف إلى معرضي |
| `err.invalid` | Paste a full link, starting with https:// | الصق رابطًا كاملًا يبدأ بـ https:// |
| `err.private` | This video is private. Set it to Unlisted, then paste the link again. | هذا الفيديو خاص. اجعله «غير مُدرج» ثم الصق الرابط مرة أخرى. |
| `err.not_found` | We couldn't find that video. Check the link and try again. | لم نجد هذا الفيديو. تأكد من الرابط وحاول مرة أخرى. |
| `err.lookup_failed` | Couldn't load a preview, but you can still add it. Just type a title. | تعذّر تحميل المعاينة، لكن يمكنك إضافته. فقط اكتب عنوانًا. |
| `err.duplicate` | Already in your portfolio | موجود بالفعل في معرضك |
| `builder.link_placeholder` | YouTube, Vimeo, TikTok, Instagram Reel or Drive link | رابط يوتيوب أو فيميو أو تيك توك أو ريلز إنستجرام أو درايف |
| `builder.link_hint` | YouTube, Vimeo, TikTok, Instagram Reels and Google Drive links play right on your portfolio. | روابط يوتيوب وفيميو وتيك توك وريلز إنستجرام وجوجل درايف تُعرض مباشرة في معرضك. |
| `builder.drive_hint` | Google Drive: set sharing to "Anyone with the link". | جوجل درايف: اجعل المشاركة «أي شخص لديه الرابط». |
| `bar.title` | This is your portfolio, {name}. Only you can see it for now. | هذا معرض أعمالك يا {name}. أنت فقط من يراه الآن. |
| `bar.ready` | Client-ready {n}/3: 3 videos · your title · a way to contact you | جاهز للعملاء {n}/3: 3 فيديوهات · مسمّاك الوظيفي · وسيلة تواصل |
| `bar.add` | Add more videos | أضف فيديوهات أخرى |
| `bar.themes` | Try another look | جرّب تصميمًا آخر |
| `bar.edit` | Edit name & title | عدّل الاسم والمسمّى |
| `bar.live` | Go live | انشر معرضك |
| `dash.welcome_first` | Welcome | أهلاً بك |
| `dash.first_title` | Add your first video | أضف أول فيديو لك |
| `dash.first_cta` | Add a video | أضف فيديو |
| `default.title` | Video Editor | مونتير فيديو |
| `default.video_title` | My video | فيديو من أعمالي |

### 10.2 Nudge email subjects

| Key | EN | AR (draft) |
|---|---|---|
| `no_project_1h` | Your portfolio is 60 seconds away | معرض أعمالك على بُعد دقيقة واحدة |
| `no_project_24h` | See what other editors built | شاهد ما صنعه مونتيرون آخرون |
| `no_project_72h` | Quick question | سؤال سريع |
| `no_project_7d` | Last note from Skillifly | رسالة أخيرة من Skillifly |
| `few_projects_48h` | Add 2 more videos to make it client-ready | أضف فيديوهين ليصبح معرضك جاهزًا للعملاء |
| `ready_unpaid_3d` | Your portfolio is ready to go live | معرض أعمالك جاهز للنشر |

**Example body, `no_project_72h`** (plain text, sent from the founder's address):

> Hi {first_name}, I'm {founder}, I built Skillifly. You signed up a few days ago but haven't added a video yet. What got in the way? Just hit reply; one line is plenty. If it's easier, send me your video links and I'll set the portfolio up for you.

### 10.3 Backlog outreach (personal, by segment)

| Segment | Opening line |
|---|---|
| `no_save` | "You signed up for Skillifly but your portfolio is still empty. It now takes one link: paste your best video at {welcome_url} and it builds itself. Or reply with your links and I'll do it for you." |
| `info_no_project` | "Your portfolio has your name on it but none of your work yet, and the work is what clients judge. Paste one link at {welcome_url}, or reply with links and I'll add them." |
| `uploaded_unpaid` | "Your portfolio's ready. Here's {coupon} for {x}% off going live this week." (The `SiteSettings` banner coupon already exists.) |

---

## 11. Analytics

### 11.1 Event catalogue (final)

| Event | Recorded in | Details stored |
|---|---|---|
| `signup_completed` | Signup views, `SkilliflySocialAccountAdapter.save_user` | method, lang, account_type |
| `email_verified` | `verify_otp_view` | minutes_since_signup |
| `dashboard_viewed` | Dashboard views | projects, first_run |
| `welcome_viewed` | `_welcome_flow` GET | entry, adding, nudge |
| `link_previewed` | `welcome_preview_link` | provider, ok, error |
| `welcome_skipped` | `welcome_skip` | — |
| `welcome_submitted` | `_welcome_flow` POST success | links, adding |
| `project_created` | `post_save` signal | source, nth, provider, seconds_since_signup |
| `reveal_viewed` | `_inject_welcome_bar` | projects |
| `reveal_action` | Target views, when `?ra=` is present | action |
| `theme_switched` | T7.1 endpoint, `themes()` POST | from, to |
| `builder_saved` / `builder_save_failed` | Builder flows | flow, projects / sections |
| `profile_field_added` | Builder save diff, AI bio | field, source |
| `nudge_sent` / `nudge_clicked` | Nudge command / welcome and dashboard with `utm_source=nudge` | key |
| (existing) payment events | `PaymentTrackingEvent` | page, action, plan_type |

### 11.2 Metrics and thresholds

| Metric | Definition | Success | Alarm |
|---|---|---|---|
| **Activation (main metric)** | Real editor signups with ≥1 project within 7 days | **≥40%** (stretch 50%) | Below baseline after 15 signups |
| Welcome conversion | `welcome_submitted` users ÷ `welcome_viewed` users | ≥60% | <30% |
| Time to first project | Median `seconds_since_signup` on the user's first `project_created` | <300 s | >1 day |
| Aha reach | `reveal_viewed` within 30 min of the first project ÷ users who added one | ≥80% | <50% |
| Depth | ≥3 projects within 7 days ÷ real signups | ≥25% | — |
| Skip rate | `welcome_skipped` ÷ `welcome_viewed` | <30% | >40% (means people don't have links ready) |
| Link lookup health | `link_previewed ok=false` (excluding `private`/`invalid`) ÷ all lookups | <10% | >20% for 48 h |
| Revenue guardrail | Signup → paid within 30 days | ≥15% | <12% |

### 11.3 Decision rule

Write this down before launch so the bar can't move afterwards.

- **Baseline:** the real-signup May 1 – Sep 30 cohort, measured as "ever uploaded" (everyone in it is at least 2 weeks old).
- **After launch:** real signups from the launch date onward, each measured once their account is at least 7 days old.
- **Model:** Beta-Binomial with flat priors. `activation_report --compare-since <launch>` prints P(new rate > baseline).

| When | Decision |
|---|---|
| Every week | Read the early signals (welcome conversion, time to first project, aha reach, skip rate) and watch the session recordings |
| 15 real signups after launch | Sanity check only. If activation is below baseline **and** welcome conversion is under 30%, apply the kill criteria in §13.4. |
| **30 real signups** (~2 months) | **Keep the flow if P(better) ≥ 90%.** Against the raw 23/81 baseline that means at least **13 of 30** activated (12/30 ≈ 88%, 14/30 ≈ 96%). Recompute with the real-signup baseline. |
| 45 real signups | If P(better) is still under 70%, go back to diagnosis: interviews and recordings. |

Track acquisition mix (UTM parameters / referrer on `signup_completed`) so that a school promo or ad campaign doesn't get mistaken for a product effect.

### 11.4 Baseline (fill in after PR-1)

| Field | Value |
|---|---|
| Report run on | |
| Real editor signups (May 1 – Sep 30) | |
| ≥1 project (ever) | |
| 95% CI | |
| Never verified | |
| Failed builder saves since May (journalctl) | |
| Launch date (switch on) | |

---

## 12. QA matrix

Run on desktop Chrome, Android Chrome (low-end phone, slow 3G throttling) and iOS Safari, in **English and Arabic**.

| # | Scenario | Expected |
|---|---|---|
| 1 | Email signup (EN) → enter code | Lands on `/welcome/?from=dashboard` |
| 2 | Email signup (AR) → enter code | `/ar/welcome/`, right-to-left, link inputs left-to-right |
| 3 | Google signup as editor → pick username | `/welcome/` |
| 4 | Paste a YouTube `watch` link | Card: thumbnail, title, "Long video" |
| 5 | Paste YouTube `/shorts/` | "Reel" |
| 6 | Paste TikTok / `vm.tiktok.com` | "Reel", thumbnail shown |
| 7 | Paste an Instagram Reel | No thumbnail; title field focused; "Reel" |
| 8 | Paste a Google Drive link | Sharing hint shown; no thumbnail |
| 9 | Paste a private YouTube link | Private message; that row can't be submitted |
| 10 | Type plain text | "Paste a full link…" |
| 11 | Provider times out (block the domain in DevTools) | Fallback message; submitting with a typed title works |
| 12 | Double-click submit | Exactly one project |
| 13 | Three links | Three projects, in the order entered |
| 14 | After submit | Own portfolio in the Creative theme, real thumbnails, bar at the bottom |
| 15 | Same URL in a logged-out window | 403 private page, no bar |
| 16 | Another account opens `?welcome=1` | No bar |
| 17 | Skip | First-run dashboard card; no redirect again this session |
| 18 | Sign out and back in, still 0 projects | Redirected to welcome once |
| 19 | User with projects opens `/welcome/` | Dashboard; `?add=1` works |
| 20 | Client / school admin opens `/welcome/` | Their own dashboard |
| 21 | Switch off | Dashboard as today (except checklist order); `/welcome/` → builder |
| 22 | Expired payer with 0 projects | Billing widgets visible (not the first-run state) |
| 23 | First project saved from the builder (switch off **and** on) | Redirected to own portfolio |
| 24 | Builder for a new user | Name pre-filled from signup; title "Video Editor" / "مونتير فيديو" |
| 25 | Theme picked with 0 projects (switch on) | Redirected to welcome |
| 26 | Arabic video title from the provider | Saved; slug generated; displays correctly |
| 27 | SMTP down during signup | Verify page with "tap Resend", no 500 |
| 28 | 6 wrong email codes | Locked until Resend |
| 29 | Dashboard at 1280px and 1440px in first-run state | No empty grid cell |
| 30 | Reveal bar on a 360px-wide phone | Wraps to one column; buttons ≥44px; doesn't cover the theme's own controls permanently (× dismisses it) |

---

## 13. Rollout, monitoring, rollback

### 13.1 Schedule

| Day | Action |
|---|---|
| 1 | Merge and deploy PR-1. Run the baseline report (§11.4). Start personal outreach to stalled users. |
| 2–3 | PR-2 deployed. Pre-fill, default theme, redirect to portfolio, copy and email-code fixes are live immediately; the first-run dashboard stays behind the switch (off). |
| 3 | PR-3 merged (no visible change). |
| 4–6 | PR-4. Arabic copy reviewed. Full QA matrix. Deploy with the switch off, smoke-test on production, delete the test account, **turn the switch on**, record the launch date. |
| Week 2 | Watch daily. PR-5 built; check deliverability; enable the timer. |
| Weeks 3–4 | PR-6 (if needed), PR-7. |
| ~Week 9 | Decision at 30 real signups (§11.3). |

### 13.2 Deploy steps (each PR)

```bash
git pull
<venv>/bin/pip install -r requirements.txt   # no new dependencies expected
<venv>/bin/python manage.py migrate
<venv>/bin/python manage.py collectstatic --noinput   # only if static files changed
sudo systemctl restart skillifly             # gunicorn (socket-activated)
```

### 13.3 Monitoring (daily for the first 2 weeks, then weekly)

- `python manage.py activation_report --since <launch>`
- Admin → Activation events, filtered by `link_previewed`; scan for `ok=false`.
- `journalctl -u skillifly --since today | grep -iE "oembed|activation|validation failed"`
- Watch every new user's session recording (about 4 a week).
- Message every user who hasn't added a project within 48 hours: "What stopped you from adding a video?"

### 13.4 Rollback

| Part | How to roll back | Data impact |
|---|---|---|
| Welcome page, first-run dashboard, reveal bar | Admin → Site Settings → turn off `onboarding_v2_enabled`. No deploy. | None. Created projects and personal info are normal records. |
| Pre-fill, default theme, redirect to portfolio, copy (PR-2) | Revert the commit | Assigned themes stay (harmless); clear them if wanted |
| Email-code hardening | Revert the commit | `attempts` column unused |
| Nudges | `sudo systemctl disable --now skillifly-nudges.timer` | `NudgeLog` kept for history |
| Deferred verification | Revert the commit | Unverified accounts stay active; gates keep them unpublished |
| Migrations | Never reversed; all changes only add fields or tables | — |

**Kill criteria (switch off and investigate):**
- Link lookup failure above 20% for 48 h.
- Any 5xx error on `/welcome/` or `/welcome/preview-link/`.
- First 15 post-launch signups below baseline **and** welcome conversion under 30%.

---

## 14. Open decisions

| # | Decision | Recommendation |
|---|---|---|
| 1 | Default theme | **Video Editor › Creative**: most used, doesn't need a photo. Set it explicitly in `SiteSettings.default_editor_theme`. |
| 2 | Arabic default title | "مونتير فيديو" (common in Egypt) vs "محرر فيديو" (formal) |
| 3 | Show the price on the reveal bar's "Go live" button? | No. Keep it as "Go live" and let the pricing page sell. |
| 4 | Session-recording tool | Microsoft Clarity (free) + privacy-policy line. Or skip it and rely on interviews. |
| 5 | Defer email verification (PR-6)? | Decide from the PR-1 report (5+ never-verified → yes) |
| 6 | Who sends the backlog and 72h emails | Founder's personal address; replies are research data |
| 7 | Concierge setups | Yes, labelled `source='concierge'` and reported separately |
