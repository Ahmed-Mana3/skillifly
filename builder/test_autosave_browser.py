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
from django.db import OperationalError
from django.test import override_settings

from unittest.mock import patch

from core.models import Link, PersonalInfo, Profile, Project, Skill
from core.test_onboarding_browser import LIVE_SETTINGS, RUN, YT, fake_fetch, fake_thumb
from core.testing_helpers import (
    TempMediaMixin, clear_cache, give_payment, make_editor, png_bytes, seed_themes, site_settings,
)

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
        # Link lookups (the card preview and the server's title/thumbnail) never leave the machine.
        for target, fn in (('core.oembed.fetch', fake_fetch), ('core.oembed.download_thumbnail', fake_thumb)):
            patcher = patch(target, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

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

    def wait_until(self, page, check, message, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if check():
                    return
            except OperationalError as exc:
                # The test database is one in-memory SQLite shared with the live server's
                # thread; reading while that thread writes reports "locked". Look again.
                if 'locked' not in str(exc):
                    raise
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

    def test_a_video_added_by_hand_is_created_once_and_then_updated(self):
        page = self.open_builder()
        page.locator('#panel-projects .bx-panel-head [data-action="add"][data-prefix="projects"]').click()
        field = page.locator('#projects-container input[name$="-name"]').first
        field.fill('Cut')
        self.wait_until(page, lambda: Project.objects.filter(user=self.user).exists(), 'video created')
        field.fill('Final cut')
        self.wait_until(page, lambda: self.titles() == ['Final cut'], 'video updated')
        self.wait_saved(page)
        self.assertEqual(Project.objects.filter(user=self.user).count(), 1, 'one row, not a duplicate')

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

    # --- video cards ---------------------------------------------------------------------

    def titles(self):
        return list(Project.objects.filter(user=self.user).values_list('title', flat=True))

    def test_paste_a_link_adds_a_filled_in_card(self):
        page = self.open_builder()
        page.wait_for_selector('#panel-projects.is-active')  # video editors land on their work
        page.fill('#bx-paste-input', YT)
        page.click('[data-action="paste-add"]')
        page.wait_for_selector('#projects-container .bx-vcard-title:text("Never Gonna Edit You Up")')
        self.wait_until(page, lambda: self.titles() == ['Never Gonna Edit You Up'], 'video saved with the title of its link')
        self.wait_until(page, lambda: bool(Project.objects.get(user=self.user).image), 'its thumbnail attached')
        self.wait_saved(page)
        self.shot(page, 'video-card', '#panel-projects')

    def test_videos_reorder_with_the_arrows(self):
        Project.objects.create(user=self.user, title='First', url=YT, order=0)
        Project.objects.create(user=self.user, title='Second', url=YT, order=1)
        page = self.open_builder()
        page.locator('#projects-container > .bx-item').nth(1).locator('[data-action="move-up"]').click()
        self.wait_until(page, lambda: self.titles() == ['Second', 'First'], 'new order saved')

    def test_details_open_and_close(self):
        Project.objects.create(user=self.user, title='Brand film', url=YT)
        page = self.open_builder()
        row = page.locator('#projects-container > .bx-item').first
        self.assertFalse(row.locator('[data-vcard-details]').is_visible(), 'a saved video starts folded')
        row.locator('[data-action="toggle-details"]').click()
        self.assertTrue(row.locator('[data-vcard-details]').is_visible())
        row.locator('textarea').fill('Edit and colour.')
        self.wait_until(page, lambda: Project.objects.get(user=self.user).details == 'Edit and colour.', 'role saved')

    # --- skills and links ------------------------------------------------------------------

    def test_skill_chips(self):
        page = self.open_builder()
        self.section(page, 'skills')
        preset = '.bx-skill-preset[data-skill="DaVinci Resolve"]'
        page.click(preset)
        page.fill('#bx-skill-new', 'Unreal Engine')
        page.press('#bx-skill-new', 'Enter')
        names = lambda: set(Skill.objects.filter(user=self.user).values_list('name', flat=True))
        self.wait_until(page, lambda: names() == {'DaVinci Resolve', 'Unreal Engine'}, 'preset and own skill saved')
        self.assertEqual(page.get_attribute(preset, 'aria-pressed'), 'true')
        self.assertEqual(page.locator('#skills-container .bx-item:visible').count(), 1, 'only the own skill shows as a chip')
        self.shot(page, 'skills', '#panel-skills')
        page.click(preset)  # untick: removed once the Undo window has passed
        self.wait_until(page, lambda: names() == {'Unreal Engine'}, 'preset removed', timeout=12)

    def test_a_pasted_link_names_itself(self):
        page = self.open_builder()
        self.section(page, 'links')
        page.locator('#panel-links [data-action="add"][data-prefix="links"]').first.click()
        page.locator('#links-container input[name$="-url"]').first.fill('instagram.com/sara')
        self.wait_until(page, lambda: Link.objects.filter(user=self.user, platform='Instagram').exists(), 'link saved by name')
        self.assertEqual(page.inner_text('#links-container [data-link-platform]'), 'Instagram')

    # --- readiness, folded sections, Done ----------------------------------------------------

    def test_readiness_card_and_sections(self):
        page = self.open_builder()
        self.shot(page, 'new-user-desktop')
        self.assertIn('Client-ready 0/3', page.inner_text('#bx-ready'))
        page.click('.bx-ready-item[data-ready="contact"]')
        page.wait_for_selector('#panel-identity.is-active')
        self.assertFalse(page.is_visible('.bx-nav-item[data-nav-key="education"]'), 'empty extras are folded')
        page.click('.bx-nav-more')
        self.assertTrue(page.is_visible('.bx-nav-item[data-nav-key="education"]'))
        self.section(page, 'reviews')
        self.assertTrue(page.is_visible('#panel-reviews .bx-done-btn'), 'the last main section ends with Done')
        self.shot(page, 'sidebar-more', '.bx-sidebar')

    def test_keeping_the_default_title_counts(self):
        page = self.open_builder()
        self.section(page, 'identity')
        self.assertTrue(page.is_visible('[data-title-keep]'), 'offered under the default title')
        page.click('[data-action="keep-title"]')
        self.wait_until(page, lambda: PersonalInfo.objects.get(user=self.user).title_confirmed, 'title kept')
        self.assertFalse(page.is_visible('[data-title-keep]'))
        self.assertIn('is-done', page.get_attribute('.bx-ready-item[data-ready="title"]', 'class'))

    def test_client_ready_offers_publish(self):
        for i in range(3):
            Project.objects.create(user=self.user, title=f'Video {i}', url=YT, order=i)
        PersonalInfo.objects.filter(user=self.user).update(title='Colorist', booking_url='https://wa.me/201001234567')
        page = self.open_builder()
        page.wait_for_selector('#bx-ready.is-ready')
        self.assertIn('Ready to send to clients.', page.inner_text('#bx-ready'))
        self.assertFalse(page.is_visible('#bx-ready [data-ready-todo]'), 'the checklist folds once done')
        self.assertTrue(page.is_visible('.bx-header [data-publish]'), 'Publish is the top bar action')
        self.shot(page, 'ready', '#bx-ready')
        self.shot(page, 'work-desktop')
        mobile = self.open_builder(width=390, height=844)
        self.assertLessEqual(mobile.evaluate('document.documentElement.scrollWidth'), 391, 'no sideways scroll')
        self.shot(mobile, 'work-mobile')

    # --- copy link -------------------------------------------------------------------

    def go_live(self):
        give_payment(self.user)
        Profile.objects.filter(user=self.user).update(is_public=True)

    def test_copy_link_confirms_on_the_page_not_in_a_browser_dialog(self):
        self.go_live()
        page = self.open_builder()
        dialogs = []
        page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
        page.click('.bx-header [data-action="copy-link"]')
        page.wait_for_selector('.bx-header [data-action="copy-link"].is-copied')
        page.wait_for_selector('.bx-toast:has-text("Link copied")')
        self.assertEqual(dialogs, [], 'no browser dialog')
        self.shot(page, 'copied', '.bx-header')

    def test_when_copying_is_blocked_the_link_shows_in_a_dialog(self):
        self.go_live()
        page = self.open_builder()
        dialogs = []
        page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
        # A browser that allows neither the clipboard API nor execCommand('copy').
        page.evaluate("""() => {
            Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
            document.execCommand = () => false;
        }""")
        page.click('.bx-header [data-action="copy-link"]')
        page.wait_for_selector('#bx-link-dialog.is-open')
        self.assertTrue(page.input_value('[data-link-dialog-url]').endswith('/sara/'))
        page.click('[data-action="copy-link-dialog"]')
        page.wait_for_selector('[data-link-dialog-hint]:visible')
        self.shot(page, 'copy-dialog')
        page.keyboard.press('Escape')
        page.wait_for_selector('#bx-link-dialog', state='hidden')
        self.assertEqual(dialogs, [], 'no browser dialog')

    def test_switched_off_the_save_button_still_saves_a_pasted_video(self):
        site_settings(builder_autosave_enabled=False)
        page = self.open_builder_without_autosave()
        page.fill('#bx-paste-input', YT)
        page.click('[data-action="paste-add"]')
        page.wait_for_selector('#projects-container .bx-vcard-title:text("Never Gonna Edit You Up")')
        page.locator('.bx-header [data-save-button]').click()
        self.wait_until(page, lambda: self.titles() == ['Never Gonna Edit You Up'], 'saved by the form')

    def open_builder_without_autosave(self):
        self.client.force_login(self.user)
        context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        context.add_cookies([{'name': 'sessionid', 'value': self.client.cookies['sessionid'].value,
                              'url': self.live_server_url}])
        page = context.new_page()
        page.set_default_timeout(20000)
        self.addCleanup(context.close)
        page.goto(self.live_server_url + '/builder/update/')
        return page

    # --- Arabic ----------------------------------------------------------------------

    def test_arabic_builder_saves_too(self):
        page = self.open_builder('/ar/update/')
        self.assertIn('تم حفظ كل التعديلات', page.inner_text('#bx-autosave-status'))
        self.section(page, 'identity')
        page.fill('#f-title', 'مصحح ألوان')
        self.wait_until(page, lambda: PersonalInfo.objects.get(user=self.user).title == 'مصحح ألوان', 'title saved')
        self.shot(page, 'header-arabic', '.bx-header')
        self.shot(page, 'arabic-desktop')
