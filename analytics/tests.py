from django.test import TestCase, Client
from django.urls import reverse
from core.models import CustomUser, Profile, AnalyticsVisit

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


