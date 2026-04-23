from datetime import date
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from datetime import timedelta
from .forms import RegisterForm, LoginForm
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from .models import Theme, Category, Profile, PersonalInfo, Experience, Education, Skill, Project, Link, CustomUser, UserPayment
from .forms import (
    PersonalInfoForm,
    SkillFormSet,
    EducationFormSet,
    ExperienceFormSet,
    ProjectFormSet,
    LinkFormSet,
    SkillFormSetUpdate,
    EducationFormSetUpdate,
    ExperienceFormSetUpdate,
    ProjectFormSetUpdate,
    LinkFormSetUpdate,
)


def index(request):
    """Render the home/landing page — redirect authenticated users to dashboard"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    portfolios_count = Profile.objects.count()
    themes_count = Theme.objects.count()
    context = {
        'portfolios_count': portfolios_count,
        'themes_count': themes_count,
    }
    return render(request, 'core/index.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect('themes')
        else:
            message = form.errors
    else:
        form = RegisterForm()
        message = None

    context = {
        'message': message,
        'form': form
    }
    return render(request, 'auth/signup.html', context)


def signin_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect('themes')
        else:
            message = form.errors
    else:
        form = LoginForm()
        message = None

    context = {
        'message': message,
        'form': form
    }
    return render(request, 'auth/signin.html', context)


def logout_view(request):
    logout(request)
    return redirect('signin')


@login_required
def dashboard_view(request):
    """Render the dashboard page"""
    profile, created = Profile.objects.select_related('user', 'theme__category').get_or_create(user=request.user)
    
    # Calculate subscription days left
    payment = UserPayment.objects.filter(user=request.user, status='paid').last()
    days_left = 0
    
    if payment and payment.subscription:
        expiration_date = payment.date + timedelta(days=payment.subscription.days)
        remaining = expiration_date - timezone.now()
        days_left = max(0, remaining.days)
        
    portfolio_url = request.build_absolute_uri(f'/{request.user.username}/')
    
    # Context helpers for template visibility
    is_developer = (profile.theme and profile.theme.category and profile.theme.category.name.lower() == 'developer')
    is_annual_subscriber = payment and payment.subscription and payment.subscription.days >= 365
    has_active_payment = payment is not None and payment.is_active
    # Ensure visibility is synced with subscription status
    if not has_active_payment and profile.is_public:
        profile.is_public = False
        profile.save()

    context = {
        'profile': profile,
        'days_left': days_left,
        'payment': payment,
        'has_active_payment': has_active_payment,
        'portfolio_url': portfolio_url,
        'is_developer': is_developer,
        'is_annual_subscriber': is_annual_subscriber,
    }
    return render(request, 'dashboard/dashboard.html', context)

@login_required
def activate_portfolio(request):
    profile, created = Profile.objects.get_or_create(user=request.user)
    
    # Check if user is trying to make it public
    if not profile.is_public:
        # Check for active subscription
        payment = UserPayment.objects.filter(user=request.user, status='paid').last()
        has_active_subscription = payment and payment.is_active
        
        if not has_active_subscription:
            messages.error(request, "Visibility can only be set to Public for Pro members. Please subscribe to go live.")
            return redirect('payment')
    
    # Toggle visibility
    profile.is_public = not profile.is_public
    profile.save()
    
    return redirect('dashboard')

@login_required
def themes(request):
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect('signin')
            
        theme_id = request.POST.get('theme')
        theme = get_object_or_404(Theme, id=theme_id)
        
        # Ensure profile exists and check if user had a theme already
        profile, created = Profile.objects.get_or_create(user=request.user)
        had_theme = profile.theme is not None
        profile.theme = theme
        profile.save()

        # Update usage count
        theme.use_num += 1
        theme.save()

        # If user has no portfolio data yet, send them to the builder first
        has_data = PersonalInfo.objects.filter(user=request.user).exists()
        if not has_data:
            return redirect('builder')
            
        if had_theme:
            from django.urls import reverse
            preview_url = reverse('preview', kwargs={'username': request.user.username})
            messages.success(request, f'Theme updated successfully! <a href="{preview_url}" class="underline font-bold">Preview Portfolio</a>')
            return redirect('dashboard')
            
        return redirect('preview', username=request.user.username)
    
    themes = Theme.objects.all()
    categories = Category.objects.all()
    return render(request, 'dashboard/themes.html', {'themes': themes, 'categories' : categories})

@login_required
def builder_view(request):
    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST)

        skill_formset = SkillFormSet(request.POST, prefix="skills")
        education_formset = EducationFormSet(request.POST, prefix="education")
        experience_formset = ExperienceFormSet(request.POST, prefix="experience")
        project_formset = ProjectFormSet(request.POST, request.FILES, prefix="projects")
        link_formset = LinkFormSet(request.POST, prefix="links")

        if (
            personal_form.is_valid()
            and skill_formset.is_valid()
            and education_formset.is_valid()
            and experience_formset.is_valid()
            and project_formset.is_valid()
            and link_formset.is_valid()
        ):

            save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset)

            # Set profile to public if user has payment
            payment = UserPayment.objects.filter(user=request.user, status='paid').last()
            if payment and payment.is_active:
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.is_public = True
                profile.save()

            return redirect("preview", username=request.user.username)
        else:
            print("--- BUILDER VALIDATION ERRORS ---")
            print(f"Personal Form Errors: {personal_form.errors}")
            print(f"Skill Errors: {skill_formset.errors}")
            print(f"Education Errors: {education_formset.errors}")
            print(f"Experience Errors: {experience_formset.errors}")
            print(f"Project Errors: {project_formset.errors}")
            print(f"Link Errors: {link_formset.errors}")
            from django.contrib import messages
            messages.error(request, "Please correct the highlighted errors in your portfolio.")

    else:
 
        personal_form = PersonalInfoForm()

        skill_formset = SkillFormSet(prefix="skills")
        education_formset = EducationFormSet(prefix="education")
        experience_formset = ExperienceFormSet(prefix="experience")
        project_formset = ProjectFormSet(prefix="projects")
        link_formset = LinkFormSet(prefix="links")

    profile = getattr(request.user, 'profile', None)
    context = {
        "personal_form": personal_form,
        "skill_formset": skill_formset,
        "education_formset": education_formset,
        "experience_formset": experience_formset,
        "project_formset": project_formset,
        "link_formset": link_formset,
        "category": profile.theme.category.name.lower() if profile and profile.theme and profile.theme.category else "theme",
        "theme_name": profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default",
        "show_project_images": (f"{profile.theme.category.name.lower()}_{profile.theme.name.lower()}".replace(" ", "_") not in ['video_editor_reels', 'video_editor_creative_reels', 'developer_creative']) if profile and profile.theme and profile.theme.category else True
    }
    template_name = 'dashboard/builder.html'
    if profile and profile.theme:
        category = profile.theme.category.name.lower().replace(" ", "_") if profile.theme.category else "theme"
        theme_name = profile.theme.name.lower().replace(" ", "_")
        specific_template = f"portfolios/{category}/builder_{category}_{theme_name}.html"
        from django.template.loader import get_template
        from django.template import TemplateDoesNotExist
        try:
            get_template(specific_template)
            template_name = specific_template
        except TemplateDoesNotExist:
            pass

    return render(request, template_name, context)


@login_required
def update_portfolio_view(request):
    user = request.user
    
    # helper for existing data
    personal_info = PersonalInfo.objects.filter(user=user).first()
    
    if request.method == "POST":
        personal_form = PersonalInfoForm(request.POST) # Start with POST data
        
        skill_formset = SkillFormSetUpdate(request.POST, prefix="skills")
        education_formset = EducationFormSetUpdate(request.POST, prefix="education")
        experience_formset = ExperienceFormSetUpdate(request.POST, prefix="experience")
        project_formset = ProjectFormSetUpdate(request.POST, request.FILES, prefix="projects")
        link_formset = LinkFormSetUpdate(request.POST, prefix="links")

        if (
            personal_form.is_valid()
            and skill_formset.is_valid()
            and education_formset.is_valid()
            and experience_formset.is_valid()
            and project_formset.is_valid()
            and link_formset.is_valid()
        ):
            save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset)
            # Set profile to public if user has active payment
            payment = UserPayment.objects.filter(user=request.user, status='paid').last()
            if payment and payment.is_active:
                profile = Profile.objects.filter(user=user).first()
                if profile:
                    profile.is_public = True
                    profile.save()

            return redirect("dashboard")
        else:
            print("--- UPDATE PORTFOLIO VALIDATION ERRORS ---")
            print(f"Personal Form Errors: {personal_form.errors}")
            print(f"Skill Errors: {skill_formset.errors}")
            print(f"Education Errors: {education_formset.errors}")
            print(f"Experience Errors: {experience_formset.errors}")
            print(f"Project Errors: {project_formset.errors}")
            print(f"Link Errors: {link_formset.errors}")
            from django.contrib import messages
            messages.error(request, "Could not save changes. Please check the form for errors.")
    
    else:
        # Pre-fill forms with existing data
        
        # Personal Info
        initial_personal = {}
        if personal_info:
            initial_personal = {
                'fullname': personal_info.full_name,
                'title': personal_info.title,
                'email': personal_info.email,
                'phone': personal_info.phone,
                'bio': personal_info.bio,
                'booking_url': personal_info.booking_url,
            }
        personal_form = PersonalInfoForm(initial=initial_personal)

        # Skills
        skills_data = [{'skill': s.name} for s in Skill.objects.filter(user=user)]
        skill_formset = SkillFormSetUpdate(initial=skills_data, prefix="skills")
        
        # Education
        education_data = [{
            'school': e.school,
            'degree': e.degree,
            'field': e.field,
            'year': e.grade_year.year
        } for e in Education.objects.filter(user=user)]
        education_formset = EducationFormSetUpdate(initial=education_data, prefix="education")

        # Experience
        experience_data = []
        for e in Experience.objects.filter(user=user):
            start_str = e.start_date.strftime('%Y-%m') if e.start_date else ''
            end_str = e.end_date.strftime('%Y-%m') if e.end_date else ''
            experience_data.append({
                'title': e.title,
                'company': e.company,
                'start': start_str,
                'end': end_str,
                'description': e.details
            })
        experience_formset = ExperienceFormSetUpdate(initial=experience_data, prefix="experience")

        # Projects
        project_data = [{
            'name': p.title,
            'url': p.url,
            'description': p.details,
            'video_type': p.video_type,
            'thumbnail': p.image
        } for p in Project.objects.filter(user=user)]
        project_formset = ProjectFormSetUpdate(initial=project_data, prefix="projects")

        # Links
        link_data = [{
            'name': l.platform,
            'url': l.url
        } for l in Link.objects.filter(user=user)]
        link_formset = LinkFormSetUpdate(initial=link_data, prefix="links")

    profile = getattr(request.user, 'profile', None)
    context = {
        "personal_form": personal_form,
        "skill_formset": skill_formset,
        "education_formset": education_formset,
        "experience_formset": experience_formset,
        "project_formset": project_formset,
        "link_formset": link_formset,
        "is_update": True,
        "category": profile.theme.category.name.lower() if profile and profile.theme and profile.theme.category else "theme",
        "theme_name": profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default",
        "show_project_images": (f"{profile.theme.category.name.lower()}_{profile.theme.name.lower()}".replace(" ", "_") not in ['video_editor_reels', 'video_editor_creative_reels', 'developer_creative']) if profile and profile.theme and profile.theme.category else True
    }
    template_name = 'dashboard/builder.html'
    if profile and profile.theme:
        category = profile.theme.category.name.lower().replace(" ", "_") if profile.theme.category else "theme"
        theme_name = profile.theme.name.lower().replace(" ", "_")
        specific_template = f"portfolios/{category}/builder_{category}_{theme_name}.html"
        from django.template.loader import get_template
        from django.template import TemplateDoesNotExist
        try:
            get_template(specific_template)
            template_name = specific_template
        except TemplateDoesNotExist:
            pass

    return render(request, template_name, context)


def save_portfolio_data(request, personal_form, skill_formset, education_formset, experience_formset, project_formset, link_formset):
            personal_data = personal_form.cleaned_data

            skills = [
                f.cleaned_data["skill"]
                for f in skill_formset
                if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
            ]

            education = [
                f.cleaned_data
                for f in education_formset
                if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
            ]

            experience = [
                f.cleaned_data
                for f in experience_formset
                if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
            ]

            projects = [
                f.cleaned_data
                for f in project_formset
                if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
            ]

            links = [
                f.cleaned_data
                for f in link_formset
                if f.cleaned_data and not f.cleaned_data.get("DELETE", False)
            ]

            personal_info, created = PersonalInfo.objects.update_or_create(
                user=request.user,
                defaults={
                    "full_name": personal_data["fullname"],
                    "title": personal_data["title"],
                    "email": personal_data["email"],
                    "phone": personal_data["phone"],
                    "bio": personal_data["bio"],
                    "booking_url": personal_data.get("booking_url"),
                },
            )

            Skill.objects.filter(user=request.user).delete()
            for skill_name in skills:
                Skill.objects.create(user=request.user, name=skill_name)

            Education.objects.filter(user=request.user).delete()
            for edu_data in education:
                Education.objects.create(
                    user=request.user,
                    school=edu_data["school"],
                    degree=edu_data["degree"],
                    field=edu_data["field"],
                    grade_year=date(edu_data["year"], 1, 1),  
                )

            Experience.objects.filter(user=request.user).delete()
            for exp_data in experience:
                
                def parse_month_year(date_str):
                    if not date_str:
                        return None
                    try:
                        y, m = map(int, date_str.split("-"))
                        return date(y, m, 1)
                    except (ValueError, AttributeError):
                        return None

                start_date = parse_month_year(exp_data.get("start"))
                end_date = parse_month_year(exp_data.get("end"))
                
                Experience.objects.create(
                    user=request.user,
                    title=exp_data["title"],
                    company=exp_data["company"],
                    start_date=start_date or date.today(),
                    end_date=end_date,
                    still_working=not end_date,
                    duration=0.0,
                    details=exp_data.get("description", ""),
                )

            # Cache existing project images to prevent data loss
            existing_images = {p.title: p.image for p in Project.objects.filter(user=request.user) if p.image}
            
            Project.objects.filter(user=request.user).delete()
            for proj_data in projects:
                new_image = proj_data.get("thumbnail")
                # Restore old image if no new one provided and titles match
                if not new_image:
                    new_image = existing_images.get(proj_data["name"])

                Project.objects.create(
                    user=request.user,
                    title=proj_data["name"],
                    url=proj_data.get("url"),
                    details=proj_data.get("description"),
                    video_type=proj_data.get("video_type", "long"),
                    image=new_image
                )

            Link.objects.filter(user=request.user).delete()
            for link_data in links:
                Link.objects.create(
                    user=request.user,
                    platform=link_data["name"],
                    url=link_data["url"],
                )
            
            # Ensure a UserPayment record exists
            if not UserPayment.objects.filter(user=request.user).exists():
                UserPayment.objects.create(user=request.user)


def preview_view(request, username):
    # Handle optional @ prefix from sitemap or direct links
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    
    # Increment visit counter
    profile, created = Profile.objects.get_or_create(user=user)
    
    # Visibility Check
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active
    
    # Auto-flip to private if not subscribed
    if not has_active_subscription and profile.is_public:
        profile.is_public = False
        profile.save()

    if not profile.is_public and request.user != user:
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    profile.visits += 1
    profile.save()

    personal_info = PersonalInfo.objects.filter(user=user).select_related('user').first()
    experiences = Experience.objects.filter(user=user).select_related('user')
    education = Education.objects.filter(user=user).select_related('user')
    skills = Skill.objects.filter(user=user).select_related('user')
    projects = Project.objects.filter(user=user).select_related('user')
    links = Link.objects.filter(user=user).select_related('user')

    context = {
        'personal_info': personal_info,
        'experiences': experiences,
        'education': education,
        'skills': skills,
        'projects': projects,
        'links': links,
    }

    # Dynamic template selection based on theme
    template_name = 'portfolios/developer/developer_minimal.html'  # Default fallback
    profile = getattr(user, 'profile', None)
    
    if profile and profile.theme:
        category = profile.theme.category.name.lower().replace(" ", "_") if profile.theme.category else "theme"
        theme_name = profile.theme.name.lower().replace(" ", "_")
        # Template folder structure: portfolios/category/category_theme.html
        specific_template = f"portfolios/{category}/{category}_{theme_name}.html"
        
        try:
            # Check if template exists
            get_template(specific_template)
            template_name = specific_template
        except TemplateDoesNotExist:
            template_name = 'portfolios/developer/developer_minimal.html'

    return render(request, template_name, context=context)



def pricing_view(request):
    """Render the payment page"""
    context = {
        'free_features': [
            '1 portfolio theme',
            'Public portfolio URL',
            'Personal info & skills',
            'Projects showcase',
            'Social links',
        ],
        'pro_features': [
            'All premium themes',
            'Custom domain support',
            'Portfolio analytics',
            'Remove Skillifly branding',
            'Priority support',
            'Unlimited projects',
        ],
        'annual_features': [
            'Everything in Pro',
            '2 months free',
            'Early access to new themes',
            'Dedicated support channel',
            'Export portfolio as PDF',
        ],
    }
    return render(request, 'payment/payment_new.html', context)


# Error handlers
def custom_404_view(request, exception=None):
    """Custom 404 error handler"""
    return render(request, 'errors/404.html', status=404)


def custom_500_view(request):
    """Custom 500 error handler"""
    return render(request, 'errors/500.html', status=500)


def custom_403_view(request, exception=None):
    """Custom 403 error handler"""
    return render(request, 'errors/403.html', status=403)


import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import timedelta

import requests as _requests
from django.conf import settings
from django.contrib import messages
from django.http import JsonResponse, FileResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .models import PdfExportJob
from .tasks import generate_portfolio_pdf

logger = logging.getLogger('core')

# Plan definitions  {plan_type: (amount_egp, subscription_name, subscription_days)}
PLAN_CATALOGUE = {
    'monthly':   ('50.00',  'Monthly',  30),
    'pro_monthly': ('250.00', '6 Months', 180),
    'pro_annual': ('360.00', 'Annual',  365),
}


def _get_or_create_subscription(name, days):
    """Fetch or create a Subscription record for the given plan."""
    from .models import Subscription
    sub, _ = Subscription.objects.get_or_create(
        name=name,
        defaults={'duration': days, 'days': days},
    )
    return sub


def _kashier_api_base():
    mode = getattr(settings, 'KASHIER_MODE', 'test')
    if mode == 'live':
        return 'https://api.kashier.io'
    return 'https://test-api.kashier.io'


@login_required
def create_payment(request, plan_type):
    """
    1. Validate plan & coupon.
    2. Call the Kashier Sessions API (server-side) to create a hosted session.
    3. Store a pending UserPayment record.
    4. Redirect the user to the Kashier-hosted payment page.
    """
    if plan_type not in PLAN_CATALOGUE:
        messages.error(request, 'Invalid plan selected.')
        return redirect('payment')

    amount_str, sub_name, sub_days = PLAN_CATALOGUE[plan_type]

    # --- Coupon check ---
    coupon_code = ''
    if request.method == 'POST':
        coupon_code = request.POST.get('coupon', '').strip().upper()
    else:
        coupon_code = request.GET.get('coupon', '').strip().upper()

    # Check if coupon grants free access
    if coupon_code:
        # 1) Master Bypass Coupon
        if coupon_code == 'SKILLIFLY2026' or coupon_code == getattr(settings, 'SKILLIFLY_COUPON_CODE', ''):
            sub = _get_or_create_subscription(sub_name, sub_days)
            payment = UserPayment.objects.create(
                user=request.user,
                subscription=sub,
                amount=0,
                status='paid',
                kashier_order_id=f'COUPON-MASTER-{uuid.uuid4().hex[:8].upper()}',
                discount_code_used=coupon_code,
            )
            profile, _ = Profile.objects.get_or_create(user=request.user)
            profile.is_public = True
            profile.save()
            messages.success(request, f'Developer Coupon applied! Your {sub_name} plan is now active.')
            return redirect('payment_success')

        # 2) Database Coupons
        from .models import DiscountCode
        try:
            discount = DiscountCode.objects.get(code=coupon_code, is_active=True)
            if discount.discount_percentage == 100:
                # Full discount — activate subscription immediately
                sub = _get_or_create_subscription(sub_name, sub_days)
                payment = UserPayment.objects.create(
                    user=request.user,
                    subscription=sub,
                    amount=0,
                    status='paid',
                    kashier_order_id=f'COUPON-{uuid.uuid4().hex[:12].upper()}',
                    discount_code_used=coupon_code,
                )
                discount.usage_count += 1
                discount.save()
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.is_public = True
                profile.save()
                messages.success(request, f'Coupon applied! Your {sub_name} plan is now active.')
                return redirect('payment_success')
            else:
                # Partial discount
                original_amount = float(amount_str)
                discounted_amount = original_amount * (1 - (discount.discount_percentage / 100.0))
                amount_str = f"{discounted_amount:.2f}"
                messages.success(request, f'Coupon applied! {discount.discount_percentage}% discount on your {sub_name} checkout.')
        except DiscountCode.DoesNotExist:
            messages.error(request, 'Invalid or expired coupon code.')
            return redirect('payment')

    # --- Build unique order ID ---
    order_id = f'SKF-{request.user.id}-{uuid.uuid4().hex[:10].upper()}'

    # --- Determine redirect URLs ---
    callback_url = request.build_absolute_uri(f'/payment/callback/?order_id={order_id}')
    
    # Kashier API strictly rejects localhost/127.0.0.1 in redirect URLs (throws HTTP 400)
    # For local development, fallback to a valid TLD to allow the session creation to succeed.
    if 'localhost' in callback_url or '127.0.0.1' in callback_url:
        callback_url = callback_url.replace(request.get_host(), 'skillifly.cloud').replace('http://', 'https://')
    failure_url  = request.build_absolute_uri('/payment/failure/')

    # --- Create Kashier payment session ---
    from datetime import datetime, timezone as dt_timezone
    expire_dt = (datetime.now(dt_timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S.000Z')

    webhook_url = request.build_absolute_uri('/webhook/kashier/')
    if 'localhost' in webhook_url or '127.0.0.1' in webhook_url:
        webhook_url = webhook_url.replace(request.get_host(), 'skillifly.cloud').replace('http://', 'https://')

    payload = {
        'merchantId': settings.KASHIER_MERCHANT_ID,
        'amount': amount_str,
        'currency': 'EGP',
        'order': order_id,
        'type': 'one-time',
        'paymentType': 'credit',
        'allowedMethods': 'card,wallet',
        'defaultMethod': 'card',
        'display': 'en',
        'merchantRedirect': callback_url,
        'failureRedirect': True,
        'expireAt': expire_dt,
        'maxFailureAttempts': 3,
        'enable3DS': True,
        'serverWebhook': webhook_url,
        'description': f'Skillifly {sub_name} subscription',
        'customer': {
            'email': request.user.email,
            'reference': str(request.user.id),
        },
        'metaData': {
            'plan_type': plan_type,
            'user_id': request.user.id,
        },
    }

    api_base = _kashier_api_base()
    headers = {
        'Authorization': settings.KASHIER_WEBHOOK_SECRET,
        'api-key': settings.KASHIER_API_KEY,
        'Content-Type': 'application/json',
    }

    # Setup retry strategy for network flakiness
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)

    try:
        resp = session.post(
            f'{api_base}/v3/payment/sessions',
            json=payload,
            headers=headers,
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error('Kashier error: %s', resp.text)
            messages.error(request, f'Kashier API Error: {resp.text}')
            return redirect('payment')
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ConnectionError as exc:
        logger.error('Kashier network/DNS error: %s', exc)
        messages.error(request, 'Network error: Unable to reach the payment gateway. Please check your internet connection or try again later.')
        return redirect('payment')
    except requests.exceptions.Timeout as exc:
        logger.error('Kashier timeout error: %s', exc)
        messages.error(request, 'Payment gateway is taking too long to respond. Please try again.')
        return redirect('payment')
    except Exception as exc:
        err_msg = str(exc)
        if hasattr(exc, 'response') and exc.response is not None:
            err_msg = exc.response.text
        logger.error('Kashier session creation failed: %s', err_msg)
        messages.error(request, f'Payment gateway unavailable. {err_msg}')
        return redirect('payment')

    session_url = data.get('sessionUrl')
    session_id  = data.get('_id', '')
    if not session_url:
        logger.error('Kashier returned no sessionUrl: %s', data)
        messages.error(request, 'Could not initiate payment. Please try again.')
        return redirect('payment')

    # --- Save pending payment record ---
    sub = _get_or_create_subscription(sub_name, sub_days)
    UserPayment.objects.filter(
        user=request.user, status='pending'
    ).delete()  # Clean up stale pending records
    UserPayment.objects.create(
        user=request.user,
        subscription=sub,
        amount=amount_str,
        status='pending',
        kashier_order_id=order_id,
        kashier_session_id=session_id,
        discount_code_used=coupon_code or None,
    )

    # Redirect to Kashier hosted payment page
    return redirect(session_url)


@login_required
def payment_callback(request):
    """
    Kashier redirects the user here after paying.
    We verify the payment by querying the Kashier session status API.
    """
    order_id   = request.GET.get('order_id', '').strip()
    session_id = request.GET.get('sessionId', '').strip()

    if not order_id:
        return redirect('payment')

    try:
        upayment = UserPayment.objects.get(
            user=request.user,
            kashier_order_id=order_id,
        )
    except UserPayment.DoesNotExist:
        messages.error(request, 'Payment record not found.')
        return redirect('payment')

    # If already activated (e.g. webhook beat us), go straight to success
    if upayment.status == 'paid':
        return redirect('payment_success')

    # Query Kashier for the actual status
    api_base = _kashier_api_base()
    sid = session_id or upayment.kashier_session_id
    
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    try:
        resp = session.get(
            f'{api_base}/v3/payment/sessions/{sid}/payment',
            headers={'Authorization': settings.KASHIER_WEBHOOK_SECRET},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get('data', {})
        status_from_kashier = data.get('status', '').upper()
    except Exception as exc:
        logger.error('Kashier status check failed: %s', exc)
        # Fallback: trust redirect (not ideal; webhook is the canonical source)
        status_from_kashier = 'PAID'

    if status_from_kashier in ('PAID', 'CAPTURED', 'SUCCESS', 'COMPLETED'):
        upayment.status = 'paid'
        upayment.save()

        if upayment.discount_code_used and upayment.discount_code_used != 'SKILLIFLY2026':
            from .models import DiscountCode
            try:
                disc = DiscountCode.objects.get(code=upayment.discount_code_used)
                disc.usage_count += 1
                disc.save()
            except DiscountCode.DoesNotExist:
                pass

        # Activate portfolio
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.is_public = True
        profile.save()
        return redirect('payment_success')
    else:
        upayment.status = 'failed'
        upayment.save()
        return redirect('payment_failure')


@login_required
def payment_success(request):
    return render(request, 'payment/payment_success.html')


@login_required
def payment_failure(request):
    error_message = request.session.pop('payment_error', "We couldn't process your payment. Please ensure your details are correct and try again.")
    return render(request, 'payment/payment_failure.html', {'error_message': error_message})


@csrf_exempt
def kashier_webhook(request):
    """
    Server-side webhook from Kashier.
    Verifies HMAC signature then activates/updates the subscription.
    """
    if request.method != 'POST':
        return HttpResponse('Method not allowed', status=405)

    raw_body = request.body

    # --- Signature verification ---
    sig_header = request.headers.get('x-signature', '') or request.GET.get('signature', '')
    secret = settings.KASHIER_WEBHOOK_SECRET
    if secret and sig_header:
        expected = hmac.new(
            secret.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, sig_header):
            logger.warning('Kashier webhook signature mismatch')
            return HttpResponse('Invalid signature', status=403)

    try:
        data = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError):
        return HttpResponse('Bad JSON', status=400)

    order_id = (
        data.get('order_id')
        or data.get('merchantOrderId')
        or data.get('order')
        or ''
    )
    event_status = (
        data.get('status')
        or data.get('transactionStatus')
        or ''
    ).upper()

    logger.info('Kashier webhook: order=%s status=%s', order_id, event_status)

    if not order_id:
        return HttpResponse('OK', status=200)

    try:
        upayment = UserPayment.objects.select_related('user').get(
            kashier_order_id=order_id
        )
    except UserPayment.DoesNotExist:
        logger.warning('Kashier webhook: unknown order %s', order_id)
        return HttpResponse('OK', status=200)

    if event_status in ('PAID', 'CAPTURED', 'SUCCESS', 'COMPLETED'):
        if upayment.status != 'paid':
            upayment.status = 'paid'
            upayment.save()
            
            if upayment.discount_code_used and upayment.discount_code_used != 'SKILLIFLY2026':
                from .models import DiscountCode
                try:
                    disc = DiscountCode.objects.get(code=upayment.discount_code_used)
                    disc.usage_count += 1
                    disc.save()
                except DiscountCode.DoesNotExist:
                    pass

            if upayment.user:
                profile, _ = Profile.objects.get_or_create(user=upayment.user)
                profile.is_public = True
                profile.save()
                logger.info('Subscription activated for user %s', upayment.user.username)
    elif event_status in ('FAILED', 'DECLINED', 'CANCELLED', 'CANCELED'):
        if upayment.status == 'pending':
            upayment.status = 'failed'
            upayment.save()

    return HttpResponse('OK', status=200)


def sitemap_view(request):
    """Return an enhanced sitemap.xml with static pages and deep-linked user portfolios."""
    from datetime import date as _date
    from .models import Project

    # Static pages
    SITE_LAUNCH_DATE = _date(2024, 1, 1)
    static_paths = [
        ('/', '1.0', 'monthly'),
        ('/themes/', '0.5', 'monthly'),
        ('/payment/', '0.8', 'monthly'),
        ('/contact/', '0.3', 'monthly'),
        ('/terms/', '0.2', 'monthly'),
        ('/privacy/', '0.2', 'monthly'),
    ]
    
    pages = []
    for path, priority, freq in static_paths:
        pages.append({
            'loc': request.build_absolute_uri(path),
            'lastmod': SITE_LAUNCH_DATE,
            'changefreq': freq,
            'priority': priority,
        })

    # Fetch public profiles
    public_profiles = (
        Profile.objects.filter(is_public=True)
        .select_related('user')
        .only('user__username', 'updated_at', 'created_at')
    )

    for profile in public_profiles:
        username = profile.user.username
        lastmod = (profile.updated_at or profile.created_at).date()
        
        # Main portfolio page
        pages.append({
            'loc': request.build_absolute_uri(f'/@{username}/'),
            'lastmod': lastmod,
            'changefreq': 'weekly',
            'priority': '0.9',
        })
        
        # Reels & Long Videos index
        pages.append({
            'loc': request.build_absolute_uri(f'/@{username}/reels/'),
            'lastmod': lastmod,
            'changefreq': 'weekly',
            'priority': '0.7',
        })
        pages.append({
            'loc': request.build_absolute_uri(f'/@{username}/long-videos/'),
            'lastmod': lastmod,
            'changefreq': 'weekly',
            'priority': '0.7',
        })
        
        # Individual project pages
        user_projects = Project.objects.filter(user=profile.user, video_type='long').only('slug')
        for project in user_projects:
            if project.slug:
                pages.append({
                    'loc': request.build_absolute_uri(f'/@{username}/long-videos/{project.slug}/'),
                    'lastmod': lastmod,
                    'changefreq': 'monthly',
                    'priority': '0.6',
                })

    return render(request, 'core/sitemap.xml', {'pages': pages}, content_type='application/xml')


def robots_txt_view(request):
    """Return robots.txt"""
    content = "User-agent: *\nDisallow: /admin/\nDisallow: /builder/\nSitemap: " + request.build_absolute_uri('/sitemap.xml')
    from django.http import HttpResponse
    return HttpResponse(content, content_type="text/plain")


# ------------------------------------------------------------------
# Portfolio Video Details & Sub-pages
# ------------------------------------------------------------------

def portfolio_reels(request, username):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    # Visibility Check
    profile = getattr(user, 'profile', None)
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public:
        profile.is_public = False
        profile.save()

    if profile and not profile.is_public and request.user != user:
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    profile.visits += 1
    profile.save()

    projects = Project.objects.filter(user=user, video_type='reel')
    personal_info = PersonalInfo.objects.filter(user=user).first()
    links = Link.objects.filter(user=user)
    
    # Dynamic template selection
    category = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"
    
    template = f"portfolios/{category}/{category}_{theme_name}_reels.html"
    try:
        get_template(template)
    except TemplateDoesNotExist:
        template = f"portfolios/{category}/{category}_reels.html"

    context = {
        'projects': projects,
        'type': 'Reels',
        'profile_user': user,
        'username': username,
        'personal_info': personal_info,
        'links': links,
    }
    return render(request, template, context)

def portfolio_long_videos(request, username):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    # Visibility Check
    profile = getattr(user, 'profile', None)
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public:
        profile.is_public = False
        profile.save()

    if profile and not profile.is_public and request.user != user:
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    profile.visits += 1
    profile.save()

    projects = Project.objects.filter(user=user, video_type='long')
    personal_info = PersonalInfo.objects.filter(user=user).first()
    links = Link.objects.filter(user=user)
    
    # Dynamic template selection
    category = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"
    
    template = f"portfolios/{category}/{category}_{theme_name}_long.html"
    try:
        get_template(template)
    except TemplateDoesNotExist:
        template = f"portfolios/{category}/{category}_long.html"

    context = {
        'projects': projects,
        'type': 'Long Videos',
        'profile_user': user,
        'username': username,
        'personal_info': personal_info,
        'links': links,
    }
    return render(request, template, context)

def portfolio_video_detail(request, username, slug):
    clean_username = username.lstrip('@')
    user = get_object_or_404(CustomUser, username=clean_username)
    # Visibility Check
    profile = getattr(user, 'profile', None)
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_subscription = payment and payment.is_active

    if not has_active_subscription and profile and profile.is_public:
        profile.is_public = False
        profile.save()

    if profile and not profile.is_public and request.user != user:
        return render(request, 'errors/403_private.html', {'username': username}, status=403)

    profile.visits += 1
    profile.save()

    project = get_object_or_404(Project, user=user, slug=slug)
    personal_info = PersonalInfo.objects.filter(user=user).first()
    other_videos = Project.objects.filter(user=user, video_type='long').exclude(id=project.id)[:4]
    
    # Dynamic template selection
    category = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"
    
    template = f"portfolios/{category}/{category}_{theme_name}_detail.html"
    try:
        get_template(template)
    except TemplateDoesNotExist:
        template = f"portfolios/{category}/{category}_detail.html"
    
    context = {
        'project': project,
        'profile_user': user,
        'personal_info': personal_info,
        'other_videos': other_videos,
        'username': username,
    }
    return render(request, template, context)


# ------------------------------------------------------------------
# PDF Export Views
# ------------------------------------------------------------------

@login_required
def export_pdf_start(request):
    """Initialize a PDF export job and trigger background task"""
    # Create simple hash of user data to detect changes (optional hardening)
    source_str = f"{request.user.id}-{timezone.now().timestamp()}"
    source_hash = hashlib.sha256(source_str.encode()).hexdigest()
    
    job = PdfExportJob.objects.create(
        user=request.user,
        status=PdfExportJob.Status.QUEUED,
        source_hash=source_hash
    )
    
    # Trigger Celery task
    generate_portfolio_pdf.delay(job.id)
    
    return JsonResponse({'job_id': job.id, 'status': job.status})

@login_required
def export_pdf_status(request, job_id):
    """Return JSON status of a PDF export job"""
    job = get_object_or_404(PdfExportJob, id=job_id, user=request.user)
    data = {
        'status': job.status,
        'error': job.error if job.status == PdfExportJob.Status.FAILED else None,
        'pdf_url': job.pdf_file.url if job.status == PdfExportJob.Status.SUCCEEDED and job.pdf_file else None
    }
    return JsonResponse(data)

@login_required
def export_pdf_download(request, job_id):
    """Download the generated PDF"""
    job = get_object_or_404(PdfExportJob, id=job_id, user=request.user)
    if job.status != PdfExportJob.Status.SUCCEEDED or not job.pdf_file:
        return redirect('dashboard')
    
    return FileResponse(job.pdf_file.open(), as_attachment=True, filename=os.path.basename(job.pdf_file.name))



# ------------------------------------------------------------------
# Legal & Contact
# ------------------------------------------------------------------

def terms_view(request):
    return render(request, 'legal/terms.html')

def privacy_view(request):
    return render(request, 'legal/privacy.html')

def contact_view(request):
    if request.method == "POST":
        # Handle contact form
        pass
    return render(request, 'core/contact.html')


# ------------------------------------------------------------------
# Manual Payment — InstaPay / Vodafone Cash + Gemini AI Verification
# ------------------------------------------------------------------

import base64
import google.generativeai as genai

@login_required
def manual_payment_view(request, plan_type):
    """
    GET  — show payment instructions + upload form.
    POST — verify receipt with Gemini AI and activate subscription if valid.
    """
    if plan_type not in PLAN_CATALOGUE:
        messages.error(request, 'Invalid plan selected.')
        return redirect('payment')

    amount_str, sub_name, sub_days = PLAN_CATALOGUE[plan_type]
    recipient_number = getattr(settings, 'MANUAL_PAYMENT_RECIPIENT', '+2010966071')

    # --- Coupon check (GET param so user can come from pricing page) ---
    coupon_code = request.POST.get('coupon', request.GET.get('coupon', '')).strip().upper()
    discount_applied = ''

    if coupon_code:
        # 1) Master Bypass Coupon — free access, skip payment entirely
        if coupon_code == 'SKILLIFLY2026' or coupon_code == getattr(settings, 'SKILLIFLY_COUPON_CODE', ''):
            sub = _get_or_create_subscription(sub_name, sub_days)
            UserPayment.objects.create(
                user=request.user,
                subscription=sub,
                amount=0,
                status='paid',
                kashier_order_id=f'MANUAL-MASTER-{uuid.uuid4().hex[:8].upper()}',
                discount_code_used=coupon_code,
            )
            profile, _ = Profile.objects.get_or_create(user=request.user)
            profile.is_public = True
            profile.save()
            messages.success(request, f'Developer Coupon applied! Your {sub_name} plan is now active.')
            return redirect('payment_success')

        # 2) Database Coupons
        from .models import DiscountCode
        try:
            discount = DiscountCode.objects.get(code=coupon_code, is_active=True)
            if discount.discount_percentage == 100:
                # Full discount — activate immediately
                sub = _get_or_create_subscription(sub_name, sub_days)
                UserPayment.objects.create(
                    user=request.user,
                    subscription=sub,
                    amount=0,
                    status='paid',
                    kashier_order_id=f'MANUAL-COUPON-{uuid.uuid4().hex[:12].upper()}',
                    discount_code_used=coupon_code,
                )
                discount.usage_count += 1
                discount.save()
                profile, _ = Profile.objects.get_or_create(user=request.user)
                profile.is_public = True
                profile.save()
                messages.success(request, f'Coupon applied! Your {sub_name} plan is now active.')
                return redirect('payment_success')
            else:
                # Partial discount — reduce amount
                original_amount = float(amount_str)
                discounted_amount = original_amount * (1 - (discount.discount_percentage / 100.0))
                amount_str = f"{discounted_amount:.2f}"
                discount_applied = f'{discount.discount_percentage}% discount applied!'
        except DiscountCode.DoesNotExist:
            if request.method == 'POST':
                messages.error(request, 'Invalid or expired coupon code.')
                return redirect('payment')
            # On GET, just ignore invalid coupon silently

    context = {
        'plan_type': plan_type,
        'plan_name': sub_name,
        'amount': amount_str,
        'recipient_number': recipient_number,
        'coupon_code': coupon_code,
        'discount_applied': discount_applied,
    }

    if request.method == 'GET':
        return render(request, 'payment/manual_payment.html', context)

    # --- POST: process the uploaded receipt ---
    payment_method = request.POST.get('payment_method', 'vodafone').strip()
    sender_identifier = request.POST.get('sender_identifier', '').strip()
    receipt_file = request.FILES.get('receipt_image')

    if not sender_identifier:
        messages.error(request, 'Please enter your phone number or InstaPay handle.')
        return render(request, 'payment/manual_payment.html', context)

    if not receipt_file:
        messages.error(request, 'Please upload a screenshot of your payment receipt.')
        return render(request, 'payment/manual_payment.html', context)

    # --- Standardize Image for Gemini using PIL ---
    import io
    from PIL import Image

    try:
        receipt_file.seek(0)
        with Image.open(receipt_file) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            # Resize to max 1024x1024 to save bandwidth and ensure compatibility
            img.thumbnail((1024, 1024))
            
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG')
            gemini_image_bytes = img_byte_arr.getvalue()
            gemini_mime_type = 'image/jpeg'
    except Exception as e:
        logger.error('Invalid image uploaded by %s: %s', request.user.username, e)
        messages.error(request, 'The uploaded image is invalid or corrupted. Please upload a valid image file.')
        return render(request, 'payment/manual_payment.html', context)

    # Reset file pointer for Django's model save
    receipt_file.seek(0)

    # Save the ManualPayment record
    from .models import ManualPayment
    manual_pay = ManualPayment.objects.create(
        user=request.user,
        plan_type=plan_type,
        amount_expected=amount_str,
        payment_method=payment_method,
        sender_identifier=sender_identifier,
        receipt_image=receipt_file,
        status='pending',
        discount_code_used=coupon_code or None,
    )

    # --- Gemini Vision Verification ---
    ai_failed_needs_review = False
    try:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-2.5-flash')

        image_part = {
            'mime_type': gemini_mime_type,
            'data': gemini_image_bytes,
        }

        prompt = f"""You are a strict payment verification assistant for a subscription service.
Carefully examine this payment receipt screenshot and check ALL THREE conditions:

1. RECIPIENT: The money was sent TO the number containing "2010966071" or "+2010966071" or "010966071" OR the InstaPay handle "ahmed_medhat_06@instapay"
2. SENDER: The sender's identifier (phone number or InstaPay handle) contains or matches "{sender_identifier}"  
3. AMOUNT: The total amount paid is AT LEAST {amount_str} EGP (you may accept amounts greater than or equal to {amount_str} EGP)

IMPORTANT rules:
- If the image is blurry, unreadable, or not a payment receipt, set verified=false
- All THREE conditions must be true for verified=true
- Be strict — do not approve if any condition is unclear or missing
- For the reason field, if verification fails, provide a perfect, user-friendly error message explaining exactly which condition failed. For example: "The receipt shows an amount less than the required {amount_str} EGP", "The sender handle does not match {sender_identifier}", or "The recipient number is incorrect".

Respond ONLY with this exact JSON format, no extra text:
{{"verified": true or false, "reason": "perfect error message or success message", "amount_found": "X EGP or not found", "recipient_found": "number or not found", "sender_found": "identifier or not found"}}"""

        response = model.generate_content([prompt, image_part])
        response_text = response.text.strip()

        # Strip markdown code fences if Gemini wraps the JSON
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            response_text = '\n'.join(lines[1:-1]) if len(lines) > 2 else response_text

        result = json.loads(response_text)
        verified = result.get('verified', False)
        reason = result.get('reason', 'Verification could not be completed.')

        logger.info(
            'Gemini receipt verification for user %s plan %s: verified=%s reason=%s',
            request.user.username, plan_type, verified, reason
        )

    except json.JSONDecodeError:
        logger.error('Gemini returned non-JSON response: %s', response_text if 'response_text' in dir() else 'N/A')
        verified = True
        reason = 'AI returned non-JSON response. Sent for manual review.'
        ai_failed_needs_review = True
    except Exception as exc:
        logger.exception('Gemini verification error for user %s', request.user.username)
        verified = True
        reason = f'AI Error: {str(exc)}. Sent for manual review.'
        ai_failed_needs_review = True

    if verified:
        # Activate subscription
        sub = _get_or_create_subscription(sub_name, sub_days)
        UserPayment.objects.create(
            user=request.user,
            subscription=sub,
            amount=amount_str,
            status='paid',
            kashier_order_id=f'MANUAL-{uuid.uuid4().hex[:12].upper()}',
            discount_code_used=coupon_code or None,
        )

        # Increment discount usage if partial coupon was used
        if coupon_code and coupon_code not in ('SKILLIFLY2026', getattr(settings, 'SKILLIFLY_COUPON_CODE', '')):
            from .models import DiscountCode
            try:
                disc = DiscountCode.objects.get(code=coupon_code)
                disc.usage_count += 1
                disc.save()
            except DiscountCode.DoesNotExist:
                pass

        # Mark manual payment as verified or needs_review
        if ai_failed_needs_review:
            manual_pay.status = 'needs_review'
            manual_pay.rejection_reason = reason
        else:
            manual_pay.status = 'verified'
        manual_pay.save()

        # Make portfolio public
        profile, _ = Profile.objects.get_or_create(user=request.user)
        profile.is_public = True
        profile.save()

        logger.info('Manual payment verified and subscription activated for user %s', request.user.username)
        messages.success(request, f'Payment verified! Your {sub_name} subscription is now active.')
        return redirect('payment_success')
    else:
        # Mark as rejected
        manual_pay.status = 'rejected'
        manual_pay.rejection_reason = reason
        manual_pay.save()

        request.session['payment_error'] = reason
        return redirect('payment_failure')


@login_required
def manual_payment_pending(request):
    """Simple holding page (currently unused — verification is instant)."""
    return render(request, 'payment/payment_success.html')

