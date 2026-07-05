from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from core.models import UserPayment, Subscription
from django.utils import timezone
from datetime import timedelta
import json

User = get_user_model()

class AdminDashboardTests(TestCase):
    def setUp(self):
        # Create a superuser
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpassword'
        )
        
        # Create normal users with different signup dates
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='userpass'
        )
        # We can backdate using update because date_joined is in AbstractUser
        User.objects.filter(id=self.user1.id).update(
            date_joined=timezone.make_aware(timezone.datetime(2026, 6, 1, 10, 0, 0))
        )
        
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='userpass'
        )
        User.objects.filter(id=self.user2.id).update(
            date_joined=timezone.make_aware(timezone.datetime(2026, 6, 15, 12, 0, 0))
        )
        
        # Create a Subscription
        self.sub = Subscription.objects.create(
            name='Pro Plan',
            duration=1,
            days=30
        )
        
        # Create UserPayments
        # 1. Paid payment (will be summed in total_spent because status='paid')
        self.payment1 = UserPayment.objects.create(
            user=self.user1,
            subscription=self.sub,
            amount=150.00,
            status='paid'
        )
        UserPayment.objects.filter(id=self.payment1.id).update(
            date=timezone.make_aware(timezone.datetime(2026, 6, 5, 14, 0, 0))
        )
        
        # 2. Unpaid/Pending payment (should NOT be summed in total_spent)
        self.payment2 = UserPayment.objects.create(
            user=self.user1,
            subscription=self.sub,
            amount=150.00,
            status='pending'
        )
        UserPayment.objects.filter(id=self.payment2.id).update(
            date=timezone.make_aware(timezone.datetime(2026, 6, 6, 15, 0, 0))
        )

    def test_admin_dashboard_access_superuser(self):
        self.client.login(username='admin', password='adminpassword')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_admin_dashboard_access_denied_for_normal_user(self):
        self.client.login(username='user1', password='userpass')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 302) # Redirect to login or admin checks

    def test_admin_dashboard_stats_and_charts(self):
        self.client.login(username='admin', password='adminpassword')
        
        # Test range covering the dates
        response = self.client.get(reverse('admin_dashboard'), {
            'start_date': '2026-06-01',
            'end_date': '2026-06-30',
            'period': 'day'
        })
        self.assertEqual(response.status_code, 200)
        
        # Context checks
        self.assertEqual(response.context['total_users'], 2)
        self.assertEqual(response.context['total_paid_users'], 1)
        self.assertEqual(response.context['total_revenue'], 150.00)
        
        # Verify users list annotation (total_spent)
        users = list(response.context['users_list'])
        user1_obj = next(u for u in users if u.username == 'user1')
        user2_obj = next(u for u in users if u.username == 'user2')
        
        # User 1 spent 150 (the pending payment is excluded)
        self.assertEqual(user1_obj.total_spent, 150.00)
        # User 2 spent 0 / None
        self.assertEqual(user2_obj.total_spent, None)

        # Check chart values JSON
        signup_values = json.loads(response.context['signup_values'])
        paid_values = json.loads(response.context['paid_values'])
        
        # June 1 should show 1 signup
        # June 15 should show 1 signup
        # June 5 should show 1 payment
        # June 6 should show 0 payments (since payment2 is pending)
        self.assertEqual(sum(signup_values), 2)
        self.assertEqual(sum(paid_values), 1)
