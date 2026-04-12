# skillifly
skillifly is the first portfolio builder that helps you to get a public portfolio you can share with your clients. 

## PDF export (1-year subscribers)

This backend includes a **Portfolio → PDF export** feature that:
- runs **as a background job** (Celery) to avoid slowing down web requests
- is available **only for active 1-year subscribers** (subscription days \(>= 365\))
- caches exports based on portfolio content (reuses existing PDFs when nothing changed)

### Local setup

Install dependencies:

```bash
pip install -r requirements.txt
playwright install chromium
```

Run migrations (includes `django_celery_results` and `PdfExportJob`):

```bash
python manage.py migrate
```

Start Redis (example using Docker):

```bash
docker run -p 6379:6379 redis
```

Start the Celery worker:

```bash
celery -A skillifly worker -l info
```

Run the server:

```bash
python manage.py runserver
```

## Sign in with Google (OAuth)

This project supports **Google sign-in** via `django-allauth`.

### Setup (local)

1) Create OAuth credentials in Google Cloud Console:
- OAuth consent screen (External)
- OAuth Client ID (Web application)
- Authorized JavaScript origins: `http://127.0.0.1:8000`
- Authorized redirect URI: `http://127.0.0.1:8000/accounts/google/login/callback/`

2) Set environment variables (see `.env.example`):
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

3) Ensure the Django Site domain matches your dev host (default is `example.com`):

```bash
python manage.py shell -c "from django.contrib.sites.models import Site; s=Site.objects.get(id=1); s.domain='127.0.0.1:8000'; s.name='Localhost'; s.save(); print(s.domain)"
```

Then use **Continue with Google** on the sign-in/sign-up pages.
