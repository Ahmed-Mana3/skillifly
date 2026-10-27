"""
Real-browser checks of builder autosave (Playwright + Chromium).

Opt-in, like the other browser tests (needs Chromium and network for the Tailwind CDN):

    $env:SKILLIFLY_BROWSER_TESTS = "1"
    manage.py test builder.test_autosave_browser

Every check reads the result back from the database, i.e. it would survive a reload.
Screenshots go to $SKILLIFLY_SCREENSHOT_DIR (default: a temp folder, path printed).
"""
import os
import tempfile
import time
from unittest import skipUnless

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from core.models import Link, PersonalInfo, Profile, Project, Skill
from core.test_onboarding_browser import LIVE_SETTINGS, RUN
from core.testing_helpers import TempMediaMixin, clear_cache, make_editor, png_bytes, seed_themes, site_settings

SHOTS = os.environ.get('SKILLIFLY_SCREENSHOT_DIR') or os.path.join(tempfile.gettempdir(), 'skillifly-autosave-shots')


@skipUnless(RUN, 'set SKILLIFLY_BROWSER_TESTS=1 to run the Playwright browser tests')
@override_settings(**LIVE_SETTINGS)
class AutosaveBrowserTests(TempMediaMixin, StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from playwright.sync_api import sync_playwright
        os.makedirs(SHOTS, exist_ok=True)
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel='chromium')
        print(f'\n[browser tests] screenshots -> {SHOTS}')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        super().tearDownClass()

    def setUp(self):
        clear_cache()
        site_settings(builder_autosave_enabled=True, launch_checklist_enabled=False)
        self.user = make_editor()
        Profile.objects.create(user=self.user, theme=seed_themes()['Creative'])
        PersonalInfo.objects.create(user=self.user, full_name='Sara Ali', title='Video Editor',
                                    email='', phone='', bio='')

    def open_builder(self, path='/builder/update/', width=1280, height=900):
        self.client.force_login(self.user)
        context = self.browser.new_context(viewport={'width': width, 'height': height})
        context.add_cookies([{'name': 'sessionid', 'value': self.client.cookies['sessionid'].value,
                              'url': self.live_server_url}])
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        self.addCleanup(lambda: self.assertEqual(errors, [], 'uncaught JavaScript errors'))
        self.addCleanup(context.close)
        page.goto(self.live_server_url + path)
        page.wait_for_selector('#bx-autosave-status:not([hidden])')
        return page

    def section(self, page, key):
        page.click(f'.bx-nav-item[data-nav-key="{key}"]')
        page.wait_for_selector(f'#panel-{key}.is-active')

    def state(self, page):
        return page.get_attribute('#bx-autosave-status', 'data-state')

    def wait_until(self, page, check, message, timeout=8):
        end = time.time() + timeout
        while time.time() < end:
            if check():
                return
            page.wait_for_timeout(150)
        self.fail(message)

    def wait_saved(self, page):
        page.wait_for_function("document.querySelector('#bx-autosave-status').dataset.state === 'saved'")

    def shot(self, page, name, selector=None):
        target = page.locator(selector) if selector else page
        target.screenshot(path=os.path.join(SHOTS, f'{name}.png'))

    # --- the page --------------------------------------------------------------

    def test_save_buttons_give_way_to_the_status_pill(self):
        page = self.open_builder()
        self.assertTrue(page.is_visible('#bx-autosave-status'))
        self.assertEqual(page.locator('[data-save-button]:visible').count(), 0, 'no Save buttons')
        self.assertIn('All changes saved', page.inner_text('#bx-autosave-status'))
        self.shot(page, 'header-desktop', '.bx-header')
        mobile = self.open_builder(width=390, height=844)
        self.assertLessEqual(mobile.evaluate('document.documentElement.scrollWidth'), 391, 'no sideways scroll')
        self.shot(mobile, 'header-mobile', '.bx-header')

    # --- saving ------------------------------------------------------------------

    def test_typing_saves_without_a_button(self):
        page = self.open_builder()
        self.section(page, 'identity')
        page.fill('#f-title', 'Colorist')
        page.wait_for_function("document.querySelector('#bx-autosave-status').dataset.state !== 'saved'")
        self.wait_saved(page)
        self.assertEqual(PersonalInfo.objects.get(user=self.user).title, 'Colorist')
        page.reload()
        self.assertEqual(page.input_value('#f-title'), 'Colorist')

    def test_new_skill_is_created_once_and_then_updated(self):
        page = self.open_builder()
        self.section(page, 'skills')
        page.locator('#panel-skills [data-action="add"][data-prefix="skills"]').first.click()
        field = page.locator('#skills-container input[name$="-skill"]').first
        field.fill('Premiere')
        self.wait_until(page, lambda: Skill.objects.filter(user=self.user).exists(), 'skill created')
        field.fill('Premiere Pro')
        self.wait_until(page, lambda: Skill.objects.filter(user=self.user, name='Premiere Pro').exists(),
                        'skill updated')
        self.wait_saved(page)
        self.assertEqual(Skill.objects.filter(user=self.user).count(), 1, 'one row, not a duplicate')

    def test_a_bad_booking_link_does_not_block_the_bio(self):
        page = self.open_builder()
        self.section(page, 'identity')
        page.fill('#f-booking', 'not a link')
        page.fill('#f-bio', 'I cut music videos.')
        self.wait_until(page, lambda: PersonalInfo.objects.get(user=self.user).bio == 'I cut music videos.',
                        'bio saved despite the bad booking link')
        page.wait_for_selector('#f-booking ~ .bx-field-error.is-visible')
        self.wait_until(page, lambda: self.state(page) == 'invalid', 'the pill reports the unsaved field')
        self.assertEqual(PersonalInfo.objects.get(user=self.user).booking_url or '', '')
        self.shot(page, 'booking-error')
        page.fill('#f-booking', 'calendly.com/sara')
        self.wait_until(page, lambda: PersonalInfo.objects.get(user=self.user).booking_url == 'https://calendly.com/sara',
                        'fixed booking link saved')
        self.wait_saved(page)

    def test_thumbnail_uploads_as_soon_as_it_is_chosen(self):
        project = Project.objects.create(user=self.user, title='Brand film')
        page = self.open_builder()
        self.section(page, 'projects')
        page.set_input_files('#projects-container input[name$="-thumbnail"]',
                             files=[{'name': 'thumb.png', 'mimeType': 'image/png', 'buffer': png_bytes()}])
        self.wait_until(page, lambda: bool(Project.objects.get(id=project.id).image), 'thumbnail stored')

    # --- removing ------------------------------------------------------------------

    def test_remove_waits_for_undo(self):
        kept = Link.objects.create(user=self.user, platform='Instagram', url='https://instagram.com/sara')
        gone = Link.objects.create(user=self.user, platform='X', url='https://x.com/sara')
        page = self.open_builder()
        self.section(page, 'links')
        rows = page.locator('#links-container .bx-item')
        rows.filter(has=page.locator(f'input[value="{kept.platform}"]')).locator('.bx-remove').click()
        page.click('.bx-toast-action')  # Undo
        rows.filter(has=page.locator(f'input[value="{gone.platform}"]')).locator('.bx-remove').click()
        self.wait_until(page, lambda: not Link.objects.filter(id=gone.id).exists(), 'removed link deleted', timeout=12)
        self.assertTrue(Link.objects.filter(id=kept.id).exists(), 'undone link kept')

    # --- Arabic ----------------------------------------------------------------------

    def test_arabic_builder_saves_too(self):
        page = self.open_builder('/ar/update/')
        self.assertIn('تم حفظ كل التعديلات', page.inner_text('#bx-autosave-status'))
        self.section(page, 'identity')
        page.fill('#f-title', 'مصحح ألوان')
        self.wait_until(page, lambda: PersonalInfo.objects.get(user=self.user).title == 'مصحح ألوان', 'title saved')
        self.shot(page, 'header-arabic', '.bx-header')
