from django.contrib import admin
from core.models import (
    CustomUser, Category, Theme, Profile, PersonalInfo, 
    Experience, Education, Skill, Project, Link, 
    Subscription, UserPayment, DiscountCode, SiteSettings, 
    Review, Showcase, SEOSettings, CustomDomain
)

# Register your models here.
admin.site.register(CustomUser)
admin.site.register(Category)
admin.site.register(Theme)
admin.site.register(Profile)
admin.site.register(PersonalInfo)
admin.site.register(Experience)
admin.site.register(Education)
admin.site.register(Skill)
admin.site.register(Project)
admin.site.register(Link)
admin.site.register(Subscription)
admin.site.register(UserPayment)
admin.site.register(DiscountCode)
admin.site.register(SiteSettings)
admin.site.register(SEOSettings)

@admin.register(CustomDomain)
class CustomDomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'user', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('domain', 'user__username')
    actions = ['activate_domains', 'deactivate_domains']

    def activate_domains(self, request, queryset):
        queryset.update(is_active=True)
    activate_domains.short_description = "Mark selected domains as Active"

    def deactivate_domains(self, request, queryset):
        queryset.update(is_active=False)
    deactivate_domains.short_description = "Mark selected domains as Inactive"

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('user_name', 'user_title', 'rating', 'is_featured', 'created_at')
    list_filter = ('is_featured', 'rating')
    search_fields = ('user_name', 'content')

from django.utils.html import format_html

@admin.register(Showcase)
class ShowcaseAdmin(admin.ModelAdmin):
    change_form_template = 'admin/core/showcase/change_form.html'
    list_display = ('image_preview', 'profile', 'title', 'order', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('profile__user__username', 'title', 'description')
    ordering = ('order', '-created_at')

    def image_preview(self, obj):
        if obj.preview_image:
            return format_html('<img src="{}" style="width: 80px; height: 50px; object-fit: cover; border-radius: 4px; border: 1px solid #ddd;" />', obj.preview_image.url)
        return "No Image"
    image_preview.short_description = 'Preview'
