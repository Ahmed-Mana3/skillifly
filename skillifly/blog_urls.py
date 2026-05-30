from django.urls import path, include
from django.contrib.sitemaps.views import sitemap
from django.http import HttpResponse
from blog.sitemaps import PostSitemap, CategorySitemap, TagSitemap
from .urls import urlpatterns as core_urlpatterns

sitemaps = {
    'posts': PostSitemap,
    'categories': CategorySitemap,
    'tags': TagSitemap,
}


def blog_robots_txt(request):
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /media/uploads/\n\n"
        "Sitemap: https://blog.skillifly.cloud/sitemap.xml\n"
    )
    return HttpResponse(content, content_type='text/plain')


urlpatterns = [
    path('', include('blog.urls')),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='blog_sitemap'),
    path('robots.txt', blog_robots_txt, name='blog_robots_txt'),
] + core_urlpatterns
