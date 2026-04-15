"""
Django settings for skillifly project.

Environment variables are loaded from a .env file (python-dotenv).
Copy .env.example to .env and fill in real values before deployment.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file if it exists (ignored in production where env vars are set
# at the OS/systemd level).
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

# SECURITY WARNING: keep the secret key used in production secret!
# Required in production. Falls back to an insecure placeholder for local dev ONLY.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    _debug_check = _env_bool("DJANGO_DEBUG", default=True)
    if not _debug_check:
        raise RuntimeError(
            "DJANGO_SECRET_KEY environment variable is not set. "
            "This is required when DJANGO_DEBUG=False (production)."
        )
    # Local dev fallback — never use this in production.
    SECRET_KEY = "dev-insecure-placeholder-change-me"  # noqa: S105

# SECURITY WARNING: don't run with debug turned on in production!
# Set DJANGO_DEBUG=False in your .env (or environment) for production.
DEBUG = _env_bool("DJANGO_DEBUG", default=True)

# Comma-separated list of hosts/domains your site can serve.
# Example: DJANGO_ALLOWED_HOSTS=skillifly.cloud,www.skillifly.cloud
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if h.strip()
]

# In development, allow localhost automatically so devs don't need to configure it.
if DEBUG and not ALLOWED_HOSTS:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0","skillifly.cloud","www.skillifly.cloud","156.67.217.227"]  # noqa: S104

SITE_ID = int(os.environ.get("DJANGO_SITE_ID", "1"))

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'django_celery_results',
    'core',
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise: serve static files efficiently without a separate web server step.
    # Must come right after SecurityMiddleware.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'allauth.account.middleware.AccountMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'skillifly.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.auth_providers',
            ],
        },
    },
]

WSGI_APPLICATION = 'skillifly.wsgi.application'

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Production: set DATABASE_URL=postgres://user:password@host:5432/dbname
# Development: falls back to SQLite automatically.

_db_url = os.environ.get("DATABASE_URL", "")

if _db_url:
    # Parse a postgres://user:pass@host:port/dbname URI
    import urllib.parse as _urlparse
    _parsed = _urlparse.urlparse(_db_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _parsed.path.lstrip("/"),
            "USER": _parsed.username or "",
            "PASSWORD": _parsed.password or "",
            "HOST": _parsed.hostname or "localhost",
            "PORT": str(_parsed.port or 5432),
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
        }
    }
else:
    # SQLite fallback for local development — do NOT use in production.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# ---------------------------------------------------------------------------
# Password Validation
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & Media Files
# ---------------------------------------------------------------------------

# URL prefix for static files served by the web server / WhiteNoise.
STATIC_URL = '/static/'

# Absolute path where `collectstatic` writes files.
# On the VPS: sudo mkdir -p /var/www/skillifly/staticfiles && chown www-data
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Additional directories to search for static files (dev source).
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# WhiteNoise compressed manifest storage for production fingerprinting.
STATICFILES_STORAGE = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage"
    if not DEBUG
    else "django.contrib.staticfiles.storage.StaticFilesStorage"
)

# User-uploaded files — served by Nginx in production.
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


# ---------------------------------------------------------------------------
# Upload Limits (Increased for high-res portfolio media)
# ---------------------------------------------------------------------------
# Standardizes limit at 100MB for all environments.
DATA_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100 MB

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

AUTH_USER_MODEL = 'core.CustomUser'

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = 'signin'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'signin'

# allauth settings
ACCOUNT_LOGIN_METHODS = {"username", "email"}
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGIN_ON_GET = True
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_ADAPTER = "core.adapters.SkilliflySocialAccountAdapter"

# Google OAuth2 — credentials come exclusively from environment variables.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "APP": {
                "client_id": GOOGLE_CLIENT_ID,
                "secret": GOOGLE_CLIENT_SECRET,
                "key": "",
            },
            "SCOPE": ["profile", "email"],
            "AUTH_PARAMS": {"access_type": "online"},
        }
    }

# ---------------------------------------------------------------------------
# Payment — Kashier
# ---------------------------------------------------------------------------
# All Kashier credentials MUST come from environment variables.
# Never commit real keys to git.

KASHIER_MERCHANT_ID = os.environ.get("KASHIER_MERCHANT_ID", "")
KASHIER_API_KEY = os.environ.get("KASHIER_API_KEY", "")
KASHIER_WEBHOOK_SECRET = os.environ.get("KASHIER_WEBHOOK_SECRET", "")
# 'test' uses test-api.kashier.io; 'live' uses api.kashier.io
KASHIER_MODE = os.environ.get("KASHIER_MODE", "test")

# Optional coupon code to bypass payment (e.g. for staging/testing).
# Leave empty to disable.
SKILLIFLY_COUPON_CODE = os.environ.get("SKILLIFLY_COUPON_CODE", "")

# ---------------------------------------------------------------------------
# Celery (async PDF export)
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = "django-db"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

# In development, run tasks synchronously (no worker required).
# In production, set CELERY_TASK_ALWAYS_EAGER=0 and run a Celery worker.
CELERY_TASK_ALWAYS_EAGER = _env_bool("CELERY_TASK_ALWAYS_EAGER", default=DEBUG)

# ---------------------------------------------------------------------------
# Security Hardening (always on, tightened in production)
# ---------------------------------------------------------------------------

# Safe for both dev and prod — no negative side effects.
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "SAMEORIGIN"
SECURE_REFERRER_POLICY = "same-origin"

if not DEBUG:
    # Cookie security — only activate when HTTPS is in use.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = False  # Required for AJAX CSRF reads

    # Trusted origins for CSRF (required when behind a reverse proxy).
    # Example: DJANGO_CSRF_TRUSTED_ORIGINS=https://skillifly.cloud,https://www.skillifly.cloud
    CSRF_TRUSTED_ORIGINS = [
        o.strip()
        for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
        if o.strip()
    ]

    # Required when behind a reverse proxy (Nginx) to detect HTTPS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    # HTTP Strict Transport Security — enable only after HTTPS is confirmed working.
    # Set DJANGO_SECURE_HSTS=True in .env to activate.
    if _env_bool("DJANGO_SECURE_HSTS", default=False):
        SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
        SECURE_HSTS_INCLUDE_SUBDOMAINS = _env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
        SECURE_HSTS_PRELOAD = _env_bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
        SECURE_SSL_REDIRECT = True


# ---------------------------------------------------------------------------
# Email Configuration (SMTP)
# ---------------------------------------------------------------------------
# In production, uses SMTP. In development (DEBUG=True), logs to console.

if DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", default=True)
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "Skillifly <noreply@skillifly.cloud>")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Writes INFO+ to stdout (captured by systemd/journald on the VPS)
# and WARNING+ to a rotating file for persistence.
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {message}",
            "style": "{",
        },
    },
    "filters": {
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "level": "WARNING",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOGS_DIR, "django.log"),
            "maxBytes": 1024 * 1024 * 5,  # 5 MB
            "backupCount": 5,
            "formatter": "verbose",
            "filters": ["require_debug_false"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file"],
            "level": "ERROR",
            "propagate": False,
        },
        "core": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
