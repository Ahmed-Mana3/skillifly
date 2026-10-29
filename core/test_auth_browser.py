"""
Real-browser checks for the rebuilt sign-up / verify pages (Playwright + Chromium).

Opt-in, like core.test_onboarding_browser:

    $env:SKILLIFLY_BROWSER_TESTS = "1"
    manage.py test core.test_auth_browser
"""
import os
import tempfile
from unittest import skipUnless

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from core.models import EmailOTP
from core.testing_helpers import clear_cache, seed_themes, site_settings

RUN = os.environ.get('SKILLIFLY_BROWSER_TESTS') == '1'
SHOTS = os.environ.get('SKILLIFLY_SCREENSHOT_DIR') or os.path.join(tempfile.gettempdir(), 'skillifly-auth-shots')
LIVE_SETTINGS = dict(
    SESSION_COOKIE_DOMAIN=None, CSRF_COOKIE_DOMAIN=None,
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['*'],
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)


@skipUnless(RUN, 'set SKILLIFLY_BROWSER_TESTS=1 to run the Playwright browser tests')
@override_settings(**LIVE_SETTINGS)
class AuthBrowserTests(StaticLiveServerTestCase):
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
        seed_themes()
        site_settings()

    def page(self, path, width=1440, height=900):
        context = self.browser.new_context(viewport={'width': width, 'height': height})
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(20000)
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        self.addCleanup(lambda: self.assertEqual(errors, [], 'uncaught JavaScript errors'))
        page.goto(self.live_server_url + path)
        return page

    def test_link_is_checked_live_and_taken_links_offer_alternatives(self):
        get_user_model().objects.create_user('nour-hassan', 'other@example.com', None)
        page = self.page('/signup/')
        page.fill('#full_name', 'Nour Hassan')
        self.assertEqual(page.input_value('#username'), 'nour-hassan')
        self.assertEqual(page.inner_text('[data-preview-name]'), 'Nour Hassan')
        self.assertEqual(page.inner_text('[data-preview-handle]'), 'nour-hassan')
        page.wait_for_selector('#username-note.is-taken')
        chip = page.locator('#username-note .au-chip').first
        chip.click()
        page.wait_for_selector('#username-note.is-available')
        self.assertEqual(page.get_attribute('[data-link]', 'data-state'), 'available')
        page.screenshot(path=os.path.join(SHOTS, 'signup-live-check.png'))

    def test_taken_link_blocks_submit_without_a_round_trip(self):
        get_user_model().objects.create_user('taken-name', 'other@example.com', None)
        page = self.page('/signup/')
        page.fill('#full_name', 'Sara Ali')
        page.fill('#email', 'sara@example.com')
        page.fill('#username', 'taken-name')
        page.wait_for_selector('#username-note.is-taken')
        page.fill('#password1', 'Cut-the-reel-2026')
        page.click('[data-submit]')
        page.wait_for_timeout(300)
        self.assertTrue(page.url.endswith('/signup/'))
        self.assertFalse(get_user_model().objects.filter(email='sara@example.com').exists())

    def test_full_signup_then_paste_the_code(self):
        page = self.page('/signup/')
        page.fill('#full_name', 'Sara Ali')
        page.fill('#email', 'sara@example.com')
        page.wait_for_selector('#username-note.is-available')
        page.fill('#password1', 'Cut-the-reel-2026')
        self.assertEqual(page.get_attribute('[data-pw-meter]', 'data-score'), '4')
        page.click('[data-submit]')
        page.wait_for_url('**/verify-email/')
        code = EmailOTP.objects.get(user__email='sara@example.com').otp
        page.wait_for_selector('#otp-1')
        page.evaluate("""code => {
            const dt = new DataTransfer(); dt.setData('text', code);
            document.getElementById('otp-1').dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
        }""", code)
        page.wait_for_url('**/launch/**')   # auto-submitted, verified, signed in
        self.assertTrue(get_user_model().objects.get(email='sara@example.com').is_active)

    def test_screenshots_and_panel_motion(self):
        """Gallery for design review, plus the panel's style switcher and the valid-field tick."""
        page = self.page('/signup/')
        page.wait_for_timeout(1200)   # entrance animation + underline
        page.screenshot(path=os.path.join(SHOTS, 'a-signup-empty.png'))
        page.fill('#full_name', 'Nour Hassan')
        page.fill('#email', 'nour@example.com')
        page.press('#email', 'Tab')
        page.wait_for_selector('#username-note.is-available')
        self.assertIn('is-valid', page.get_attribute('#full_name >> xpath=ancestor::div[contains(@class,"au-field")]', 'class'))
        page.fill('#password1', 'Cut-the-reel-2026')
        page.click('[data-look="editorial"]')
        self.assertEqual(page.get_attribute('[data-preview-site]', 'data-look'), 'editorial')
        page.wait_for_timeout(700)
        page.screenshot(path=os.path.join(SHOTS, 'b-signup-filled-editorial.png'))
        page.click('[data-look="neon"]')
        page.wait_for_timeout(700)
        page.screenshot(path=os.path.join(SHOTS, 'c-signup-neon.png'))
        for path, name in (('/ar/signup/', 'd-signup-ar'), ('/signin/', 'e-signin'), ('/ar/signin/', 'f-signin-ar')):
            p = self.page(path)
            p.wait_for_timeout(1200)
            p.screenshot(path=os.path.join(SHOTS, f'{name}.png'))
        phone = self.page('/signup/', width=390, height=844)
        phone.wait_for_timeout(1000)
        phone.screenshot(path=os.path.join(SHOTS, 'g-signup-phone.png'), full_page=True)

    def test_signin_polish(self):
        get_user_model().objects.create_user('sara', 'sara@example.com', 'Cut-the-reel-2026')
        page = self.page('/signin/')
        page.wait_for_timeout(1200)
        page.screenshot(path=os.path.join(SHOTS, 'h-signin-clean.png'))
        page.fill('#email', 'sara@example.com')
        page.press('#email', 'Enter')            # empty password: Enter moves on instead of submitting
        self.assertTrue(page.url.endswith('/signin/'))
        self.assertEqual(page.evaluate('document.activeElement.id'), 'password')
        # Headless Chromium has no real Caps Lock state: send a key event that carries it.
        page.evaluate("""document.getElementById('password').dispatchEvent(
            new KeyboardEvent('keyup', {key: 'A', modifierCapsLock: true, bubbles: true}))""")
        self.assertTrue(page.locator('#password-caps').is_visible())
        page.evaluate("""document.getElementById('password').dispatchEvent(
            new KeyboardEvent('keyup', {key: 'a', bubbles: true}))""")
        self.assertTrue(page.locator('#password-caps').is_hidden())
        page.fill('#password', 'wrong-password')
        page.press('#password', 'Enter')
        page.wait_for_selector('form .au-alert')
        page.wait_for_timeout(600)
        page.screenshot(path=os.path.join(SHOTS, 'i-signin-error.png'))
        self.assertEqual(page.input_value('#email'), 'sara@example.com')
        self.assertEqual(page.evaluate('document.activeElement.id'), 'password')
        page.fill('#password', 'Cut-the-reel-2026')
        page.press('#password', 'Enter')
        page.wait_for_url('**/dashboard/**')
        ar = self.page('/ar/signin/')
        ar.wait_for_timeout(1200)
        ar.screenshot(path=os.path.join(SHOTS, 'j-signin-ar.png'))
        phone = self.page('/signin/', width=390, height=844)
        phone.wait_for_timeout(1000)
        phone.screenshot(path=os.path.join(SHOTS, 'k-signin-phone.png'))

    def test_last_used_badge(self):
        page = self.page('/signin/')
        self.assertTrue(page.locator('[data-last-for="email"]').is_hidden())
        page.evaluate("localStorage.setItem('skillifly-last-auth', 'email')")
        page.reload()
        self.assertTrue(page.locator('[data-last-for="email"]').is_visible())

    def test_phone_layout_has_no_sideways_scroll(self):
        for path in ('/signup/?username=a-very-long-handle-for-testing', '/ar/signup/', '/signin/', '/ar/signin/'):
            page = self.page(path, width=360, height=780)
            width = page.evaluate('document.documentElement.scrollWidth')
            self.assertLessEqual(width, 360, path)
        page.screenshot(path=os.path.join(SHOTS, 'signin-ar-phone.png'))
