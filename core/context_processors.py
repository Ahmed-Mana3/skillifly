from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import json


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
        "google_oauth_button_visible": google_configured,
    }


def navbar_profile(request):
    """Provide the user's profile picture and initials for the navbar."""
    if not request.user.is_authenticated:
        return {}

    from core.models import Profile

    nav_picture = None
    nav_initials = ''
    nav_account_type = 'editor'

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

    user_account = getattr(user, 'user_account', None)
    if user_account and user_account.account_type in ('editor', 'client'):
        nav_account_type = user_account.account_type

    return {
        'nav_profile_picture': nav_picture,
        'nav_user_initials': nav_initials,
        'nav_account_type': nav_account_type,
        'nav_is_client': nav_account_type == 'client',
    }

def site_globals(request):
    """Provide the main site URL for cross-subdomain linking."""
    host = request.get_host()
    # If we are on the blog, links should go to main site
    if host.startswith('blog.'):
        main_host = host.replace('blog.', '', 1)
        main_site_url = f"{request.scheme}://{main_host}"
    else:
        main_site_url = ''

    # Arabic detection: /ar/ paths, or a `next` target pointing at /ar/, or a
    # password-reset flow started from an Arabic page (see the adapter below).
    path = request.path_info
    next_target = request.GET.get('next') or request.POST.get('next') or ''
    is_arabic_page = path.startswith('/ar/') or next_target.startswith('/ar/')

    # Social (Google) signup initiated from an Arabic page: the pending social
    # login state carries an Arabic `next`, so render the 3rd-party signup
    # form in Arabic as well.
    if not is_arabic_page and path.startswith('/accounts/3rdparty/signup/'):
        pending = request.session.get('socialaccount_sociallogin')
        if pending:
            try:
                from allauth.socialaccount.models import SocialLogin
                state_next = SocialLogin.deserialize(pending).state.get('next', '')
                if state_next.startswith('/ar/'):
                    is_arabic_page = True
            except Exception:
                pass

    reset_flow = request.session.get('is_arabic_reset_flow', False)
    if reset_flow:
        is_arabic_page = True
        # Drop the flag once the user leaves the /accounts/ reset flow so it
        # cannot leak into later English pages.
        if not path.startswith('/accounts/') and not path.startswith('/ar/'):
            request.session.pop('is_arabic_reset_flow', None)
    else:
        # The reset form is shown in Arabic (via ?next=/ar/...). Remember that
        # for the whole flow so the done page and the reset email stay Arabic
        # after the form POSTs (allauth's success redirect doesn't keep `next`).
        if is_arabic_page and path.startswith('/accounts/password/reset/'):
            request.session['is_arabic_reset_flow'] = True

    from .middleware import LanguagePreferenceMiddleware
    route_map = dict(LanguagePreferenceMiddleware.ROUTE_MAP)

    return {
        'MAIN_SITE_URL': main_site_url,
        'is_arabic_page': is_arabic_page,
        'lang_route_map': json.dumps(route_map),
    }
