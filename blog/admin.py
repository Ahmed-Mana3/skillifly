from django.contrib import admin
from .models import Post, Category, Tag


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display  = ('title', 'language', 'status', 'author', 'created_at', 'seo_status')
    list_filter   = ('status', 'language', 'categories', 'created_at')
    search_fields = ('title', 'meta_description', 'content')
    prepopulated_fields = {'slug': ('title',)}
    filter_horizontal   = ('categories', 'tags')
    date_hierarchy  = 'created_at'
    raw_id_fields   = ('author',)

    fieldsets = (
        ('Content', {
            'fields': ('title', 'slug', 'author', 'language', 'status', 'content'),
        }),
        ('Featured Image', {
            'fields': ('featured_image', 'featured_image_alt'),
        }),
        ('SEO', {
            'classes': ('collapse',),
            'fields': ('meta_description', 'canonical_url'),
        }),
        ('Taxonomy', {
            'fields': ('categories', 'tags'),
        }),
    )

    @admin.display(description='SEO', boolean=False)
    def seo_status(self, obj):
        missing = []
        if not obj.meta_description:
            missing.append('meta')
        if not obj.featured_image_alt:
            missing.append('img-alt')
        if missing:
            return f'⚠ Missing: {", ".join(missing)}'
        return '✓ Complete'
