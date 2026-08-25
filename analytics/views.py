import json
import threading
from datetime import timedelta
from urllib.parse import urlparse

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count, Avg, OuterRef, Subquery
from django.db.models.functions import TruncDate

from core.models import CustomUser, AnalyticsVisit, AnalyticsEvent, UserPayment

BOT_UA_FRAGMENTS = (
    'bot', 'crawl', 'spider', 'slurp', 'curl', 'wget', 'python-requests',
    'headless', 'lighthouse', 'pagespeed', 'pingdom', 'uptime', 'monitor',
    'facebookexternalhit', 'embedly', 'whatsapp', 'telegrambot', 'preview',
)

MAX_DURATION_SECONDS = 6 * 3600  # cap absurd heartbeat values


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def _is_bot_ua(user_agent):
    ua = (user_agent or '').lower()
    if not ua:
        return False
    return any(fragment in ua for fragment in BOT_UA_FRAGMENTS)


def _parse_device(user_agent):
    ua = (user_agent or '').lower()
    if not ua:
        return 'Unknown'
    if 'ipad' in ua or 'tablet' in ua or ('android' in ua and 'mobile' not in ua):
        return 'Tablet'
    if 'mobi' in ua or 'iphone' in ua or 'android' in ua:
        return 'Mobile'
    return 'Desktop'


def _parse_browser(user_agent):
    ua = (user_agent or '').lower()
    if not ua:
        return 'Unknown'
    if 'edg/' in ua or 'edga' in ua or 'edgios' in ua:
        return 'Edge'
    if 'samsungbrowser' in ua:
        return 'Samsung Internet'
    if 'opr/' in ua or 'opera' in ua:
        return 'Opera'
    if 'firefox' in ua or 'fxios' in ua:
        return 'Firefox'
    if 'chrome' in ua or 'crios' in ua:
        return 'Chrome'
    if 'safari' in ua:
        return 'Safari'
    return 'Other'


SOURCE_MAP = {
    'google': 'Google', 'bing': 'Bing', 'duckduckgo': 'DuckDuckGo', 'yahoo': 'Yahoo',
    'instagram': 'Instagram', 'facebook': 'Facebook', 'fb.watch': 'Facebook',
    'tiktok': 'TikTok', 'twitter': 'X (Twitter)', 'x.com': 'X (Twitter)',
    't.co': 'X (Twitter)', 'linkedin': 'LinkedIn', 'lnkd.in': 'LinkedIn',
    'youtube': 'YouTube', 'youtu.be': 'YouTube', 'pinterest': 'Pinterest',
    'reddit': 'Reddit', 'whatsapp': 'WhatsApp', 'wa.me': 'WhatsApp',
    'behance': 'Behance', 'dribbble': 'Dribbble', 'vimeo': 'Vimeo',
    'artstation': 'ArtStation', 'mail.google': 'Email', 'outlook': 'Email',
}
OWN_HOSTS = ('skillifly.cloud', 'lvh.me', 'skillifly.com')


def _parse_traffic_source(referer):
    """Group a referer URL into a friendly source name."""
    if not referer:
        return None  # direct visit
    try:
        host = urlparse(referer).netloc.lower()
    except Exception:
        return 'Other'
    host = host[4:] if host.startswith('www.') else host
    if not host:
        return None
    for fragment, name in SOURCE_MAP.items():
        if fragment in host:
            return name
    if any(host == own or host.endswith('.' + own) for own in OWN_HOSTS):
        return 'Internal'
    # Unknown referrers: show the domain itself (trimmed)
    return host[:28]


def _pct_change(current, previous):
    """Return percentage change between two periods, or None when undefined."""
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100)


def _enrich_location(visit_id, ip):
    """Resolve visitor country/city from IP without blocking the tracking request."""
    import requests
    try:
        resp = requests.get(
            f"http://ip-api.com/json/{ip}",
            timeout=4,
            params={'fields': 'status,country,city'},
        )
        if resp.status_code == 200:
            geo = resp.json()
            if geo.get('status') == 'ok':
                AnalyticsVisit.objects.filter(pk=visit_id).update(
                    country=geo.get('country') or 'Unknown',
                    city=geo.get('city') or 'Unknown',
                )
    except Exception:
        pass


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
        event_type = data.get('event_type', 'view')
        session_id = data.get('session_id')

        if not username or not session_id:
            return JsonResponse({'status': 'error', 'message': 'Missing data'}, status=400)

        # Ignore bots / link-preview crawlers so human stats stay accurate
        user_agent = request.META.get('HTTP_USER_AGENT') or ''
        if _is_bot_ua(user_agent):
            response = JsonResponse({'status': 'ignored', 'message': 'Bot traffic ignored'})
            response["Access-Control-Allow-Origin"] = "*"
            return response

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
                'user_agent': user_agent,
                'referer': request.META.get('HTTP_REFERER'),
            }
        )

        # Geolocate new visits in the background so tracking stays fast
        if created and visit.ip_address:
            import ipaddress as _ipaddress
            try:
                is_public_ip = not _ipaddress.ip_address(visit.ip_address).is_private
            except ValueError:
                is_public_ip = False
            if is_public_ip and visit.country == 'Unknown':
                threading.Thread(
                    target=_enrich_location,
                    args=(visit.id, visit.ip_address),
                    daemon=True,
                ).start()

        if not created:
            # Update duration if it's a heartbeat or ping
            try:
                duration = int(data.get('duration', 0))
            except (TypeError, ValueError):
                duration = 0
            duration = max(0, min(duration, MAX_DURATION_SECONDS))
            if duration > visit.duration_seconds:
                visit.duration_seconds = duration
                visit.save(update_fields=['duration_seconds'])

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


def _build_analytics_context(user, days_param='7'):
    """Build accurate, period-scoped visitor insights shared by EN/AR dashboards."""
    try:
        active_days = int(days_param)
        if active_days not in [7, 30]:
            active_days = 7
    except (TypeError, ValueError):
        active_days = 7

    now = timezone.now()
    start = now - timedelta(days=active_days)
    prev_start = start - timedelta(days=active_days)

    profile = getattr(user, 'profile', None)
    legacy_views = getattr(profile, 'visits', 0) or 0

    # Human visits only, scoped to the selected period
    visits = AnalyticsVisit.objects.filter(user=user).exclude(user_agent__icontains='bot')

    current_qs = visits.filter(created_at__gte=start)
    previous_qs = visits.filter(created_at__gte=prev_start, created_at__lt=start)

    total_views = current_qs.count()
    unique_visitors = current_qs.values('session_id').distinct().count()
    views_per_visitor = round(total_views / unique_visitors, 1) if unique_visitors > 0 else None

    avg_seconds = current_qs.aggregate(a=Avg('duration_seconds'))['a'] or 0
    avg_duration = round(avg_seconds / 60, 1)

    bounced = current_qs.filter(duration_seconds__lt=10).count()
    bounce_rate = round(bounced / total_views * 100) if total_views > 0 else 0

    click_events = AnalyticsEvent.objects.filter(
        visit__user=user,
        event_type='project_click',
        created_at__gte=start,
    ).exclude(visit__user_agent__icontains='bot')
    total_clicks = click_events.count()
    ctr = round(total_clicks / total_views * 100, 1) if total_views > 0 else 0

    # Trend vs the equivalent preceding window
    prev_views = previous_qs.count()
    prev_visitors = previous_qs.values('session_id').distinct().count()
    prev_avg_seconds = previous_qs.aggregate(a=Avg('duration_seconds'))['a'] or 0
    prev_bounced = previous_qs.filter(duration_seconds__lt=10).count()
    prev_bounce_rate = round(prev_bounced / prev_views * 100) if prev_views > 0 else 0

    # Daily series (fills zero-visit days) — views + unique visitors
    daily_raw = (
        current_qs.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(v=Count('id'), u=Count('session_id', distinct=True))
    )
    daily_map = {row['day']: row for row in daily_raw}

    chart_data = []
    best_day = None
    for i in range(active_days - 1, -1, -1):
        day = now.date() - timedelta(days=i)
        row = daily_map.get(day, {'v': 0, 'u': 0})
        chart_data.append({
            'label': day.strftime('%b %d'),
            'views': row['v'],
            'visitors': row['u'],
        })
        if best_day is None or row['v'] > best_day['value']:
            best_day = {'label': day.strftime('%b %d'), 'value': row['v']}

    # Top projects by clicks within the period, % = share of all clicks
    top_projects = []
    if total_clicks > 0:
        projects_raw = click_events.values('project__id', 'project__title').annotate(
            clicks=Count('id')
        ).order_by('-clicks')[:5]
        for p in projects_raw:
            top_projects.append({
                'id': p['project__id'],
                'title': p['project__title'] or 'Untitled project',
                'clicks': p['clicks'],
                'percentage': round(p['clicks'] / total_clicks * 100, 1),
            })

    # Locations with share of visits
    top_locations = []
    loc_raw = (
        current_qs.values('country').annotate(count=Count('session_id', distinct=True))
        .order_by('-count')[:5]
    )
    for loc in loc_raw:
        top_locations.append({
            'country': loc['country'] or 'Unknown',
            'count': loc['count'],
            'percentage': round(loc['count'] / unique_visitors * 100, 1) if unique_visitors else 0,
        })

    # Devices & browsers (per visit)
    devices = {}
    browsers = {}
    for ua in current_qs.exclude(user_agent__isnull=True).values_list('user_agent', flat=True):
        device = _parse_device(ua)
        browser = _parse_browser(ua)
        devices[device] = devices.get(device, 0) + 1
        browsers[browser] = browsers.get(browser, 0) + 1
    device_rows = [
        {'name': k, 'count': v, 'percentage': round(v / total_views * 100, 1)}
        for k, v in sorted(devices.items(), key=lambda kv: -kv[1])
    ]
    browser_rows = sorted(browsers.items(), key=lambda kv: -kv[1])[:4]

    # Traffic sources (per session)
    sources = {}
    for referer in current_qs.values_list('referer', flat=True):
        name = _parse_traffic_source(referer) or 'Direct'
        sources[name] = sources.get(name, 0) + 1
    source_rows = [
        {'name': k, 'count': v, 'percentage': round(v / total_views * 100, 1)}
        for k, v in sorted(sources.items(), key=lambda kv: -kv[1])[:6]
    ]

    tracked_all = visits.count()
    has_data = tracked_all > 0 or legacy_views > 0

    return {
        'total_views': total_views,
        'tracked_views': tracked_all,
        'legacy_views': legacy_views,
        'all_time_views': tracked_all + legacy_views,
        'unique_visitors': unique_visitors,
        'views_per_visitor': views_per_visitor,
        'avg_duration': avg_duration,
        'bounce_rate': bounce_rate,
        'ctr': ctr,
        'total_clicks': total_clicks,
        'views_change': _pct_change(total_views, prev_views),
        'visitors_change': _pct_change(unique_visitors, prev_visitors),
        'duration_change': _pct_change(avg_duration, round(prev_avg_seconds / 60, 1)),
        'bounce_change': _pct_change(bounce_rate, prev_bounce_rate),
        'top_projects': top_projects,
        'top_locations': top_locations,
        'devices': device_rows,
        'browsers': browser_rows,
        'traffic_sources': source_rows,
        'chart_data': json.dumps(chart_data),
        'best_day': best_day,
        'active_days': active_days,
        'has_data': has_data,
    }


@login_required
def analytics_dashboard(request):
    """View for the advanced analytics dashboard"""
    # Pro Check
    payment = UserPayment.objects.filter(user=request.user, status='paid').last()
    if not (payment and payment.is_active):
        messages.warning(request, "Analytics Dashboard is a Pro feature. Upgrade to view your visitor insights.")
        return redirect('payment')

    context = _build_analytics_context(request.user, request.GET.get('days', '7'))
    return render(request, 'dashboard/analytics.html', context)


@login_required(login_url='arabic_signin')
def arabic_analytics_dashboard(request):
    """Arabic RTL version of the advanced analytics dashboard"""
    # Pro Check
    payment = UserPayment.objects.filter(user=request.user, status='paid').last()
    if not (payment and payment.is_active):
        messages.warning(request, "لوحة التحليلات من مزايا خطة Pro. قم بترقية خطتك لعرض إحصائيات زوارك.")
        return redirect('arabic_payment')

    context = _build_analytics_context(request.user, request.GET.get('days', '7'))
    context['is_arabic_page'] = True
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
