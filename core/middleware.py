from .models import CustomDomain

class CustomDomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Get the host without the port
        host = request.get_host().split(':')[0].lower()
        
        # Main domains where we don't apply custom domain logic
        main_domains = ['skillifly.cloud', 'localhost', '127.0.0.1', 'testserver']
        
        if host not in main_domains:
            try:
                # Check if this host matches an active custom domain
                cd = CustomDomain.objects.select_related('user').get(domain=host, is_active=True)
                
                # Store the custom domain info on the request for possible use in views
                request.custom_domain_user = cd.user
                
                # If they are at the root of their custom domain, serve their portfolio
                # We import here to avoid circular imports
                if request.path == '/':
                    from .views import preview_view
                    return preview_view(request, username=cd.user.username)
                
            except CustomDomain.DoesNotExist:
                # Host not recognized as a custom domain
                pass
            except Exception:
                # Safety fallback
                pass

        return self.get_response(request)
