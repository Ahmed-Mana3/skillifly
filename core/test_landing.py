"""Landing pages (EN + AR) and the "claim your link" hand-off to signup."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Review


class LandingPageTests(TestCase):
    def test_english_landing_renders_conversion_paths(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/index.html')
        content = response.content.decode()
        # Claim form posts the handle to signup; pricing keeps the checkout hooks.
        self.assertIn('action="%s"' % reverse('signup'), content)
        self.assertIn('id="pro-cta"', content)
        self.assertIn(reverse('manual_payment', args=['pro_annual']), content)
        self.assertIn(reverse('manual_payment', args=['monthly']), content)
        self.assertIn('id="lp-pricing-i18n"', content)
        self.assertIn('id="theme-live-urls"', content)
        self.assertIn(reverse('hire_editors'), content)

    def test_arabic_landing_renders_rtl_with_arabic_links(self):
        response = self.client.get(reverse('arabic_landing'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'core/arabic_landing.html')
        content = response.content.decode()
        self.assertIn('<div class="lp" dir="rtl">', content)
        self.assertIn('action="%s"' % reverse('arabic_signup'), content)
        self.assertIn(reverse('arabic_manual_payment', args=['pro_annual']), content)
        self.assertIn(reverse('arabic_hire_editors'), content)


class LandingReviewsTests(TestCase):
    def make(self, name, content, order, featured=True):
        return Review.objects.create(user_name=name, content=content, order=order, is_featured=featured, rating=5)

    def test_hero_is_first_review_short_enough_to_feature(self):
        self.make('Long', 'x' * 500, 0)
        short = self.make('Short', 'A great platform for showing my edits to clients, fast and simple.', 1)
        self.make('Other', 'Also very good, I recommend it to every editor I know personally.', 2)
        self.make('Hidden', 'Not featured so it never shows on the landing page at all.', 3, featured=False)
        response = self.client.get(reverse('index'))
        self.assertEqual(response.context['review_hero'], short)
        self.assertEqual([r.user_name for r in response.context['review_rest']], ['Long', 'Other'])
        self.assertEqual(response.context['review_avg'], '5.0')
        self.assertEqual(response.context['review_count'], 3)
        self.assertContains(response, 'class="lp-hero-quote')
        self.assertContains(response, 'Average rating from 3 reviews')

    def test_no_reviews_hides_the_section(self):
        response = self.client.get(reverse('index'))
        self.assertIsNone(response.context['review_hero'])
        self.assertNotContains(response, 'class="lp-section lp-love"')


class ClaimedUsernamePrefillTests(TestCase):
    def test_signup_prefills_sanitised_handle(self):
        response = self.client.get(reverse('signup'), {'username': ' Ahmed  Kamel!<b>- '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].initial.get('username'), 'ahmed-kamelb')
        self.assertContains(response, 'value="ahmed-kamelb"')

    def test_arabic_signup_prefills_handle(self):
        response = self.client.get(reverse('arabic_signup'), {'username': 'sara_edits'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].initial.get('username'), 'sara_edits')

    def test_signup_without_handle_has_no_initial(self):
        response = self.client.get(reverse('signup'))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('username', response.context['form'].initial)

    def test_handle_with_only_invalid_characters_is_ignored(self):
        response = self.client.get(reverse('signup'), {'username': 'أحمد'})
        self.assertNotIn('username', response.context['form'].initial)


class CheckUsernameTests(TestCase):
    def check(self, value):
        response = self.client.get(reverse('check_username'), {'username': value})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        return response.json()

    def test_free_handle_is_available(self):
        data = self.check('Night Owl Edits')
        self.assertEqual(data, {'username': 'night-owl-edits', 'status': 'available', 'suggestions': []})

    def test_taken_handle_is_case_insensitive_and_offers_free_suggestions(self):
        User = get_user_model()
        User.objects.create(username='Sara_Edits', email='sara@example.com')
        User.objects.create(username='sara_edits-edits', email='sara2@example.com')
        data = self.check('sara_edits')
        self.assertEqual(data['status'], 'taken')
        self.assertTrue(data['suggestions'])
        self.assertNotIn('sara_edits-edits', data['suggestions'])
        for suggestion in data['suggestions']:
            self.assertFalse(User.objects.filter(username__iexact=suggestion).exists())

    def test_reserved_route_name_is_rejected(self):
        data = self.check('Launch')
        self.assertEqual(data['status'], 'reserved')
        self.assertTrue(data['suggestions'])

    def test_too_short_after_cleaning(self):
        self.assertEqual(self.check('a!').get('status'), 'short')
        self.assertEqual(self.check('أحمد')['status'], 'short')

    def test_post_is_not_allowed(self):
        self.assertEqual(self.client.post(reverse('check_username'), {'username': 'x'}).status_code, 405)
