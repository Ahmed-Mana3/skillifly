from django.conf import settings
from django.shortcuts import redirect
from .models import CustomDomain


class CustomDomainMiddleware:
    """
    Routes requests arriving on a custom domain to the correct user's
    portfolio by rewriting ``request.path_info``.

    Only portfolio-related paths are rewritten.  System paths like
    ``/static/``, ``/media/``, ``/api/``, ``/admin/`` etc. are left
    untouched so that Nginx (or WhiteNoise) can serve them normally.
    """

    # Paths that must NEVER be rewritten — they are served by Nginx or
    # handled by Django system views regardless of the Host header.
    SKIP_PREFIXES = (
        '/static/',
        '/media/',
        '/api/',
        '/admin/',
        '/accounts/',
        '/dashboard/',
        '/builder/',
        '/payment/',
        '/pay/',
        '/manual-pay/',
        '/webhook/',
        '/export/',
        '/signup/',
        '/signin/',
        '/logout/',
        '/toggle-visibility/',
        '/sitemap.xml',
        '/robots.txt',
        '/sw.js',
        '/favicon.ico',
        '/terms/',
        '/privacy/',
        '/contact/',
        '/themes/',
        '/examples/',
        '/update_portfolio/',
        '/submit-review-exclusive/',
        '/manage/',
        '/user-activity/',
    )

    MAIN_DOMAINS = frozenset([
        'skillifly.cloud',
        'www.skillifly.cloud',
        'blog.skillifly.cloud',
        'localhost',
        'blog.localhost',
        'lvh.me',
        'blog.lvh.me',
        '127.0.0.1',
        'testserver',
    ])

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()

        if host not in self.MAIN_DOMAINS:
            try:
                # Route any known custom domain — verified or not — to the
                # correct user's portfolio.  The is_active flag is used only
                # for SSL provisioning / canonical URL display; it should NOT
                # block routing, otherwise an unverified domain shows the
                # Skillifly homepage instead of the user's portfolio.
                cd = CustomDomain.objects.select_related('user').get(
                    domain=host,
                )
            except CustomDomain.DoesNotExist:
                # Completely unknown host — let Django handle it normally (may 404)
                return self.get_response(request)
            except Exception:
                return self.get_response(request)

            # Attach the custom-domain owner to the request so views/
            # templates can use it (e.g. for canonical URL generation).
            request.custom_domain_user = cd.user
            username = cd.user.username
            path = request.path_info

            # Skip system paths — they work the same on every domain.
            if not path.startswith(self.SKIP_PREFIXES):
                # Rewrite:  /           → /@username/
                #           /reels/     → /@username/reels/
                #           /long-videos/  → /@username/long-videos/
                if not path.startswith(f'/{username}') and not path.startswith(f'/@{username}'):
                    request.path_info = f'/{username}{path}'

        return self.get_response(request)


class DynamicCsrfTrustedOriginsMiddleware:
    """
    Dynamically adds active custom domains to Django's
    ``CSRF_TRUSTED_ORIGINS`` so that form POSTs (and AJAX with CSRF
    tokens) from custom domains are not rejected with 403 Forbidden.

    Must be placed in MIDDLEWARE **before** Django's CsrfViewMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        # Build the set of custom-domain origins on every request.
        # The DB query is lightweight (SELECT domain FROM … WHERE is_active)
        # and can be cached later if traffic demands it.
        try:
            active_domains = CustomDomain.objects.filter(
                is_active=True,
            ).values_list('domain', flat=True)

            extra_origins = []
            for d in active_domains:
                extra_origins.append(f'https://{d}')
                extra_origins.append(f'http://{d}')

            # Only add origins that aren't already present
            existing = set(settings.CSRF_TRUSTED_ORIGINS)
            for origin in extra_origins:
                if origin not in existing:
                    settings.CSRF_TRUSTED_ORIGINS.append(origin)
        except Exception:
            # Never break the request pipeline over this
            pass


        return self.get_response(request)


class UpdateLastSeenMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            from .models import Profile
            from django.utils import timezone
            # Update last_seen timestamp
            Profile.objects.filter(user=request.user).update(last_seen=timezone.now())
        
        response = self.get_response(request)
        return response


class SubdomainRoutingMiddleware:
    """
    Routes requests arriving on the blog subdomain to the blog_urls configuration.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()

        if host in ('blog.skillifly.cloud', 'blog.localhost', 'blog.lvh.me'):
            request.urlconf = 'skillifly.blog_urls'

        return self.get_response(request)


class LocalhostRedirectMiddleware:
    """
    In local development (DEBUG=True), redirect requests on 'localhost' or '127.0.0.1'
    to 'lvh.me' so that session/CSRF cookies (which are configured for '.lvh.me' to
    support subdomains) are correctly set by the browser.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEBUG:
            host_port = request.get_host()
            host = host_port.split(':')[0].lower()
            if host in ('localhost', '127.0.0.1'):
                # Replace host with lvh.me, keeping the port if present
                new_host_port = host_port.replace(host, 'lvh.me')
                # Reconstruct absolute URI
                scheme = 'https' if request.is_secure() else 'http'
                new_url = f"{scheme}://{new_host_port}{request.get_full_path()}"
                return redirect(new_url)
        return self.get_response(request)
