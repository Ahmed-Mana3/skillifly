from django.urls import reverse
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from core.models import Profile, Showcase

User = get_user_model()


class ShowcaseEntryManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='sadmin', email='sadmin@test.local', password='x', is_superuser=True, is_staff=True)
        self.u1 = User.objects.create_user(username='alice', email='alice@test.local', password='x')
        self.u2 = User.objects.create_user(username='bob', email='bob@test.local', password='x')
        self.p1 = Profile.objects.create(user=self.u1, is_public=True)
        self.p2 = Profile.objects.create(user=self.u2, is_public=True)
        self.c = Client()
        self.c.force_login(self.admin)

    def test_manage_page_lists_entries_and_candidates(self):
        Showcase.objects.create(profile=self.p1, title='One', order=0)
        resp = self.c.get(reverse('manage_dashboard'))
        self.assertContains(resp, 'Made with Skillifly')
        self.assertContains(resp, '@alice')
        self.assertContains(resp, reverse('manage_showcase_entry_toggle', args=[1]))
        self.assertContains(resp, 'name="username"')

    def test_add_entry(self):
        self.assertFalse(Showcase.objects.filter(profile=self.p2).exists())
        resp = self.c.post(reverse('manage_showcase_entry_add'), {'username': 'bob'})
        self.assertRedirects(resp, reverse('manage_dashboard'))
        sc = Showcase.objects.get(profile=self.p2)
        self.assertTrue(sc.is_active)
        resp2 = self.c.post(reverse('manage_showcase_entry_add'), {'username': 'bob'})
        self.assertRedirects(resp2, reverse('manage_dashboard'))
        self.assertEqual(Showcase.objects.filter(profile=self.p2).count(), 1)

    def test_add_entry_rejects_nonpublic_or_missing(self):
        u3 = User.objects.create_user(username='carol', email='carol@test.local', password='x')
        Profile.objects.create(user=u3, is_public=False)
        resp = self.c.post(reverse('manage_showcase_entry_add'), {'username': 'carol'})
        self.assertRedirects(resp, reverse('manage_dashboard'))
        self.assertFalse(Showcase.objects.filter(profile__user=u3).exists())
        resp2 = self.c.post(reverse('manage_showcase_entry_add'), {'username': 'nobody'})
        self.assertRedirects(resp2, reverse('manage_dashboard'))

    def test_toggle(self):
        sc = Showcase.objects.create(profile=self.p1, is_active=True, order=0)
        resp = self.c.post(reverse('manage_showcase_entry_toggle', args=[sc.pk]))
        self.assertRedirects(resp, reverse('manage_dashboard'))
        sc.refresh_from_db()
        self.assertFalse(sc.is_active)

    def test_move_reorders(self):
        a = Showcase.objects.create(profile=self.p1, order=0)
        b = Showcase.objects.create(profile=self.p2, order=1)
        resp = self.c.post(reverse('manage_showcase_entry_move', args=[a.pk, 'down']))
        self.assertRedirects(resp, reverse('manage_dashboard'))
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.order, 1)
        self.assertEqual(b.order, 0)

    def test_delete(self):
        sc = Showcase.objects.create(profile=self.p1, order=0)
        resp = self.c.post(reverse('manage_showcase_entry_delete', args=[sc.pk]))
        self.assertRedirects(resp, reverse('manage_dashboard'))
        self.assertFalse(Showcase.objects.filter(pk=sc.pk).exists())

    def test_superuser_gate(self):
        anon = Client()
        resp = anon.post(reverse('manage_showcase_entry_add'), {'username': 'bob'})
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn('manage_dashboard', resp.url)
        norm = Client()
        norm.force_login(self.u1)
        resp2 = norm.post(reverse('manage_showcase_entry_toggle', args=[0]))
        self.assertEqual(resp2.status_code, 302)
        self.assertNotIn('manage_dashboard', resp2.url)
