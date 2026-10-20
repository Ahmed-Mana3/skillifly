"""Crimson video-editor theme: registries, public page, and the wheel markup."""
import os

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from core.models import Category, PersonalInfo, Profile, Project, Skill, Theme
from core.section_order import section_layout_supported
from core.testing_helpers import give_payment, make_editor
from core.theme_colors import BACKGROUND_ENABLED_THEMES

TEMPLATE = os.path.join(settings.BASE_DIR, 'templates', 'portfolios', 'video_editor', 'video_editor_crimson.html')
MAIN = 'portfolios/video_editor/video_editor_crimson.html'


class CrimsonRegistryTests(TestCase):
    def test_section_layout_and_colours_are_enabled(self):
        self.assertTrue(section_layout_supported('video_editor', 'crimson'))
        self.assertIn(('video_editor', 'crimson'), BACKGROUND_ENABLED_THEMES)

    def test_template_ships_the_override_partials(self):
        with open(TEMPLATE, encoding='utf-8') as f:
            source = f.read()
        self.assertIn('portfolios/common/section_layout_css.html', source)
        self.assertIn('portfolios/common/theme_background_css.html', source)
        self.assertIn('class="portfolio-body"', source)


class CrimsonPageTests(TestCase):
    def setUp(self):
        self.theme = Theme.objects.create(name='Crimson', category=Category.objects.create(name='Video Editor'))
        self.user = make_editor(username='rami')
        give_payment(self.user)
        Profile.objects.create(user=self.user, theme=self.theme, is_public=True)
        PersonalInfo.objects.create(user=self.user, full_name='Rami Adel', title='Colorist',
                                    email='rami@example.com', bio='Cuts and grades.')

    def _get(self):
        return self.client.get(reverse('preview', kwargs={'username': self.user.username}))

    def test_page_without_projects_has_no_wheel(self):
        response = self._get()
        self.assertTemplateUsed(response, MAIN)
        self.assertNotContains(response, '<div class="cr-stage-wrap"')
        self.assertContains(response, 'Rami Adel')

    def test_wheel_renders_a_card_per_project_with_the_right_links(self):
        film = Project.objects.create(user=self.user, title='Brand Film', video_type='long', image='projects/a.jpg')
        reel = Project.objects.create(user=self.user, title='Launch Reel', video_type='reel')  # no cover
        Skill.objects.create(user=self.user, name='DaVinci Resolve')
        response = self._get()
        self.assertTemplateUsed(response, MAIN)
        content = response.content.decode()
        self.assertEqual(content.count('<a class="cr-card" data-card'), 2)
        self.assertEqual(content.count('<button type="button" data-i="'), 2)
        self.assertIn(f'/rami/long-videos/{film.slug}/', content)
        self.assertIn(f'/rami/reels/#reel-{reel.id}', content)
        self.assertIn('cr-ph', content)  # the cover-less reel gets the placeholder
        self.assertIn('DaVinci Resolve', content)
