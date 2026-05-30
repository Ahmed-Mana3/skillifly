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


def navbar_profile(request):
    """Provide the user's profile picture and initials for the navbar."""
    if not request.user.is_authenticated:
        return {}

    from core.models import Profile

    nav_picture = None
    nav_initials = ''

    try:
        profile = request.user.profile
        if profile.picture and hasattr(profile.picture, 'url'):
            nav_picture = profile.picture.url
    except Profile.DoesNotExist:
        pass

    user = request.user
    if user.first_name and user.last_name:
        nav_initials = (user.first_name[0] + user.last_name[0]).upper()
    elif user.first_name:
        nav_initials = user.first_name[:2].upper()
    else:
        nav_initials = user.username[:2].upper()

    return {
        'nav_profile_picture': nav_picture,
        'nav_user_initials': nav_initials,
    }

def site_globals(request):
    """Provide the main site URL for cross-subdomain linking."""
    host = request.get_host()
    # If we are on the blog, links should go to main site
    if host.startswith('blog.'):
        main_host = host.replace('blog.', '', 1)
        return {'MAIN_SITE_URL': f"{request.scheme}://{main_host}"}
    return {'MAIN_SITE_URL': ''}

