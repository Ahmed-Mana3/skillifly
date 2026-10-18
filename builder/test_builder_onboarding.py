"""PR-7 builder changes: video editors start with their work and see a client-ready counter."""
import os
import shutil
import subprocess
import unittest

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from core.models import Category, Profile, Theme
from core.testing_helpers import make_editor, seed_themes


class BuilderScriptLogicTests(unittest.TestCase):
    """Runs builder/js_tests/builder_progress_check.js against the real builder_v2.js."""

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_section_order_and_client_ready_counter(self):
        script = os.path.join(settings.BASE_DIR, 'builder', 'js_tests', 'builder_progress_check.js')
        result = subprocess.run(
            [shutil.which('node'), script], capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('checks passed', result.stdout)


class BuilderProgressLabelTests(TestCase):
    def setUp(self):
        self.themes = seed_themes()
        self.user = make_editor()
        self.client.force_login(self.user)

    def test_video_editor_sees_client_ready_label_and_category(self):
        resp = self.client.get(reverse('update_portfolio'))
        self.assertContains(resp, 'data-category="video_editor"')
        self.assertContains(resp, 'Client-ready 0/3')
        self.assertNotContains(resp, '0 of 7 sections')

    def test_arabic_builder_label(self):
        resp = self.client.get(reverse('arabic_update_portfolio'))
        self.assertContains(resp, 'جاهز للعملاء 0/3')
        self.assertContains(resp, "clientReadyOf: 'جاهز للعملاء {done}/3'")

    def test_other_categories_keep_the_section_counter(self):
        dev_cat = Category.objects.create(name='Developer')
        dev_theme = Theme.objects.create(category=dev_cat, name='Minimal')
        Profile.objects.create(user=self.user, theme=dev_theme)
        resp = self.client.get(reverse('update_portfolio'))
        self.assertContains(resp, 'data-category="developer"')
        self.assertContains(resp, '0 of 7 sections')
        self.assertNotContains(resp, 'Client-ready 0/3')

    def test_builder_script_ships_the_new_order(self):
        path = os.path.join(settings.BASE_DIR, 'static', 'js', 'builder_v2.js')
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        self.assertIn("video_editor: ['identity', 'projects'", text)
