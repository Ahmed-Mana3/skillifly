from django.contrib.sitemaps import Sitemap
from .models import Post, Category, Tag


class PostSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.9
    protocol = 'https'

    def items(self):
        return Post.objects.filter(status='published').order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return f'/{obj.slug}/'


class CategorySitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6
    protocol = 'https'

    def items(self):
        # Only categories that have at least one published post
        return Category.objects.filter(posts__status='published').distinct().order_by('name')

    def location(self, obj):
        return f'/category/{obj.slug}/'


class TagSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.5
    protocol = 'https'

    def items(self):
        # Only tags that have at least one published post
        return Tag.objects.filter(posts__status='published').distinct().order_by('name')

    def location(self, obj):
        return f'/tag/{obj.slug}/'
