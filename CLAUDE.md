# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Skillifly is a Django 5.2 / Python 3.13 portfolio-builder SaaS for video editors. Users build a
portfolio, pick a theme, and publish at `skillifly.cloud/<username>` or a custom domain. Fully
bilingual (English + Arabic RTL `/ar/...` twins). A broader guide lives at `../AGENTS.md`.

## Commands

The virtualenv lives one level up, outside this repo (`D:\skillifly_dev\venv`). Run from this directory:

```powershell
D:\skillifly_dev\venv\Scripts\python.exe manage.py runserver     # open http://lvh.me:8000, NOT localhost
D:\skillifly_dev\venv\Scripts\python.exe manage.py migrate
D:\skillifly_dev\venv\Scripts\python.exe manage.py test          # all tests
D:\skillifly_dev\venv\Scripts\python.exe manage.py test payments # one app
D:\skillifly_dev\venv\Scripts\python.exe manage.py test core.tests.SomeTestCase.test_method  # single test
D:\skillifly_dev\venv\Scripts\python.exe manage.py provision_ssl # custom-domain SSL (prod)
```

There's no lint or typecheck config. Verify changes with `manage.py test`. In dev, Celery runs
eagerly (`CELERY_TASK_ALWAYS_EAGER` defaults to `DEBUG`), so you don't need Redis or a worker.
Don't read `.env`. Settings are env-driven, and `.env.example` lists the variables.

## Architecture

**All models live in `core/models.py`**, even when another app uses them. The `models.py` files in other apps
(`portfolios`, `school`, `agent`, …) are intentionally empty. Put new models in `core` and
generate migrations there.

**URL order matters** (`skillifly/urls.py`): admin → allauth → ckeditor5 → `payments` → `builder/` →
`analytics` → `core` → `school` → `agent/` → **`portfolios` last**, because it holds the
`<username>/` catch-all. Any new top-level route must be registered before `portfolios`, or it
will be swallowed as a username.

**Middleware pipeline** (`core/middleware.py`, in order), which shapes how requests resolve:
1. `LocalhostRedirectMiddleware`: in dev, redirects `localhost` → `lvh.me` (cookies are scoped to `.lvh.me`).
2. `CustomDomainMiddleware`: rewrites `path_info` so a custom domain serves its owner's
   portfolio. Routing must never block on verification. `is_active` only gates SSL/canonical display.
3. `SubdomainRoutingMiddleware`: `blog.*` hosts switch to `skillifly/blog_urls.py`.
4. `LanguagePreferenceMiddleware`: `skillifly_lang` cookie and EN↔AR redirects via `ROUTE_MAP`.
   When you add a user-facing page, add both the EN and `/ar/` routes plus a `ROUTE_MAP` entry.
   Arabic templates set `is_arabic_page` and `dir="rtl"`.
5. `DynamicCsrfTrustedOriginsMiddleware`: injects active custom domains into `CSRF_TRUSTED_ORIGINS`.
6. `UpdateLastSeenMiddleware`.

**Apps:** `core` (landing, auth, dashboard, admin dashboard, themes, SEO, custom domains, affiliates),
`portfolios` (public rendering + `/preview/<theme>`), `builder` (formset-based editor + AJAX),
`payments` (Fawaterk, manual InstaPay/Vodafone Cash receipts verified by Gemini, coupons),
`blog`, `analytics`, `school` (`/school/<slug>/` pages for students/videos with ratings and comments),
`agent` (`/agent/` AI chat assistant that edits the user's portfolio through function-calling
tools in `agent/tools.py`, with snapshots and undo).

**AI layer:** `core/ai.py` is provider-agnostic. It tries Groq first, falls back to Gemini, and then
to deterministic templates. Placeholder or missing keys degrade silently. Generated copy is
grounded in real portfolio data (`portfolio_payload`). `agent/services.py` builds on it.

**Theme system:** a theme's name and category resolve to
`templates/portfolios/<category>/<category>_<theme_name>.html`, falling back to
`portfolios/developer/developer_minimal.html`. Each video_editor theme has `_reels`, `_long`,
`_detail`, and `_category` variants. Templates are large, self-contained files with inline JS. The
reels/long templates duplicate shared JS that must stay in sync across themes (the workspace-root
`patch_reels*.py` / `patch_themes.py` scripts show how bulk edits were done). A new theme needs
templates plus `Theme`/`Category` DB rows. `/preview/<theme>` renders the auto-seeded mock user
`alex_mercer` via `get_or_create_mock_user()`.

**Payments and visibility:** plans live in `payments/views.py` `PLAN_CATALOGUE` (monthly 99 EGP/30d,
`pro_annual` 449 EGP/365d; legacy `pro_monthly` rows may still exist). `UserPayment.is_active` means
paid and still within the plan's day window. `preview_view` automatically flips a profile to private when
the latest payment has lapsed (the mock user is exempt). `SKILLIFLY_COUPON_CODE` bypasses payment.

## Deployment

Production runs on an Ubuntu VPS with Gunicorn (unix socket) behind Nginx, systemd, certbot, and WhiteNoise.
The DB is SQLite or Postgres via `DATABASE_URL`. See `README_PROD.md` and `deploy_skillifly.sh`. Never commit
`.env`, `db.sqlite3`, `media/`, `staticfiles/`, or `logs/`.
