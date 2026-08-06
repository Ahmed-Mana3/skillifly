<div align="center">

# 🎬 Skillifly

**The #1 portfolio builder for video editors and creative professionals.**

Build a stunning portfolio in minutes — publish it at `skillifly.cloud/<username>`
or on your own custom domain. Showcase reels and long-form work side by side.

Bilingual (**English / العربية RTL**) · Free / Pro / Annual plans

</div>

---

## ✨ Features

- **Video-first portfolios** — dedicated layouts that treat Reels (short-form)
  and Long Videos as first-class citizens, with YouTube / Vimeo / Drive embeds.
- **Curated themes** — a growing library of premium themes (Creative, Minimal,
  Cinematic, Editorial Studio, Monochrome, Yellow, Cyan, Animated…), each with
  dedicated reels, long-video, category, and detail pages.
- **Instant publishing** — portfolios go live at `skillifly.cloud/<username>`
  immediately, plus **custom domain** support.
- **AI-verified manual payments** — users pay via Fawaterk or submit an
  InstaPay / Vodafone Cash receipt that **Google Gemini AI** verifies.
- **PDF export** — active annual subscribers export their portfolio as a PDF,
  generated asynchronously with **Celery + Playwright/Chromium** and cached.
- **Portfolio analytics** — 30-day visitor/event dashboard per portfolio.
- **Full RTL Arabic** — every page has an English and an Arabic (`/ar/…`) twin.
- **Blog** — Arabic-aware slugs, CKEditor-5 rich text, sitemaps, and a
  `blog.*` subdomain served by the same Django app.
- **Affiliate program** — track earnings from referred customers.
- **Admin dashboard** — users, revenue, discounts, banner settings, reviews,
  showcases, and SEO tools.

---

## 🧱 Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5.2.8 · Python 3.13 |
| Database | SQLite (dev) / PostgreSQL (prod, via `DATABASE_URL`) |
| Auth | django-allauth (email/username + Google OAuth) |
| Async / PDF | Celery · Redis · django-celery-results · Playwright |
| Payments | Fawaterk gateway + Gemini Vision receipt verification |
| Blog | django-ckeditor-5 · python-slugify (Arabic transliteration) |
| Frontend | Server-rendered Django templates · vanilla CSS/JS · `@splidejs` |
| Infra | WhiteNoise · Gunicorn · Nginx · systemd · certbot (Ubuntu VPS) |

---

## 🚀 Getting Started

### Prerequisites

- Python **3.13+**
- pip + virtualenv (or venv)
- Redis (only needed for the async PDF worker — see below)

### 1. Clone & install

```bash
git clone https://github.com/Ahmed-Mana3/skillifly.git
cd skillifly

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Required for PDF export only
playwright install chromium
```

### 2. Configure environment

Copy the example environment file and fill in real values:

```bash
cp .env.example .env
```

Key variables (see `.env.example` for the full list):

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required in production. Generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_DEBUG` | `True` in dev, `False` in production |
| `DATABASE_URL` | Leave empty for SQLite; set `postgres://…` to use PostgreSQL |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google sign-in (see below) |
| `FAWATERK_*` | Fawaterk gateway credentials |
| `GEMINI_API_KEY` | Gemini Vision key for receipt verification |
| `CELERY_BROKER_URL` | Redis connection string |
| `SKILLIFLY_COUPON_CODE` | Optional coupon that bypasses payment (useful for staging) |

### 3. Migrate & run

```bash
python manage.py migrate
python manage.py runserver
```

> **Dev host:** access the site at `http://lvh.me:8000` (not `localhost`).
> Sessions/CSRF cookies are scoped to `.lvh.me` so they work across
> subdomains (e.g. `blog.lvh.me`); a middleware auto-redirects
> `localhost` → `lvh.me` in DEBUG mode.

### 4. Seed a portfolio for testing (optional)

Theme previews render a ready-made mock portfolio:

```
/preview/<theme_name>      e.g. /preview/creative
```

The demo user (`alex_mercer`) is created automatically on first visit.

---

## 🗂 Project Structure

```
skillifly/
├── skillifly/              # Django project package
│   ├── settings.py         # env-driven settings
│   ├── urls.py             # root URLConf (portfolios catch-all is LAST)
│   ├── blog_urls.py        # URLConf for the blog.* subdomain
│   ├── celery.py           # Celery app
│   └── wsgi.py / asgi.py
├── core/                   # All models live here (zero-migration strategy)
│   ├── models.py           # User, Profile, Project, Theme, Payments, Analytics…
│   ├── middleware.py       # Custom domains, language routing, CSRF origins…
│   ├── views.py            # Landing, auth, dashboard, admin, PDF views
│   ├── tasks.py            # Celery task: generate_portfolio_pdf
│   └── management/         # e.g. provision_ssl
├── portfolios/             # Public portfolio rendering + theme preview
├── builder/                # Logged-in portfolio editor (formsets + AJAX)
├── payments/               # Pricing, Fawaterk, manual + Gemini verification
├── blog/                   # Blog app (posts, categories, tags, sitemaps)
├── analytics/              # Visitor/event tracking + 30-day dashboard
├── templates/              # Server-rendered templates (EN + /ar/ twins)
├── static/                 # CSS/JS, service worker, images
├── media/                  # User uploads (not committed)
├── staticfiles/            # collectstatic output (not committed)
├── logs/                   # Runtime logs (not committed)
└── manage.py
```

### Django apps

| App | Responsibility |
|---|---|
| `core` | Models, landing pages, auth views, dashboard, themes, SEO, custom domains, admin dashboard, affiliate system, PDF export |
| `portfolios` | Public portfolio rendering, reels/long-video/category pages, examples gallery, `/preview/<theme>/` |
| `builder` | Formset-based portfolio editor + AJAX category save/delete |
| `payments` | Pricing page, Fawaterk checkout/webhook, manual payments + Gemini verification, coupons, banner |
| `blog` | Post/Category/Tag models, sitemaps, dashboard CRUD under `manage/blog/` |
| `analytics` | Tracking endpoint + analytics dashboard (30-day view) |

---

## 🧠 Architecture Highlights

### Theme system

A portfolio's theme maps to a template by convention:

```
templates/portfolios/<category>/<category>_<theme_name>.html
# e.g. templates/portfolios/video_editor/video_editor_creative.html
```

The fallback is `portfolios/developer/developer_minimal.html`. Each theme ships
variants for reels (`_reels`), long videos (`_long`), detail (`_detail`) and
category pages. Adding a theme = add templates + a `Theme`/`Category` DB record
(see `scratch_add_*_theme.py` for the pattern).

### Localization (English / Arabic RTL)

Nearly every page has an `/ar/...` twin. `LanguagePreferenceMiddleware` persists
the choice in a `skillifly_lang` cookie and redirects between branches using the
`ROUTE_MAP` in `core/middleware.py`. Arabic templates set `is_arabic_page` and
use `dir="rtl"`.

### Custom domains

`CustomDomainMiddleware` rewrites `path_info` so any registered custom domain
serves its owner's portfolio (routing works even before verification; `is_active`
only gates SSL/canonical display). Verified domains are injected into
`CSRF_TRUSTED_ORIGINS` dynamically. See `python manage.py provision_ssl`.

### Payments & the PDF export flow

- Plans are defined in `payments/views.py` (`PLAN_CATALOGUE`): Monthly 50 EGP/30d,
  6-Month 250 EGP/180d, Annual 360 EGP/365d.
- `UserPayment.is_active` == `status='paid'` and still within the plan's day window.
- Portfolio visibility auto-flips to private when the last payment expires.
- PDF export is restricted to active **annual** subscribers and runs as a Celery
  task (`core/tasks.py`), cached by a `source_hash` so unchanged portfolios reuse
  the generated file.

---

## 📦 PDF Export (Celery + Redis)

Export runs as a background job so requests stay fast.

```bash
# 1. Start Redis (example with Docker)
docker run -p 6379:6379 redis

# 2. Start the Celery worker
celery -A skillifly worker -l info

# 3. Run the server
python manage.py runserver
```

In development, `CELERY_TASK_ALWAYS_EAGER` defaults to `True`, so tasks run
synchronously without a worker. Set it to `False` in production and run a real
worker (see `README_PROD.md`).

---

## 🔐 Sign in with Google (OAuth)

`django-allauth` powers Google sign-in.

1. Create OAuth credentials in the [Google Cloud Console](https://console.cloud.google.com):
   - OAuth consent screen → **External**
   - Credentials → **OAuth client ID** → *Web application*
   - Authorized JS origins: `http://lvh.me:8000` (dev) / `https://skillifly.cloud` (prod)
   - Authorized redirect URI: `http://lvh.me:8000/accounts/google/login/callback/`
2. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`.
3. Make sure the Django Site domain matches your host:

```bash
python manage.py shell -c "from django.contrib.sites.models import Site; s=Site.objects.get(id=1); s.domain='lvh.me:8000'; s.name='Localhost'; s.save()"
```

Then use **Continue with Google** on the sign-in/sign-up pages.

---

## 🧪 Testing

```bash
python manage.py test          # runs tests for core, blog, builder, payments, analytics
```

No lint/typecheck config is present in the repo; use `manage.py test` to verify changes.

---

## ☁️ Deployment

The full production walkthrough (Ubuntu VPS, Gunicorn, Nginx, systemd, SQLite
permissions, certbot SSL, Celery worker) lives in
**[README_PROD.md](README_PROD.md)**.

Quick reminder: never commit `.env`, `db.sqlite3`, `media/`, `staticfiles/`, or
`logs/` (all in `.gitignore`).

---

## ⚖️ License

**Proprietary.** Copyright © 2026 Ahmed Medhat Mannaa. All rights reserved.
See [LICENSE](LICENSE) for details — this software may not be used, copied,
modified, or distributed without explicit written permission.
