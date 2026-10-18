"""Minimal Gallery video-editor theme: templates, hero thumbnails, registries, shared player JS."""
import os
import re
import shutil
import subprocess
import unittest
from datetime import date

from django.conf import settings
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import Category, Creator, PersonalInfo, Profile, Project, ProjectCategory, Skill, Theme
from core.section_order import THEME_SECTION_DEFAULTS, section_layout_supported
from core.testing_helpers import give_payment, make_editor
from core.theme_colors import BACKGROUND_ENABLED_THEMES

TEMPLATE_DIR = os.path.join(settings.BASE_DIR, 'templates', 'portfolios', 'video_editor')
MAIN = 'portfolios/video_editor/video_editor_minimal_gallery.html'
YT_URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


def _read(name):
    with open(os.path.join(TEMPLATE_DIR, name), encoding='utf-8') as f:
        return f.read()


class TiltedGalleryScriptTests(unittest.TestCase):
    """Runs portfolios/js_tests/tilted_gallery_check.js against static/js/tilted_gallery.js."""

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_layout_maths_matches_the_original_component(self):
        script = os.path.join(settings.BASE_DIR, 'portfolios', 'js_tests', 'tilted_gallery_check.js')
        result = subprocess.run([shutil.which('node'), script], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('checks passed', result.stdout)


class MinimalGalleryRegistryTests(TestCase):
    def test_section_layout_and_colours_are_enabled(self):
        self.assertTrue(section_layout_supported('video_editor', 'minimal_gallery'))
        self.assertIn(('video_editor', 'minimal_gallery'), BACKGROUND_ENABLED_THEMES)

    def test_every_variant_template_exists(self):
        for suffix in ('', '_reels', '_long', '_detail', '_category'):
            with self.subTest(suffix=suffix):
                self.assertTrue(os.path.exists(os.path.join(TEMPLATE_DIR, f'video_editor_minimal_gallery{suffix}.html')))

    def test_shared_player_script_is_byte_identical_to_kinetic(self):
        # The workspace-root patch_*.py scripts bulk-edit these blocks across
        # every theme, so they must stay exactly as the other themes have them.
        reels, kinetic_reels = _read('video_editor_minimal_gallery_reels.html'), _read('video_editor_kinetic_reels.html')
        marker = '    <!-- YouTube IFrame API'
        self.assertEqual(reels[reels.index(marker):], kinetic_reels[kinetic_reels.index(marker):])
        self.assertIn('skillifly:cloudflare-player', reels)
        self.assertIn('Auto-reorder reels based on URL hash', reels)

        detail, kinetic_detail = _read('video_editor_minimal_gallery_detail.html'), _read('video_editor_kinetic_detail.html')
        marker = '    <script>'
        self.assertEqual(detail[detail.index(marker):], kinetic_detail[kinetic_detail.index(marker):])
        self.assertIn('skillifly:cloudflare-player', detail)

    def test_main_template_never_uses_a_blanket_animation_override(self):
        # A `* { animation-duration: … !important }` reduced-motion rule would run
        # the hero band's keyframes straight to their hidden end state.
        main = _read('video_editor_minimal_gallery.html')
        self.assertNotIn('animation-iteration-count', main)
        self.assertNotRegex(main, r'\*,\s*\*::before,\s*\*::after\s*\{\s*animation-duration')


class MinimalGalleryPageTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name='Video Editor')
        self.theme = Theme.objects.create(name='Minimal Gallery', category=self.category)
        self.user = make_editor(username='nour')
        give_payment(self.user)
        self.profile = Profile.objects.create(user=self.user, theme=self.theme, is_public=True)
        PersonalInfo.objects.create(user=self.user, full_name='Nour Hassan', title='Video Editor',
                                    email='nour@example.com', bio='I cut films and reels.')
        self.collection = ProjectCategory.objects.create(user=self.user, name='Commercials')

    def _project(self, title, video_type='long', **kwargs):
        kwargs.setdefault('category', self.collection)
        return Project.objects.create(user=self.user, title=title, video_type=video_type, **kwargs)

    def _get(self, name, **kwargs):
        return self.client.get(reverse(name, kwargs={'username': self.user.username, **kwargs}))

    def test_every_page_renders_with_the_theme_templates(self):
        film = self._project('Brand Film', image='projects/brand.jpg')
        self._project('Launch Reel', video_type='reel', url=YT_URL)
        pages = [
            ('preview', {}, MAIN),
            ('portfolio_reels', {}, 'portfolios/video_editor/video_editor_minimal_gallery_reels.html'),
            ('portfolio_long_videos', {}, 'portfolios/video_editor/video_editor_minimal_gallery_long.html'),
            ('portfolio_video_detail', {'slug': film.slug}, 'portfolios/video_editor/video_editor_minimal_gallery_detail.html'),
            ('portfolio_category_detail', {'category_id': self.collection.id},
             'portfolios/video_editor/video_editor_minimal_gallery_category.html'),
        ]
        for name, kwargs, template in pages:
            with self.subTest(page=name):
                response = self._get(name, **kwargs)
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template)
                self.assertContains(response, 'Brand Film' if name != 'portfolio_reels' else 'Launch Reel')

    def test_hero_band_lists_uploaded_and_youtube_thumbnails(self):
        self._project('With image', image='projects/one.jpg')
        self._project('YouTube only', url=YT_URL)
        self._project('No thumbnail', url='https://example.com/video.mp4')
        content = self._get('preview').content.decode()
        sources = re.findall(r'<li data-src="([^"]+)"', content)
        self.assertEqual(sources, [
            reverse('image_thumb', args=['projects/one.jpg', 960]),
            'https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg',
        ])
        self.assertIn('id="mgCurve"', content)
        self.assertIn('js/tilted_gallery.js', content)

    def test_hero_band_is_capped_at_twelve_images(self):
        for i in range(15):
            self._project(f'Film {i}', image=f'projects/film{i}.jpg')
        content = self._get('preview').content.decode()
        self.assertEqual(len(re.findall(r'<li data-src=', content)), 12)

    def test_portfolio_without_projects_gets_a_typographic_hero(self):
        response = self._get('preview')
        self.assertContains(response, 'class="mg-hero is-flat"')
        self.assertNotContains(response, 'id="mgCurve"')
        self.assertNotContains(response, 'id="projects"')

    def test_demo_stills_never_appear_on_a_real_portfolio(self):
        self._project('Brand Film', image='projects/brand.jpg')
        self._project('Launch Reel', video_type='reel', image='projects/reel.jpg')
        for name in ('preview', 'portfolio_reels', 'portfolio_long_videos'):
            with self.subTest(page=name):
                self.assertNotContains(self._get(name), 'minimal_gallery/still-')

    def test_sections_render_in_the_registry_order(self):
        self._project('Brand Film', image='projects/brand.jpg')
        Skill.objects.create(user=self.user, name='DaVinci Resolve')
        self.user.experiences.create(title='Editor', company='Studio', start_date=date(2020, 1, 1), duration=2)
        self.user.education.create(school='Film School', degree='BA', field='Film', grade_year=date(2019, 6, 1))
        Creator.objects.create(user=self.user, name='A Creator')
        content = self._get('preview').content.decode()
        body = content[content.index('class="portfolio-body"'):]
        present = [key for key in THEME_SECTION_DEFAULTS[('video_editor', 'minimal_gallery')]
                   if f'<section id="{key}"' in body]
        self.assertEqual(present, ['projects', 'skills', 'experience', 'education', 'creators', 'contact'])
        positions = [body.index(f'<section id="{key}"') for key in present]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn('id="links"', body)

    def test_filter_chips_and_project_ids(self):
        other = ProjectCategory.objects.create(user=self.user, name='Music Videos')
        film = self._project('Brand Film', image='projects/brand.jpg')
        reel = self._project('Clip', video_type='reel', category=other)
        content = self._get('preview').content.decode()
        self.assertIn('id="mgFilters"', content)
        self.assertIn(f'data-filter="{other.id}"', content)
        self.assertIn(f'data-project-id="{film.id}"', content)
        self.assertIn(f'href="/{self.user.username}/reels/#reel-{reel.id}"', content)
        self.assertIn(f'href="/{self.user.username}/long-videos/{film.slug}/"', content)

    def test_custom_section_names_and_default_headings(self):
        self._project('Brand Film')
        Skill.objects.create(user=self.user, name='Premiere Pro')
        response = self._get('preview')
        self.assertContains(response, 'Selected Works')
        self.assertContains(response, 'Enquiries')
        self.profile.section_names = {'projects': {'label': 'Showreel'}, 'contact': {'label': 'Say hello'}}
        self.profile.save()
        response = self._get('preview')
        self.assertContains(response, 'Showreel')
        self.assertContains(response, 'Say hello')
        self.assertNotContains(response, 'Selected Works')

    def test_skills_render_once_inside_the_marquee(self):
        # The page ships each skill once; the marquee's clones are added client-side
        # and marked aria-hidden, so screen readers hear the list a single time.
        for name in ('Premiere Pro', 'DaVinci Resolve'):
            Skill.objects.create(user=self.user, name=name)
        content = self._get('preview').content.decode()
        self.assertIn('id="mgMarquee"', content)
        self.assertEqual(content.count('<li class="mg-skill">Premiere Pro</li>'), 1)
        self.assertEqual(content.count('<li class="mg-skill">DaVinci Resolve</li>'), 1)

    def test_main_page_query_count_does_not_grow_with_projects(self):
        self._project('First', image='projects/a.jpg')
        self._project('Second', video_type='reel', url=YT_URL)
        with CaptureQueriesContext(connection) as few:
            self._get('preview')
        for i in range(20):
            self._project(f'Film {i}', video_type='reel' if i % 2 else 'long', image=f'projects/f{i}.jpg')
        with CaptureQueriesContext(connection) as many:
            self._get('preview')
        self.assertEqual(len(many), len(few))

    def test_detail_keeps_the_collection_filter_on_up_next_links(self):
        film = self._project('Brand Film')
        other = self._project('Second Film')
        response = self.client.get(
            reverse('portfolio_video_detail', kwargs={'username': self.user.username, 'slug': film.slug}),
            {'category_id': self.collection.id})
        self.assertContains(response, f'/long-videos/{other.slug}/?category_id={self.collection.id}')


class MinimalGalleryPreviewRouteTests(TestCase):
    def setUp(self):
        category = Category.objects.create(name='Video Editor')
        self.gallery = Theme.objects.create(name='Minimal Gallery', category=category)
        self.minimal = Theme.objects.create(name='Minimal', category=category)

    def test_theme_preview_uses_demo_stills(self):
        response = self.client.get(reverse('theme_preview', kwargs={'theme_name': 'minimal-gallery'}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, MAIN)
        content = response.content.decode()
        self.assertEqual(len(re.findall(r'<li data-src="[^"]*minimal_gallery/still-0\d\.webp"', content)), 8)
        self.assertIn('Alex', content)

    def test_minimal_preview_still_resolves_to_minimal(self):
        response = self.client.get(reverse('theme_preview', kwargs={'theme_name': 'minimal'}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'portfolios/video_editor/video_editor_minimal.html')
        self.assertTemplateNotUsed(response, MAIN)
