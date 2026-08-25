from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import CustomUser, Profile, AnalyticsVisit, AnalyticsEvent


class OwnerVisitExclusionTests(TestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            username='john_editor',
            email='john@example.com',
            password='Password123!'
        )
        self.other_user = CustomUser.objects.create_user(
            username='jane_visitor',
            email='jane@example.com',
            password='Password123!'
        )
        # Ensure owner profile exists and has an active payment so portfolio is public
        self.owner_profile, _ = Profile.objects.get_or_create(user=self.owner, is_public=True, visits=0)
        from core.models import UserPayment, Subscription
        subscription = Subscription.objects.create(name='Pro', duration=30, days=30)
        UserPayment.objects.create(user=self.owner, subscription=subscription, status='paid')
        self.client = Client()

    def test_anonymous_visit_increments_visits(self):
        initial_visits = self.owner_profile.visits
        response = self.client.get(reverse('preview', kwargs={'username': self.owner.username}))
        self.owner_profile.refresh_from_db()
        self.assertEqual(self.owner_profile.visits, initial_visits + 1)

    def test_other_logged_in_user_visit_increments_visits(self):
        self.client.login(username='jane_visitor', password='Password123!')
        initial_visits = self.owner_profile.visits
        response = self.client.get(reverse('preview', kwargs={'username': self.owner.username}))
        self.owner_profile.refresh_from_db()
        self.assertEqual(self.owner_profile.visits, initial_visits + 1)

    def test_owner_self_visit_does_not_increment_visits(self):
        self.client.login(username='john_editor', password='Password123!')
        initial_visits = self.owner_profile.visits
        response = self.client.get(reverse('preview', kwargs={'username': self.owner.username}))
        self.owner_profile.refresh_from_db()
        self.assertEqual(self.owner_profile.visits, initial_visits)

    def test_analytics_api_ignores_owner_self_visit(self):
        self.client.login(username='john_editor', password='Password123!')
        payload = {
            'username': 'john_editor',
            'session_id': 'sess_123456789',
            'event_type': 'view'
        }
        response = self.client.post(
            reverse('track_analytics'),
            data=payload,
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'ignored')
        self.assertFalse(AnalyticsVisit.objects.filter(user=self.owner, session_id='sess_123456789').exists())

    def test_analytics_api_tracks_external_visit(self):
        self.client.login(username='jane_visitor', password='Password123!')
        payload = {
            'username': 'john_editor',
            'session_id': 'sess_ext_987654',
            'event_type': 'view'
        }
        response = self.client.post(
            reverse('track_analytics'),
            data=payload,
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.assertTrue(AnalyticsVisit.objects.filter(user=self.owner, session_id='sess_ext_987654').exists())

    def test_analytics_api_ignores_bot_traffic(self):
        payload = {
            'username': 'john_editor',
            'session_id': 'sess_bot_crawler',
            'event_type': 'view'
        }
        response = self.client.post(
            reverse('track_analytics'),
            data=payload,
            content_type='application/json',
            HTTP_USER_AGENT='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('status'), 'ignored')
        self.assertFalse(AnalyticsVisit.objects.filter(session_id='sess_bot_crawler').exists())

    def test_analytics_dashboard_avg_duration_excludes_owner_time(self):
        # Create external visit with 120 seconds duration
        AnalyticsVisit.objects.create(
            user=self.owner,
            session_id='external_sess_1',
            duration_seconds=120,
            ip_address='1.2.3.4'
        )

        # Owner attempts to track heartbeat duration of 600 seconds for themselves
        self.client.login(username='john_editor', password='Password123!')
        self.client.post(
            reverse('track_analytics'),
            data={'username': 'john_editor', 'session_id': 'owner_sess', 'event_type': 'heartbeat', 'duration': 600},
            content_type='application/json'
        )

        # Check Visitor Insights dashboard
        response = self.client.get(reverse('analytics'))
        self.assertEqual(response.status_code, 200)
        # avg_duration in context should be 120s / 60 = 2.0 mins (not including owner's 600s)
        self.assertEqual(response.context['avg_duration'], 2.0)


class DashboardMetricsTests(TestCase):
    """Accurate, period-scoped metrics for the Visitor Insights dashboard."""

    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            username='stats_owner',
            email='stats@example.com',
            password='Password123!'
        )
        Profile.objects.get_or_create(user=self.owner, is_public=True, visits=0)
        from core.models import UserPayment, Subscription
        subscription = Subscription.objects.create(name='Pro Stats', duration=30, days=30)
        UserPayment.objects.create(user=self.owner, subscription=subscription, status='paid')
        self.client = Client()
        self.client.login(username='stats_owner', password='Password123!')
        self.now = timezone.now()

    def _visit(self, session_id, minutes_ago=1, duration=60, ip=None,
               user_agent='Mozilla/5.0 (Windows NT 10.0) Chrome/120.0', referer=None):
        # created_at uses auto_now_add, so set it explicitly after creation.
        visit = AnalyticsVisit.objects.create(
            user=self.owner,
            session_id=session_id,
            duration_seconds=duration,
            ip_address=ip,
            user_agent=user_agent,
            referer=referer,
        )
        AnalyticsVisit.objects.filter(pk=visit.pk).update(
            created_at=self.now - timedelta(minutes=minutes_ago)
        )
        return visit

    def test_unique_visitors_counted_by_session_not_ip(self):
        # Two sessions sharing the same IP are still two unique visitors.
        self._visit('sess_a', ip='1.2.3.4')
        self._visit('sess_b', ip='1.2.3.4')
        response = self.client.get(reverse('analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['unique_visitors'], 2)

    def test_period_filter_applies_to_all_stats(self):
        self._visit('recent_sess', minutes_ago=60)          # inside last 7 days
        self._visit('old_sess', minutes_ago=60 * 24 * 20)   # ~20 days ago
        response = self.client.get(reverse('analytics') + '?days=7')
        self.assertEqual(response.context['total_views'], 1)
        # All-time figures stay visible separately for transparency.
        self.assertEqual(response.context['tracked_views'], 2)
        self.assertEqual(response.context['all_time_views'], 2)

    def test_bounce_rate_and_click_through_rate(self):
        bounced = self._visit('bounce_sess', duration=5)
        engaged = self._visit('engaged_sess', duration=180)
        AnalyticsEvent.objects.create(visit=engaged, event_type='project_click')
        AnalyticsEvent.objects.create(visit=engaged, event_type='project_click')
        response = self.client.get(reverse('analytics'))
        self.assertEqual(response.context['bounce_rate'], 50)
        self.assertEqual(response.context['total_clicks'], 2)
        self.assertEqual(response.context['ctr'], 100.0)

    def test_top_projects_share_of_clicks(self):
        engaged = self._visit('proj_sess', duration=200)
        AnalyticsEvent.objects.create(visit=engaged, event_type='project_click')
        AnalyticsEvent.objects.create(visit=engaged, event_type='project_click')
        AnalyticsEvent.objects.create(visit=engaged, event_type='project_click')
        response = self.client.get(reverse('analytics'))
        top_projects = response.context['top_projects']
        self.assertEqual(len(top_projects), 1)
        self.assertEqual(top_projects[0]['clicks'], 3)
        self.assertEqual(top_projects[0]['percentage'], 100.0)

    def test_device_and_browser_detection(self):
        self._visit('mobile_sess', user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1')
        self._visit('desktop_sess', user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        response = self.client.get(reverse('analytics'))
        device_names = [d['name'] for d in response.context['devices']]
        self.assertIn('Mobile', device_names)
        self.assertIn('Desktop', device_names)
        browser_names = [b[0] for b in response.context['browsers']]
        self.assertIn('Safari', browser_names)
        self.assertIn('Chrome', browser_names)

    def test_traffic_source_grouping(self):
        self._visit('ig_sess', referer='https://www.instagram.com/p/Cxyz/')
        self._visit('google_sess', referer='https://www.google.com/search?q=video+editor')
        self._visit('direct_sess', referer=None)
        response = self.client.get(reverse('analytics'))
        sources = {s['name']: s['count'] for s in response.context['traffic_sources']}
        self.assertEqual(sources.get('Instagram'), 1)
        self.assertEqual(sources.get('Google'), 1)
        self.assertEqual(sources.get('Direct'), 1)

    def test_bots_excluded_from_dashboard_numbers(self):
        self._visit('human_sess', user_agent='Mozilla/5.0 Chrome/120.0')
        AnalyticsVisit.objects.create(
            user=self.owner,
            session_id='crawler_sess',
            user_agent='Mozilla/5.0 (compatible; bingbot/2.0)',
        )
        AnalyticsVisit.objects.filter(session_id='crawler_sess').update(
            created_at=self.now - timedelta(minutes=30)
        )
        response = self.client.get(reverse('analytics'))
        self.assertEqual(response.context['total_views'], 1)

    def test_trend_delta_vs_previous_period(self):
        # One view now and one exactly 8 days ago: 7-day window sees growth of +100%? No:
        # previous window (days 8-14 before today) contains the day-8 visit -> prev=1, current=1 -> 0% change.
        self._visit('today_sess', minutes_ago=10)
        self._visit('prev_week_sess', minutes_ago=60 * 24 * 8)
        response = self.client.get(reverse('analytics') + '?days=7')
        self.assertEqual(response.context['views_change'], 0)

        # Add another visit today -> +100%
        self._visit('today_sess_2', minutes_ago=20)
        response = self.client.get(reverse('analytics') + '?days=7')
        self.assertEqual(response.context['views_change'], 100)

    def test_chart_series_includes_zero_days_and_both_metrics(self):
        self._visit('chart_sess', minutes_ago=30)
        response = self.client.get(reverse('analytics'))
        import json as jsonlib
        chart_data = jsonlib.loads(response.context['chart_data'])
        self.assertEqual(len(chart_data), 7)
        self.assertTrue(all(set(entry) >= {'label', 'views', 'visitors'} for entry in chart_data))
        total_views_in_series = sum(entry['views'] for entry in chart_data)
        self.assertEqual(total_views_in_series, 1)

    def test_arabic_dashboard_provides_same_data(self):
        self._visit('ar_sess', referer='https://t.co/abc123')
        response = self.client.get(reverse('arabic_analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_views'], 1)
        self.assertTrue(response.context['is_arabic_page'])
