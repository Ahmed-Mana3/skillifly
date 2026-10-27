"""Private portfolios: staff users and superusers can view them; everyone else gets the 403 page."""
from django.test import TestCase
from django.urls import reverse

from core.models import Profile
from core.testing_helpers import make_editor


class AdminCanViewPrivatePortfolioTests(TestCase):
    def setUp(self):
        self.owner = make_editor(username='hidden')
        self.profile = Profile.objects.create(user=self.owner, is_public=False)
        self.urls = [
            reverse('preview', kwargs={'username': 'hidden'}),
            reverse('portfolio_reels', kwargs={'username': 'hidden'}),
            reverse('portfolio_long_videos', kwargs={'username': 'hidden'}),
        ]

    def test_anonymous_and_regular_users_are_blocked(self):
        for url in self.urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.client.force_login(make_editor(username='stranger'))
        for url in self.urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_superuser_can_view_even_without_staff(self):
        self.client.force_login(make_editor(username='boss', is_superuser=True, is_staff=False))
        for url in self.urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_staff_can_view(self):
        self.client.force_login(make_editor(username='mod', is_staff=True))
        for url in self.urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_admin_visits_are_not_counted(self):
        self.client.force_login(make_editor(username='boss', is_superuser=True, is_staff=True))
        self.client.get(self.urls[0])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.visits, 0)
        self.assertFalse(self.profile.is_public)
