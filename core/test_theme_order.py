import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Category, Theme


class ThemeOrderTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('boss', 'boss@example.com', 'pw12345!')
        self.user = User.objects.create_user('plain', 'plain@example.com', 'pw12345!')
        video = Category.objects.create(name='Video Editor')
        dev = Category.objects.create(name='Developer')
        self.dev_hot = Theme.objects.create(name='dev_hot', category=dev, use_num=99)
        self.vid_low = Theme.objects.create(name='vid_low', category=video, use_num=1)
        self.vid_high = Theme.objects.create(name='vid_high', category=video, use_num=10)

    def names(self, response):
        return [t.name for t in response.context['themes']]

    def test_automatic_order_is_video_editor_first_then_uses(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('themes'))
        self.assertEqual(self.names(r), ['vid_high', 'vid_low', 'dev_hot'])

    def test_manual_order_wins_in_both_languages(self):
        self.client.force_login(self.admin)
        order = [self.dev_hot.id, self.vid_low.id, self.vid_high.id]
        r = self.client.post(reverse('manage_theme_order_save'), json.dumps({'order': order}),
                             content_type='application/json')
        self.assertTrue(r.json()['success'])
        for url_name in ('themes', 'arabic_themes'):
            r = self.client.get(reverse(url_name))
            self.assertEqual(self.names(r), ['dev_hot', 'vid_low', 'vid_high'])

    def test_reset_returns_to_automatic(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('manage_theme_order_save'),
                         json.dumps({'order': [self.dev_hot.id, self.vid_low.id, self.vid_high.id]}),
                         content_type='application/json')
        self.client.post(reverse('manage_theme_order_save'), json.dumps({'reset': True}),
                         content_type='application/json')
        r = self.client.get(reverse('themes'))
        self.assertEqual(self.names(r), ['vid_high', 'vid_low', 'dev_hot'])

    def test_rejects_unknown_and_duplicate_ids(self):
        self.client.force_login(self.admin)
        url = reverse('manage_theme_order_save')
        r = self.client.post(url, json.dumps({'order': [self.vid_low.id, 99999]}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 404)
        r = self.client.post(url, json.dumps({'order': [self.vid_low.id, self.vid_low.id]}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Theme.objects.filter(display_order__isnull=False).exists())

    def test_non_superuser_is_blocked(self):
        self.client.force_login(self.user)
        self.assertNotEqual(self.client.get(reverse('manage_theme_order')).status_code, 200)
        r = self.client.post(reverse('manage_theme_order_save'), json.dumps({'reset': True}),
                             content_type='application/json')
        self.assertNotEqual(r.status_code, 200)

    def test_manage_page_renders_for_admin(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('manage_theme_order'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.names(r), ['vid_high', 'vid_low', 'dev_hot'])
