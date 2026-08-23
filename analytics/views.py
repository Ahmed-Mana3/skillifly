import json
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Avg, OuterRef, Subquery

from core.models import CustomUser, AnalyticsVisit, AnalyticsEvent, Project, UserPayment


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


@csrf_exempt
def track_analytics(request):
    """Endpoint to track portfolio views and events"""
    if request.method == 'OPTIONS':
        response = HttpResponse()
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST allowed'}, status=405)
    
    try:
        if request.content_type == 'application/json' or not request.content_type:
            data = json.loads(request.body)
        else:
            # Handle text/plain from sendBeacon
            data = json.loads(request.body.decode('utf-8'))
        
        username = data.get('username')
        print(f"DEBUG: Tracking event for {username}: {data}")
        event_type = data.get('event_type', 'view')
        session_id = data.get('session_id')
        
        if not username or not session_id:
            return JsonResponse({'status': 'error', 'message': 'Missing data'}, status=400)

        user = get_object_or_404(CustomUser, username=username)

        # Ignore analytics tracking if the logged-in user is visiting their own portfolio
        if request.user.is_authenticated and request.user == user:
            response = JsonResponse({'status': 'ignored', 'message': 'Owner visit ignored'})
            response["Access-Control-Allow-Origin"] = "*"
            return response
        
        # Get or create the visit session
        visit, created = AnalyticsVisit.objects.get_or_create(
            session_id=session_id,
            user=user,
            defaults={
                'ip_address': get_client_ip(request),
                'user_agent': request.META.get('HTTP_USER_AGENT'),
                'referer': request.META.get('HTTP_REFERER'),
            }
        )
        
        # Simple Geolocation based on IP (Real-time lookup for demo purposes)
        if created and visit.ip_address:
            import requests
            try:
                # Use a free API (Note: in high traffic production, use MaxMind GeoIP2 locally)
                response = requests.get(f"http://ip-api.com/json/{visit.ip_address}", timeout=3)
                if response.status_code == 200:
                    geo_data = response.json()
                    visit.country = geo_data.get('country', 'Unknown')
                    visit.city = geo_data.get('city', 'Unknown')
                    visit.save()
            except Exception:
                pass
        
        if not created:
            # Update duration if it's a heartbeat or ping
            duration = data.get('duration', 0)
            if duration > visit.duration_seconds:
                visit.duration_seconds = duration
                visit.save()

        if event_type == 'project_click':
            project_id = data.get('project_id')
            if project_id:
                AnalyticsEvent.objects.create(
                    visit=visit,
                    event_type='project_click',
                    project_id=project_id
                )
        
        response = JsonResponse({'status': 'success'})
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type"
        return response
    except Exception as e:
        response = JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        response["Access-Control-Allow-Origin"] = "*"
        return response


@login_required
def analytics_dashboard(request):
    """View for the advanced analytics dashboard"""
    # Pro Check
    payment = UserPayment.objects.filter(user=request.user, status='paid').last()
    if not (payment and payment.is_active):
        messages.warning(request, "Analytics Dashboard is a Pro feature. Upgrade to view your visitor insights.")
        return redirect('payment')
    
    # Base Queryset
    visits = AnalyticsVisit.objects.filter(user=request.user)
    
    # Stats
    tracked_views = visits.count()
    legacy_views = getattr(request.user.profile, 'visits', 0)
    total_views = tracked_views + legacy_views
    
    unique_visitors = visits.values('ip_address', 'user_agent').distinct().count()
    avg_duration = visits.aggregate(Avg('duration_seconds'))['duration_seconds__avg'] or 0
    
    # Top Projects
    top_projects_raw = AnalyticsEvent.objects.filter(
        visit__user=request.user, 
        event_type='project_click'
    ).values('project__title', 'project__id').annotate(
        clicks=Count('id')
    ).order_by('-clicks')[:5]
    
    top_projects = []
    for p in top_projects_raw:
        percentage = (p['clicks'] / total_views * 100) if total_views > 0 else 0
        p['percentage'] = round(percentage, 1)
        top_projects.append(p)
    
    # Top Locations (By Visit)
    top_locations = visits.values('country').annotate(
        count=Count('id')
    ).order_by('-count')[:5]

    # Time Chart (last N days)
    days_param = request.GET.get('days', '7')
    try:
        active_days = int(days_param)
        if active_days not in [7, 30]:
            active_days = 7
    except ValueError:
        active_days = 7

    chart_data = []
    
    for i in range(active_days - 1, -1, -1):
        day = timezone.now().date() - timedelta(days=i)
        tracked_count = visits.filter(created_at__date=day).count()
        
        # for 30 days, maybe skip labels or format differently, but JS can handle it
        label_format = '%b %d'
        chart_data.append({
            'label': day.strftime(label_format),
            'value': tracked_count
        })

    context = {
        'total_views': total_views,
        'tracked_views': tracked_views,
        'legacy_views': legacy_views,
        'unique_visitors': unique_visitors,
        'avg_duration': round(avg_duration / 60, 1), # in minutes
        'top_projects': top_projects,
        'top_locations': top_locations,
        'chart_data': json.dumps(chart_data),
        'active_days': active_days,
    }
    return render(request, 'dashboard/analytics.html', context)


@login_required(login_url='arabic_signin')
def arabic_analytics_dashboard(request):
    """Arabic RTL version of the advanced analytics dashboard"""
    # Pro Check
    payment = UserPayment.objects.filter(user=request.user, status='paid').last()
    if not (payment and payment.is_active):
        messages.warning(request, "لوحة التحليلات من مزايا خطة Pro. قم بترقية خطتك لعرض إحصائيات زوارك.")
        return redirect('arabic_payment')

    # Base Queryset
    visits = AnalyticsVisit.objects.filter(user=request.user)

    # Stats
    tracked_views = visits.count()
    legacy_views = getattr(request.user.profile, 'visits', 0)
    total_views = tracked_views + legacy_views

    unique_visitors = visits.values('ip_address', 'user_agent').distinct().count()
    avg_duration = visits.aggregate(Avg('duration_seconds'))['duration_seconds__avg'] or 0

    # Top Projects
    top_projects_raw = AnalyticsEvent.objects.filter(
        visit__user=request.user,
        event_type='project_click'
    ).values('project__title', 'project__id').annotate(
        clicks=Count('id')
    ).order_by('-clicks')[:5]

    top_projects = []
    for p in top_projects_raw:
        percentage = (p['clicks'] / total_views * 100) if total_views > 0 else 0
        p['percentage'] = round(percentage, 1)
        top_projects.append(p)

    # Top Locations (By Visit)
    top_locations = visits.values('country').annotate(
        count=Count('id')
    ).order_by('-count')[:5]

    # Time Chart (last N days)
    days_param = request.GET.get('days', '7')
    try:
        active_days = int(days_param)
        if active_days not in [7, 30]:
            active_days = 7
    except ValueError:
        active_days = 7

    chart_data = []

    for i in range(active_days - 1, -1, -1):
        day = timezone.now().date() - timedelta(days=i)
        tracked_count = visits.filter(created_at__date=day).count()

        # for 30 days, maybe skip labels or format differently, but JS can handle it
        label_format = '%b %d'
        chart_data.append({
            'label': day.strftime(label_format),
            'value': tracked_count
        })

    context = {
        'total_views': total_views,
        'tracked_views': tracked_views,
        'legacy_views': legacy_views,
        'unique_visitors': unique_visitors,
        'avg_duration': round(avg_duration / 60, 1), # in minutes
        'top_projects': top_projects,
        'top_locations': top_locations,
        'chart_data': json.dumps(chart_data),
        'active_days': active_days,
        'is_arabic_page': True,
    }
    return render(request, 'dashboard/arabic_analytics.html', context)


@user_passes_test(lambda u: u.is_superuser)
def user_activity_report(request):
    """View to see last time users opened Skillifly and last portfolio visits."""
    
    # Subquery to get the latest visit for each user's portfolio
    latest_visit_subquery = AnalyticsVisit.objects.filter(
        user=OuterRef('pk')
    ).order_by('-created_at').values('created_at')[:1]
    
    users = CustomUser.objects.annotate(
        last_portfolio_visit=Subquery(latest_visit_subquery)
    ).select_related('profile', 'personal_info').order_by('-profile__last_seen')
    
    # Calculate status badges (Active: < 15 mins, Idle: < 24 hours, Away: > 24 hours)
    now = timezone.now()
    active_threshold = now - timedelta(minutes=15)
    idle_threshold = now - timedelta(hours=24)
    
    context = {
        'users': users,
        'now': now,
        'active_threshold': active_threshold,
        'idle_threshold': idle_threshold,
    }
    return render(request, 'core/user_activity.html', context)
