import logging
import os
from decimal import Decimal
from django.conf import settings
from datetime import date
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.db.models import Sum, Count, Avg, Q
from datetime import timedelta
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Theme, Category, Profile, PersonalInfo, Experience, Education, Skill, Project, Link, CustomUser, UserPayment, Review, Showcase, SEOSettings, ManualPayment, Creator, ProjectCategory
from .forms import RegisterForm, LoginForm, ReviewForm, SEOSettingsForm

logger = logging.getLogger('core')






@login_required
def seo_settings_view(request):
    """View to manage SEO Meta Tags"""
    # Pro Check
    payment = UserPayment.objects.filter(user=request.user, status='paid').last()
    has_active_payment = payment is not None and payment.is_active
    
    if not has_active_payment:
        messages.warning(request, "SEO Meta Tag Control is a Pro feature. Upgrade your plan to access it.")
        return redirect('payment')

    seo_settings, created = SEOSettings.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = SEOSettingsForm(request.POST, request.FILES, instance=seo_settings)
        if form.is_valid():
            form.save()
            messages.success(request, "SEO settings updated successfully!")
            return redirect('seo_settings')
    else:
        form = SEOSettingsForm(instance=seo_settings)

    context = {
        'form': form,
        'seo_settings': seo_settings,
        'portfolio_url': request.build_absolute_uri(f'/{request.user.username}/'),
    }
    return render(request, 'dashboard/seo_settings.html', context)

@login_required
def custom_domain_view(request):
    """View to manage Custom Domains"""
    # Pro Check
    payment = UserPayment.objects.filter(user=request.user, status='paid').last()
    has_active_payment = payment is not None and payment.is_active
    
    if not has_active_payment:
        messages.warning(request, "Custom Domains are a Pro feature. Upgrade your plan to access them.")
        return redirect('payment')

    from .models import CustomDomain
    from .forms import CustomDomainForm
    import socket

    custom_domain, created = CustomDomain.objects.get_or_create(user=request.user, defaults={'domain': ''})
    
    # The actual IP of the Skillifly VPS
    server_ip = '156.67.217.227'

    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'verify':
            if not custom_domain.domain:
                messages.error(request, "Please set a domain first.")
            else:
                try:
                    # Check if domain resolves to our server IP (A record)
                    # or to skillifly.cloud (CNAME record)
                    resolved_ip = socket.gethostbyname(custom_domain.domain)
                    skillifly_ip = socket.gethostbyname('skillifly.cloud')
                    
                    if resolved_ip == server_ip or resolved_ip == skillifly_ip:
                        custom_domain.is_active = True
                        custom_domain.dns_verified_at = timezone.now()
                        custom_domain.save()
                        
                        # Trigger SSL provisioning in production
                        if not settings.DEBUG:
                            import subprocess
                            try:
                                subprocess.Popen(
                                    ['sudo', 'python', 'manage.py', 'provision_ssl', custom_domain.domain],
                                    cwd=settings.BASE_DIR,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                )
                                logger.info('SSL provisioning triggered for %s', custom_domain.domain)
                            except Exception as e:
                                logger.warning('Could not trigger SSL provisioning for %s: %s', custom_domain.domain, e)
                        
                        messages.success(request, f"DNS Verified! Your portfolio is now live at {custom_domain.domain}. SSL certificate is being provisioned automatically.")
                    else:
                        messages.warning(request, f"DNS check failed. {custom_domain.domain} currently points to {resolved_ip}, but it should point to {server_ip}. Please update your DNS records.")
                except socket.gaierror:
                    messages.error(request, f"Could not resolve {custom_domain.domain}. Please check your DNS settings and try again in a few minutes.")
            return redirect('custom_domain')

        form = CustomDomainForm(request.POST, instance=custom_domain)
        if form.is_valid():
            domain_obj = form.save()
            # Reset verification status on domain change
            domain_obj.is_active = False
            domain_obj.dns_verified_at = None
            domain_obj.save()
            messages.success(request, "Custom domain updated! Please follow the DNS setup instructions and click Verify.")
            return redirect('custom_domain')
    else:
        form = CustomDomainForm(instance=custom_domain)

    context = {
        'form': form,
        'custom_domain': custom_domain,
        'server_ip': server_ip,
    }
    return render(request, 'dashboard/custom_domain.html', context)

@login_required
def submit_review_view(request):
    """Hidden review submission page for authenticated users"""
    if request.method == "POST":
        form = ReviewForm(request.POST, request.FILES)
        if form.is_valid():
            review = form.save(commit=False)
            # Default to not featured until admin approves? 
            # User didn't specify, but usually it's better to review them.
            # I'll set is_featured=False by default just in case.
            review.is_featured = False 
            review.save()
            messages.success(request, "Thank you for your review! It has been submitted for verification.")
            return redirect('dashboard')
    else:
        # Pre-fill user name if possible
        initial_data = {}
        if hasattr(request.user, 'personal_info'):
            initial_data['user_name'] = request.user.personal_info.full_name
            initial_data['user_title'] = request.user.personal_info.title
        
        form = ReviewForm(initial=initial_data)

    return render(request, 'core/submit_review.html', {'form': form})

from django.http import HttpResponse

def service_worker(request):
    """Serve the service worker file"""
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    try:
        with open(sw_path, 'rb') as f:
            return HttpResponse(f.read(), content_type="application/javascript")
    except FileNotFoundError:
        return HttpResponse("// Service Worker not found", content_type="application/javascript")

from django.views.decorators.csrf import csrf_exempt
import json


from django.http import JsonResponse

# ---------------------------------------------------------------------------
# Portfolio views moved to the `portfolios` app.
# Shim imports keep any internal reverse() / URL name lookups working.
# ---------------------------------------------------------------------------
from portfolios.views import (
    examples_view,
    preview_view,
    portfolio_reels,
    portfolio_long_videos,
    portfolio_video_detail,
    portfolio_category_detail,
)






def index(request):
    """Render the home/landing page — redirect authenticated users to dashboard"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    portfolios_count = Profile.objects.count()
    themes_count = Theme.objects.count()
    total_visits = Profile.objects.aggregate(Sum('visits'))['visits__sum'] or 0
    
    # Get featured reviews
    reviews = Review.objects.filter(is_featured=True).order_by('order', '-created_at')[:6]
    
    context = {
        'portfolios_count': portfolios_count,
        'themes_count': themes_count,
        'total_visits': total_visits,
        'reviews': reviews,
    }
    return render(request, 'core/index.html', context)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard'

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return redirect(next_url)
        else:
            message = form.errors
    else:
        form = RegisterForm()
        message = None

    context = {
        'message': message,
        'form': form,
        'next': next_url
    }
    return render(request, 'auth/signup.html', context)


def signin_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard'

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect(next_url)
        else:
            message = form.errors
    else:
        form = LoginForm()
        message = None

    context = {
        'message': message,
        'form': form,
        'next': next_url
    }
    return render(request, 'auth/signin.html', context)


def logout_view(request):
    logout(request)
    return redirect('signin')


@login_required
def profile_view(request):
    """User profile page — view & edit account details, sign out"""
    user = request.user
    profile, _ = Profile.objects.get_or_create(user=user)

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        username = request.POST.get('username', '').strip()

        errors = {}
        if email and email != user.email:
            if CustomUser.objects.filter(email=email).exclude(pk=user.pk).exists():
                errors['email'] = 'This email address is already in use.'
        if username and username != user.username:
            if CustomUser.objects.filter(username=username).exclude(pk=user.pk).exists():
                errors['username'] = 'This username is already taken.'
            elif len(username) < 3:
                errors['username'] = 'Username must be at least 3 characters.'

        if errors:
            error_msg = ' '.join(errors.values())
            messages.error(request, error_msg)
        else:
            user.first_name = first_name
            user.last_name = last_name
            if email:
                user.email = email
            if username:
                user.username = username
            user.save()

            # Handle profile picture upload (same field used by builder/portfolio)
            picture = request.FILES.get('picture')
            if picture:
                profile.picture = picture
                profile.save()
            elif request.POST.get('remove_picture') == '1':
                profile.picture = None
                profile.save()

            messages.success(request, 'Profile updated successfully!')
            return redirect('profile')

    # Payment info
    payment = UserPayment.objects.filter(user=user, status='paid').last()
    has_active_payment = payment is not None and payment.is_active

    # Profile picture
    profile_picture = None
    if profile.picture and hasattr(profile.picture, 'url'):
        profile_picture = profile.picture.url

    # User initials for avatar fallback
    initials = ''
    if user.first_name and user.last_name:
        initials = (user.first_name[0] + user.last_name[0]).upper()
    elif user.first_name:
        initials = user.first_name[:2].upper()
    else:
        initials = user.username[:2].upper()

    context = {
        'profile': profile,
        'has_active_payment': has_active_payment,
        'profile_picture': profile_picture,
        'user_initials': initials,
    }
    return render(request, 'dashboard/profile.html', context)


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

    # Fetch site settings for the banner
    from .models import SiteSettings
    site_settings = SiteSettings.objects.first()
    if not site_settings:
        # Create default settings if none exist
        site_settings = SiteSettings.objects.create()

    # Ensure visibility is synced with subscription status
    if not has_active_payment and profile.is_public:
        profile.is_public = False
        profile.save()

    # Check if we need to show the category notification
    show_category_notification = request.session.pop('show_category_notification', False)

    context = {
        'profile': profile,
        'days_left': days_left,
        'payment': payment,
        'has_active_payment': has_active_payment,
        'portfolio_url': portfolio_url,
        'is_developer': is_developer,
        'is_annual_subscriber': is_annual_subscriber,
        'site_settings': site_settings,
        'show_category_notification': show_category_notification,
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

        # Check if it's a category theme
        if 'categories' in theme.name.lower() or 'category' in theme.name.lower():
            request.session['show_category_notification'] = True

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



def sitemap_view(request):
    """Return an enhanced sitemap.xml. Domain-aware for custom domains."""
    from datetime import date as _date
    from .models import Project, Profile, CustomUser

    # Detect if we're on a custom domain
    custom_user = getattr(request, 'custom_domain_user', None)

    pages = []

    # If it's NOT a custom domain, include static main site pages
    if not custom_user:
        SITE_LAUNCH_DATE = _date(2024, 1, 1)
        static_paths = [
            ('/', '1.0', 'monthly'),
            ('/themes/', '0.5', 'monthly'),
            ('/payment/', '0.8', 'monthly'),
            ('/contact/', '0.3', 'monthly'),
            ('/terms/', '0.2', 'monthly'),
            ('/privacy/', '0.2', 'monthly'),
        ]
        for path, priority, freq in static_paths:
            pages.append({
                'loc': request.build_absolute_uri(path),
                'lastmod': SITE_LAUNCH_DATE,
                'changefreq': freq,
                'priority': priority,
            })

        # Global sitemap for all public profiles
        public_profiles = Profile.objects.filter(is_public=True).select_related('user')
    else:
        # Custom domain: ONLY show this user's content
        public_profiles = Profile.objects.filter(user=custom_user, is_public=True).select_related('user')

    for profile in public_profiles:
        username = profile.user.username
        lastmod = (profile.updated_at or profile.created_at).date()
        
        # Determine prefix (empty for custom domain, /@username for main domain)
        prefix = "" if custom_user else f"/@{username}"
        
        # Main portfolio page
        pages.append({
            'loc': request.build_absolute_uri(f'{prefix}/'),
            'lastmod': lastmod,
            'changefreq': 'weekly',
            'priority': '0.9',
        })
        
        # Reels & Long Videos index
        pages.append({
            'loc': request.build_absolute_uri(f'{prefix}/reels/'),
            'lastmod': lastmod,
            'changefreq': 'weekly',
            'priority': '0.7',
        })
        pages.append({
            'loc': request.build_absolute_uri(f'{prefix}/long-videos/'),
            'lastmod': lastmod,
            'changefreq': 'weekly',
            'priority': '0.7',
        })
        
        # Individual project pages
        user_projects = Project.objects.filter(user=profile.user, video_type='long').only('slug')
        for project in user_projects:
            if project.slug:
                pages.append({
                    'loc': request.build_absolute_uri(f'{prefix}/long-videos/{project.slug}/'),
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
        'download_url': reverse('export_pdf_download', kwargs={'job_id': job.id}) if job.status == PdfExportJob.Status.SUCCEEDED and job.pdf_file else None
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

@user_passes_test(lambda u: u.is_superuser)
def revenue_report(request):
    """Hidden admin-only revenue report with date filtering and graphs."""
    from django.db.models import Sum, Count
    platform_launch_date = timezone.datetime(2026, 5, 1, tzinfo=timezone.get_current_timezone()).date()
    today = timezone.now().date()

    # Date range inputs
    start_str = request.GET.get('start_date')
    end_str   = request.GET.get('end_date')

    if start_str:
        try:
            start_date = timezone.datetime.strptime(start_str, '%Y-%m-%d').date()
            if start_date < platform_launch_date:
                start_date = platform_launch_date
        except ValueError:
            start_date = platform_launch_date
    else:
        start_date = platform_launch_date

    if end_str:
        try:
            end_date = timezone.datetime.strptime(end_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = today
    else:
        end_date = today

    # Convert to datetime for filtering (inclusive)
    start_dt = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end_dt   = timezone.make_aware(timezone.datetime.combine(end_date, timezone.datetime.max.time()))

    # Fetch UserPayments (Exclude Kashier 'SKF-' gateway payments)
    payments = UserPayment.objects.filter(
        status='paid',
        date__range=(start_dt, end_dt)
    ).exclude(
        kashier_order_id__startswith='SKF-'
    ).select_related('user', 'subscription').order_by('-date')

    # --- Split: paid (amount > 0) vs free-code (amount = 0) ---
    paid_payments = payments.filter(amount__gt=0)
    free_payments = payments.filter(amount=0)

    paid_count         = paid_payments.count()
    free_count         = free_payments.count()
    total_transactions = payments.count()

    # Revenue only from real payments
    total_revenue = paid_payments.aggregate(total=Sum('amount'))['total'] or 0
    avg_payment   = total_revenue / paid_count if paid_count > 0 else 0
    
    # Calculate conversion metrics
    from .models import CustomUser
    total_signups = CustomUser.objects.filter(date_joined__range=(start_dt, end_dt)).count()
    unique_paid_users = paid_payments.values('user').distinct().count()
    conversion_rate = round((unique_paid_users / total_signups * 100), 1) if total_signups > 0 else 0

    # Calculate Monthly vs Annual plan breakdown
    monthly_paid_count = paid_payments.filter(subscription__days=30).count()
    six_month_paid_count = paid_payments.filter(subscription__days=180).count()
    annual_paid_count = paid_payments.filter(subscription__days=365).count()
    total_paid_subs = monthly_paid_count + annual_paid_count
    
    total_monthly_annual = monthly_paid_count + annual_paid_count
    monthly_pct = (monthly_paid_count / total_monthly_annual * 100) if total_monthly_annual > 0 else 0
    annual_pct = (annual_paid_count / total_monthly_annual * 100) if total_monthly_annual > 0 else 0

    # --- Plan breakdown ---
    plan_breakdown = list(
        paid_payments.values('subscription__name')
        .annotate(count=Count('id'), revenue=Sum('amount'))
        .order_by('-count')
    )

    # --- Daily chart data ---
    chart_labels   = []
    chart_revenue  = []
    chart_paid_cnt = []
    chart_free_cnt = []

    current_day = start_date
    while current_day <= end_date:
        day_paid = paid_payments.filter(date__date=current_day)
        day_free = free_payments.filter(date__date=current_day)

        chart_labels.append(current_day.strftime('%b %d'))
        chart_revenue.append(float(day_paid.aggregate(total=Sum('amount'))['total'] or 0))
        chart_paid_cnt.append(day_paid.count())
        chart_free_cnt.append(day_free.count())
        current_day += timedelta(days=1)

    context = {
        'payments':          payments,
        'total_revenue':     total_revenue,
        'paid_count':        paid_count,
        'free_count':        free_count,
        'total_transactions': total_transactions,
        'avg_payment':       avg_payment,
        'total_signups':     total_signups,
        'unique_paid_users': unique_paid_users,
        'conversion_rate':   conversion_rate,
        'monthly_paid_count': monthly_paid_count,
        'six_month_paid_count': six_month_paid_count,
        'annual_paid_count':  annual_paid_count,
        'total_paid_subs':    total_paid_subs,
        'monthly_pct':        monthly_pct,
        'annual_pct':         annual_pct,
        'plan_breakdown':    plan_breakdown,
        'start_date':        start_date,
        'end_date':          end_date,
        'min_date':          platform_launch_date,
        'chart_labels':      json.dumps(chart_labels),
        'chart_revenue':     json.dumps(chart_revenue),
        'chart_paid_cnt':    json.dumps(chart_paid_cnt),
        'chart_free_cnt':    json.dumps(chart_free_cnt),
    }

    return render(request, 'core/revenue_report.html', context)


@user_passes_test(lambda u: u.is_superuser)
def admin_dashboard(request):
    """Hidden admin-only dashboard with user stats, growth charts, and user list."""
    # Absolute minimum date allowed
    min_date = timezone.datetime(2026, 4, 16, tzinfo=timezone.get_current_timezone()).date()
    
    try:
        today = timezone.localdate()
    except Exception:
        today = timezone.now().date()
    
    # 1. Date Filtering Logic
    start_str = request.GET.get('start_date')
    end_str = request.GET.get('end_date')
    period = request.GET.get('period', 'day') # 'day' or 'week'
    
    if start_str:
        try:
            start_date = timezone.datetime.strptime(start_str, '%Y-%m-%d').date()
            if start_date < min_date:
                start_date = min_date
        except ValueError:
            start_date = today.replace(day=1)
            if start_date < min_date:
                start_date = min_date
    else:
        # Default to the first of the current month
        start_date = today.replace(day=1)
        if start_date < min_date:
            start_date = min_date
        
    if end_str:
        try:
            end_date = timezone.datetime.strptime(end_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = today
    else:
        end_date = today

    if start_date > end_date:
        start_date = end_date

    # Convert to aware datetimes for index-friendly filtering
    start_dt = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
    end_dt   = timezone.make_aware(timezone.datetime.combine(end_date, timezone.datetime.max.time()))

    # 2. High-level Stats (Now filtered by range)
    # Total Users = New signups in this period
    total_users = CustomUser.objects.filter(date_joined__range=(start_dt, end_dt)).count()
    
    # Paid users = unique users who made a successful payment in this period
    paid_user_ids_in_period = UserPayment.objects.filter(
        status='paid', 
        amount__gt=0,
        date__range=(start_dt, end_dt)
    ).values_list('user_id', flat=True).distinct()
    
    total_paid_users = len(paid_user_ids_in_period)
    conversion_rate = (total_paid_users / total_users * 100) if total_users > 0 else 0
    
    # Global paid user IDs for the table 'Paid' badge (unfiltered)
    # Check if a user has a payment with status 'paid' that is still active
    all_payments = UserPayment.objects.filter(status='paid', amount__gt=0).select_related('subscription')
    active_paid_user_ids = {p.user_id for p in all_payments if p.is_active}
    
    # Total revenue in period
    total_revenue = UserPayment.objects.filter(
        status='paid',
        date__range=(start_dt, end_dt)
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    # 3. Growth Chart Data (Filtered by range and period)
    signup_labels = []
    signup_values = []
    paid_values = [] # Track count of payments made in each interval
    
    if period == 'week':
        # Grouping by 7-day intervals starting from start_date
        current_dt = start_date
        while current_dt <= end_date:
            next_dt = current_dt + timedelta(days=7)
            if next_dt > end_date + timedelta(days=1):
                next_dt = end_date + timedelta(days=1)
            
            interval_start_dt = timezone.make_aware(timezone.datetime.combine(current_dt, timezone.datetime.min.time()))
            interval_end_dt = timezone.make_aware(timezone.datetime.combine(next_dt - timedelta(days=1), timezone.datetime.max.time()))
            
            # 1. New Signups in interval
            signup_count = CustomUser.objects.filter(
                date_joined__range=(interval_start_dt, interval_end_dt)
            ).count()
            
            # 2. Payments in interval
            paid_count = UserPayment.objects.filter(
                status='paid',
                amount__gt=0,
                date__range=(interval_start_dt, interval_end_dt)
            ).count()
            
            signup_labels.append(f"Wk: {current_dt.strftime('%b %d')}")
            signup_values.append(signup_count)
            paid_values.append(paid_count)
            current_dt = next_dt
    else:
        # Default: Daily grouping
        current_dt = start_date
        while current_dt <= end_date:
            day_start_dt = timezone.make_aware(timezone.datetime.combine(current_dt, timezone.datetime.min.time()))
            day_end_dt = timezone.make_aware(timezone.datetime.combine(current_dt, timezone.datetime.max.time()))
            
            # 1. New Signups
            signup_count = CustomUser.objects.filter(date_joined__range=(day_start_dt, day_end_dt)).count()
            
            # 2. Payments
            paid_count = UserPayment.objects.filter(
                status='paid',
                amount__gt=0,
                date__range=(day_start_dt, day_end_dt)
            ).count()
            
            signup_labels.append(current_dt.strftime('%b %d'))
            signup_values.append(signup_count)
            paid_values.append(paid_count)
            current_dt += timedelta(days=1)
        
    # 4. Users Table Data (NOW FILTERED BY RANGE)
    users_list = CustomUser.objects.filter(
        date_joined__range=(start_dt, end_dt)
    ).select_related('profile', 'personal_info').annotate(
        total_spent=Sum('userpayment__amount', filter=Q(userpayment__status='paid'))
    ).order_by('-date_joined')
    
    context = {
        'total_users': total_users,
        'total_paid_users': total_paid_users,
        'paid_user_ids': list(active_paid_user_ids), # Convert to list for template 'in' check
        'conversion_rate': round(conversion_rate, 1),
        'total_revenue': total_revenue,
        'signup_labels': json.dumps(signup_labels),
        'signup_values': json.dumps(signup_values),
        'paid_values': json.dumps(paid_values),
        'users_list': users_list,
        'start_date': start_date,
        'end_date': end_date,
        'min_date': min_date,
        'period': period,
    }
    
    return render(request, 'core/admin_dashboard.html', context)


@user_passes_test(lambda u: u.is_superuser)
def manage_dashboard(request):
    """Admin hub for superusers to access all management pages."""
    from .models import DiscountCode, SiteSettings
    from .forms import DiscountCodeForm, SiteSettingsForm
    
    discount_codes = DiscountCode.objects.all().order_by('-created_at')
    site_settings = SiteSettings.objects.first()
    if not site_settings:
        site_settings = SiteSettings.objects.create()
        
    discount_form = DiscountCodeForm()
    banner_form = SiteSettingsForm(instance=site_settings)
    
    context = {
        'discount_codes': discount_codes,
        'site_settings': site_settings,
        'discount_form': discount_form,
        'banner_form': banner_form,
    }
    return render(request, 'core/manage.html', context)



@login_required
def affiliate_view(request):
    """Render the affiliate dashboard or landing page."""
    from .models import AffiliateProfile, DiscountCode
    affiliate_profile = AffiliateProfile.objects.filter(user=request.user).first()
    
    discount_code = None
    if affiliate_profile:
        # User is already an affiliate, find their specific 28% code
        discount_code = DiscountCode.objects.filter(owner=request.user, discount_percentage=28).first()

    context = {
        'affiliate': affiliate_profile,
        'discount_code': discount_code,
    }
    return render(request, 'core/affiliate.html', context)


@login_required
def join_affiliate(request):
    """Enroll the user in the affiliate program and generate their code."""
    if request.method == "POST":
        from .models import AffiliateProfile, DiscountCode
        
        # Check if already an affiliate
        if AffiliateProfile.objects.filter(user=request.user).exists():
            messages.info(request, "You are already enrolled in the affiliate program.")
            return redirect('affiliate')

        # 1. Create Affiliate Profile
        AffiliateProfile.objects.create(user=request.user)

        # 2. Generate Discount Code (username-based, 28% off)
        code_str = request.user.username.upper()
        
        # Ensure code is unique (append random chars if username taken as code)
        if DiscountCode.objects.filter(code=code_str).exists():
            code_str = f"{code_str}{uuid.uuid4().hex[:4].upper()}"
            
        DiscountCode.objects.create(
            code=code_str,
            discount_percentage=28,
            owner=request.user,
            is_active=True
        )

        messages.success(request, f"Welcome to the Affiliate Program! Your personal code {code_str} is now active.")
        return redirect('affiliate')
    
    return redirect('affiliate')


def process_affiliate_earning(upayment):
    """
    Helper to credit affiliates when their code is used for an annual plan.
    Reward: 100 EGP.
    """
    if not upayment.discount_code_used or upayment.status != 'paid':
        return

    # Check if it's an annual plan (365 days)
    if upayment.subscription and upayment.subscription.days == 365:
        from .models import DiscountCode, AffiliateProfile
        try:
            # Find the discount code and its owner
            discount = DiscountCode.objects.get(code=upayment.discount_code_used.upper())
            owner = discount.owner
            
            # Check if owner has an affiliate profile
            affiliate, created = AffiliateProfile.objects.get_or_create(user=owner)
            
            # Credit the affiliate
            earning_amount = 100.00
            affiliate.balance += Decimal(earning_amount)
            affiliate.total_earned += Decimal(earning_amount)
            affiliate.save()
            
            logger.info(f"Affiliate Earning: {owner.username} earned 100 EGP from {upayment.user.username}")
        except (DiscountCode.DoesNotExist, Exception) as e:
            logger.error(f"Error processing affiliate earning: {e}")


@user_passes_test(lambda u: u.is_superuser)
def manage_affiliates(request):
    """Admin view to manage all affiliates and their earnings."""
    from .models import AffiliateProfile, DiscountCode
    from django.db.models import Sum
    
    affiliates = AffiliateProfile.objects.select_related('user').all().order_by('-created_at')
    
    # Calculate summary stats
    total_affiliates = affiliates.count()
    total_balance = affiliates.aggregate(Sum('balance'))['balance__sum'] or 0
    total_lifetime = affiliates.aggregate(Sum('total_earned'))['total_earned__sum'] or 0
    
    # Pre-fetch 28% codes for these users to avoid N+1
    codes = DiscountCode.objects.filter(owner__in=[a.user for a in affiliates], discount_percentage=28)
    code_map = {c.owner_id: c.code for c in codes}
    
    for affiliate in affiliates:
        affiliate.promo_code = code_map.get(affiliate.user_id, "NO CODE")
        
    context = {
        'affiliates': affiliates,
        'total_affiliates': total_affiliates,
        'total_balance': total_balance,
        'total_lifetime': total_lifetime,
        'join_link': request.build_absolute_uri(reverse('affiliate')),
    }
    return render(request, 'core/manage_affiliates.html', context)






def portfolio_category_detail(request, username, category_id):
    user = get_object_or_404(CustomUser, username=username)
    profile = getattr(user, 'profile', None)
    
    if int(category_id) == 0:
        # Mock a category object
        class MockCategory:
            id = 0
            name = 'Other Videos'
            description = 'Uncategorized projects and videos.'
        category = MockCategory()
        projects = Project.objects.filter(user=user, category__isnull=True)
    else:
        from core.models import ProjectCategory
        category = get_object_or_404(ProjectCategory, user=user, id=category_id)
        projects = Project.objects.filter(user=user, category=category)
        
    # simple view tracking
    cat_key = f'viewed_category_{category.id}'
    if not request.session.get(cat_key, False):
        if profile:
            profile.visits += 1
            profile.save(update_fields=['visits'])
        request.session[cat_key] = True
        
    category_slug = profile.theme.category.name.lower().replace(" ", "_") if profile and profile.theme and profile.theme.category else "video_editor"
    theme_name = profile.theme.name.lower().replace(" ", "_") if profile and profile.theme else "default"
    
    template = f"portfolios/{category_slug}/{category_slug}_{theme_name}_category.html"
    from django.template.exceptions import TemplateDoesNotExist
    from django.template.loader import get_template
    try:
        get_template(template)
    except TemplateDoesNotExist:
        template = f"portfolios/{category_slug}/{category_slug}_category.html"
        
    context = {
        'portfolio_user': user,
        'profile': profile,
        'category': category,
        'projects': projects,
    }
    return render(request, template, context)

