from django.test import TestCase
from django.urls import reverse

from core import survey
from core.testing_helpers import make_editor


class HeardAboutTrackingTests(TestCase):
    def setUp(self):
        self.url = reverse('manage_heard_about')
        survey.save(make_editor('sara'), 'instagram', '@Creator')
        survey.save(make_editor('omar'), 'instagram', 'creator')
        survey.save(make_editor('lina'), 'friend', 'Ahmed')

    def test_superuser_only(self):
        self.client.force_login(make_editor('plain'))
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_lists_answers_and_ranks_creators(self):
        self.client.force_login(make_editor('boss', is_superuser=True, is_staff=True))
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['summary']['total'], 3)
        self.assertEqual(page.context['top_creators'], [('creator', 2)])
        self.assertContains(page, 'Ahmed')

    def test_filters_by_source_and_search(self):
        self.client.force_login(make_editor('boss', is_superuser=True, is_staff=True))
        page = self.client.get(self.url, {'source': 'friend'})
        self.assertEqual(page.context['result_count'], 1)
        page = self.client.get(self.url, {'q': 'omar'})
        self.assertEqual(page.context['result_count'], 1)
