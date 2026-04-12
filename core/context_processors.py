from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def auth_providers(request):
    google_id = getattr(settings, "GOOGLE_CLIENT_ID", "")
    google_secret = getattr(settings, "GOOGLE_CLIENT_SECRET", "")

    # Treat empty or placeholder values as unconfigured
    placeholders = {"YOUR_CLIENT_ID", "YOUR_CLIENT_SECRET", "change-me", ""}
    google_configured = (
        bool(google_id and google_secret) and
        google_id not in placeholders and
        google_secret not in placeholders
    )

    # Also consider database SocialApp configuration, if used.
    try:
        from allauth.socialaccount.models import SocialApp

        google_configured = google_configured or SocialApp.objects.filter(provider="google").exists()
    except Exception:
        # If allauth isn't installed/ready for any reason, just treat as not configured.
        pass

    return {
        # Show a UI button in DEBUG for testing, but only generate a real login URL when configured.
        "google_oauth_configured": google_configured,
        "google_oauth_button_visible": False, # Forced to False as per user request
    }

