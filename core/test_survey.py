from django.test import TestCase
from django.urls import reverse

from core import survey
from core.models import HeardAboutResponse
from core.testing_helpers import make_editor

URL = '/ar/survey/heard-about/'


class HeardAboutSurveyTests(TestCase):
    def setUp(self):
        self.user = make_editor('sara')
        self.client.force_login(self.user)

    def test_page_renders_in_arabic_with_all_options(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'كيف عرفت Skillifly؟')
        for key in survey.KEYS:
            self.assertContains(response, f'value="{key}"')

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(URL).status_code, 302)

    def test_answer_awards_25_xp_once(self):
        response = self.client.post(URL, {'source': 'instagram'})
        self.assertRedirects(response, URL + '?done=1')
        row = HeardAboutResponse.objects.get(user=self.user)
        self.assertEqual((row.source, row.xp_awarded), ('instagram', 25))

        # A second answer keeps the first and awards nothing more.
        again = self.client.post(URL, {'source': 'tiktok'})
        self.assertRedirects(again, URL)
        row.refresh_from_db()
        self.assertEqual((HeardAboutResponse.objects.count(), row.source), (1, 'instagram'))

        page = self.client.get(URL)
        self.assertContains(page, '+25 XP')
        self.assertContains(page, 'إنستجرام')

    def test_celebration_only_after_a_fresh_answer(self):
        self.client.post(URL, {'source': 'google'})
        self.assertTrue(self.client.get(URL + '?done=1').context['celebrate'])
        self.assertFalse(self.client.get(URL).context['celebrate'])

    def test_invalid_source_saves_nothing(self):
        response = self.client.post(URL, {'source': 'nope'}, follow=True)
        self.assertEqual(HeardAboutResponse.objects.count(), 0)
        self.assertContains(response, 'اختر إجابة')

    def test_detail_kept_only_for_options_that_ask_and_is_trimmed(self):
        self.client.post(URL, {'source': 'friend', 'detail': '  أحمد   علي  ' + 'x' * 500})
        row = HeardAboutResponse.objects.get()
        self.assertTrue(row.detail.startswith('أحمد علي'))
        self.assertLessEqual(len(row.detail), survey.MAX_DETAIL)

        other = make_editor('omar')
        self.assertEqual(survey.save(other, 'tiktok', 'ignored')[0].detail, '')

    def test_instagram_asks_for_the_creator(self):
        page = self.client.get(URL)
        self.assertContains(page, 'من هو صانع المحتوى')
        row = survey.save(make_editor('lina'), 'instagram', ' @creator ')[0]
        self.assertEqual(row.detail, '@creator')

    def test_manage_hub_links_to_survey_and_shows_counts(self):
        admin = make_editor('boss', is_superuser=True, is_staff=True)
        survey.save(self.user, 'youtube')
        survey.save(make_editor('omar'), 'youtube')
        survey.save(make_editor('lina'), 'friend', 'x')
        self.client.force_login(admin)
        page = self.client.get(reverse('manage_dashboard'))
        self.assertContains(page, reverse('arabic_heard_about'))
        self.assertContains(page, 'يوتيوب')
        self.assertEqual(page.context['heard_about']['total'], 3)
        self.assertEqual(page.context['heard_about']['rows'][0]['count'], 2)
