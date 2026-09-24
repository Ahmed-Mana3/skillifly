from django.contrib import admin
from core.models import (
    CustomUser, UserAccount, Category, Theme, Profile, PersonalInfo, 
    Experience, Education, Skill, Project, Link, 
    Subscription, UserPayment, DiscountCode, SiteSettings, 
    Review, ClientReview, Showcase, SEOSettings, CustomDomain, ManualPayment,
    PaymentTrackingEvent,
)

# Register your models here.
admin.site.register(CustomUser)
admin.site.register(UserAccount)
admin.site.register(Category)
admin.site.register(Theme)
admin.site.register(Profile)
admin.site.register(PersonalInfo)

@admin.register(Experience)
class ExperienceAdmin(admin.ModelAdmin):
    list_display = ('title', 'company', 'user', 'order', 'start_date', 'still_working')
    list_editable = ('order',)
    list_filter = ('still_working', 'user')
    search_fields = ('title', 'company', 'user__username', 'user__email')
    ordering = ('user', 'order', '-start_date')

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
    list_display = ('user_name', 'user_title', 'rating', 'is_featured', 'order', 'created_at')
    list_editable = ('order', 'is_featured')
    list_filter = ('is_featured', 'rating')
    search_fields = ('user_name', 'content')

@admin.register(ClientReview)
class ClientReviewAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_name', 'rating', 'is_featured', 'order', 'created_at')
    list_editable = ('order', 'is_featured')
    list_filter = ('is_featured', 'rating')
    search_fields = ('user__username', 'user_name', 'content')
    raw_id_fields = ('user', 'reviewer')

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


@admin.register(ManualPayment)
class ManualPaymentAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan_type', 'amount_expected', 'payment_method', 'status', 'created_at')
    list_filter = ('status', 'payment_method', 'plan_type')
    search_fields = ('user__username', 'sender_identifier')
    readonly_fields = ('created_at',)


@admin.register(PaymentTrackingEvent)
class PaymentTrackingEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'page', 'action', 'plan_type', 'user', 'session_id', 'created_at')
    list_filter = ('event_type', 'page', 'plan_type')
    search_fields = ('user__username', 'user__email', 'session_id', 'action', 'ip_address')
    readonly_fields = ('created_at', 'session_id', 'ip_address', 'user_agent')
    ordering = ('-created_at',)

