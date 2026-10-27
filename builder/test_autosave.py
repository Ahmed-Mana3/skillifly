"""Builder autosave (SiteSettings.builder_autosave_enabled): the switch and the save-queue logic."""
import os
import shutil
import subprocess
import unittest

from django.conf import settings
from django.test import TestCase

from core.models import Profile
from core.testing_helpers import make_editor, seed_themes, site_settings


class AutosaveScriptLogicTests(unittest.TestCase):
    """Runs builder/js_tests/builder_autosave_check.js against the real builder_v2.js."""

    @unittest.skipUnless(shutil.which('node'), 'Node.js is not installed')
    def test_save_queue(self):
        script = os.path.join(settings.BASE_DIR, 'builder', 'js_tests', 'builder_autosave_check.js')
        result = subprocess.run([shutil.which('node'), script], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('autosave checks passed', result.stdout)


class AutosaveSwitchTests(TestCase):
    PAGES = ('/builder/', '/builder/update/', '/ar/builder/', '/ar/update/')

    def setUp(self):
        Profile.objects.create(user=make_editor(), theme=seed_themes()['Creative'])
        self.client.force_login(Profile.objects.get().user)

    def render(self, path):
        res = self.client.get(path)
        self.assertEqual(res.status_code, 200, path)
        return res.content.decode()

    def test_off_by_default_keeps_the_save_button(self):
        for path in self.PAGES:
            with self.subTest(path):
                html = self.render(path)
                self.assertNotIn('data-autosave', html)
                self.assertNotIn('id="bx-autosave-status"', html)
                self.assertIn('data-save-button', html)

    def test_on_marks_the_page_for_autosave(self):
        site_settings(builder_autosave_enabled=True)
        for path in self.PAGES:
            with self.subTest(path):
                html = self.render(path)
                self.assertIn('data-autosave="1" data-api-base="/builder/api/"', html)
                self.assertIn('id="bx-autosave-status"', html)
                # The Save buttons stay in the page for visitors without JavaScript; the
                # script hides them (body.bx-autosave-on).
                self.assertIn('data-save-button', html)

    def test_language_reaches_the_script(self):
        site_settings(builder_autosave_enabled=True)
        self.assertIn('data-lang="en"', self.render('/builder/update/'))
        self.assertIn('data-lang="ar"', self.render('/ar/update/'))
