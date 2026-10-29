"""
Real-browser checks for the onboarding UI (Playwright + Chromium).

Opt-in because it needs the Chromium binary and network access for the Tailwind CDN:

    $env:SKILLIFLY_BROWSER_TESTS = "1"
    manage.py test core.test_onboarding_browser

Runs against Django's live test server (isolated test database, never db.sqlite3) and
writes screenshots to $SKILLIFLY_SCREENSHOT_DIR (default: a temp folder, path printed).
"""
import os
import tempfile
from unittest import skipUnless
from unittest.mock import patch

# Playwright's sync API runs an event loop; Django's ORM guard would otherwise refuse
# database calls from the test thread.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.files.base import ContentFile
from django.test import override_settings

from core.models import PersonalInfo, Profile, Project
from core.oembed import VideoMeta
from core.testing_helpers import (
    TempMediaMixin, clear_cache, make_editor, png_bytes, seed_themes, site_settings,
)

RUN = os.environ.get('SKILLIFLY_BROWSER_TESTS') == '1'
YT = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
VIMEO = 'https://vimeo.com/76979871'
SHOTS = os.environ.get('SKILLIFLY_SCREENSHOT_DIR') or os.path.join(tempfile.gettempdir(), 'skillifly-onboarding-shots')

LIVE_SETTINGS = dict(
    SESSION_COOKIE_DOMAIN=None, CSRF_COOKIE_DOMAIN=None,
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=['*'],
)


def fake_fetch(url):
    if 'private' in url:
        return VideoMeta(url=url, provider='youtube', ok=False, error='private')
    if 'vimeo' in url:
        return VideoMeta(
            url=url, provider='vimeo', title='Alpine Timelapse', video_type='long',
            thumbnail_url='https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg',
            thumbnail_candidates=['https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg'],
        )
    return VideoMeta(
        url=url, provider='youtube', title='Never Gonna Edit You Up', video_type='long',
        thumbnail_url='https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg',
        thumbnail_candidates=['https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg'],
    )


def fake_thumb(meta):
    return ContentFile(png_bytes(640, 360), name='oembed_browser.png')


@skipUnless(RUN, 'set SKILLIFLY_BROWSER_TESTS=1 to run the Playwright browser tests')
@override_settings(**LIVE_SETTINGS)
class OnboardingBrowserTests(TempMediaMixin, StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from playwright.sync_api import sync_playwright
        os.makedirs(SHOTS, exist_ok=True)
        cls.pw = sync_playwright().start()
        # channel='chromium' uses the full Chromium build (new headless mode) rather than
        # the separate headless-shell download, which is often missing on dev machines.
        cls.browser = cls.pw.chromium.launch(channel='chromium')
        print(f'\n[browser tests] screenshots -> {SHOTS}')

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        super().tearDownClass()

    def setUp(self):
        clear_cache()
        self.themes = seed_themes()
        site_settings(onboarding_v2_enabled=True)
        self.user = make_editor()
        for target, fn in (('core.oembed.fetch', fake_fetch), ('core.oembed.download_thumbnail', fake_thumb)):
            patcher = patch(target, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    # -- helpers --------------------------------------------------------------

    def open_page(self, width=1280, height=820, bypass_welcome_redirect=False, user=None):
        self.client.force_login(user or self.user)
        if bypass_welcome_redirect:
            session = self.client.session
            session['welcome_routed'] = True
            session.save()
        context = self.browser.new_context(viewport={'width': width, 'height': height})
        context.add_cookies([{
            'name': 'sessionid', 'value': self.client.cookies['sessionid'].value,
            'url': self.live_server_url,
        }])
        page = context.new_page()
        page.set_default_timeout(20000)
        self.watch_js_errors(page)
        self.addCleanup(context.close)
        return page

    def watch_js_errors(self, page):
        """Fail the test on any uncaught exception thrown by the page's own scripts."""
        errors = []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        self.addCleanup(lambda: self.assertEqual(errors, [], 'uncaught JavaScript errors'))

    def shot(self, page, name, full=False):
        page.screenshot(path=os.path.join(SHOTS, f'{name}.png'), full_page=full)

    def paste(self, page, row_index, url):
        inputs = page.locator('[data-url]')
        inputs.nth(row_index).fill(url)
        card = page.locator('[data-row]').nth(row_index).locator('[data-card]')
        return card

    # -- tests ---------------------------------------------------------------

    def test_welcome_to_reveal_flow_on_desktop(self):
        page = self.open_page()
        page.goto(f'{self.live_server_url}/welcome/?from=dashboard')
        self.assertIn('Start with your best edit', page.inner_text('h1'))
        self.assertTrue(page.locator('#wl-submit').is_disabled(), 'submit waits for a link')
        self.shot(page, '01-welcome-desktop-empty')

        # Paste a link -> live preview card with the title filled in.
        card = self.paste(page, 0, YT)
        page.wait_for_function("document.querySelector('[data-title]').value.length > 0")
        self.assertEqual(page.input_value('[data-title]'), 'Never Gonna Edit You Up')
        self.assertTrue(card.is_visible())
        self.assertFalse(page.locator('#wl-submit').is_disabled())
        self.assertEqual(page.input_value('[data-type]'), 'long')

        # Switch to Reel, add a second video.
        page.click('[data-type-btn="reel"]')
        self.assertEqual(page.input_value('[data-type]'), 'reel')
        page.click('#wl-add')
        self.assertEqual(page.locator('[data-row]').count(), 2)
        self.paste(page, 1, VIMEO)
        page.wait_for_function("document.querySelectorAll('[data-title]')[1].value.length > 0")
        self.shot(page, '02-welcome-desktop-two-links')

        # Submit -> own portfolio with the owner-only bar.
        page.click('#wl-submit')
        page.wait_for_url('**welcome=1**')
        page.wait_for_selector('#sfw-bar')
        self.assertIn('This is your portfolio, Sara.', page.inner_text('#sfw-bar'))
        self.assertIn('Client-ready 0/3', page.inner_text('#sfw-bar'))
        self.shot(page, '03-reveal-desktop')

        projects = list(Project.objects.filter(user=self.user).order_by('id'))
        self.assertEqual([p.title for p in projects], ['Never Gonna Edit You Up', 'Alpine Timelapse'])
        self.assertEqual([p.video_type for p in projects], ['reel', 'long'])
        self.assertTrue(all(p.image for p in projects))
        self.assertEqual(PersonalInfo.objects.get(user=self.user).title, 'Video Editor')

        # Try another look: one tap, still on the reveal.
        page.click('#sfw-bar >> text=Pro')
        page.wait_for_selector('#sfw-bar')
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Pro'])
        self.shot(page, '04-reveal-pro-theme')

        # Dismiss.
        page.click('.sfw-close')
        self.assertEqual(page.locator('#sfw-bar').count(), 0)

    def test_private_video_blocks_submit_with_a_message(self):
        page = self.open_page()
        page.goto(f'{self.live_server_url}/welcome/')
        self.paste(page, 0, 'https://www.youtube.com/watch?v=private123')
        page.wait_for_function("document.querySelector('[data-msg]').textContent.includes('private')")
        self.assertTrue(page.locator('#wl-submit').is_disabled())
        self.shot(page, '05-welcome-private-error')
        # Fixing the link re-enables it.
        self.paste(page, 0, YT)
        page.wait_for_function("!document.querySelector('#wl-submit').disabled")

    def test_skip_goes_to_the_first_run_dashboard(self):
        page = self.open_page()
        page.goto(f'{self.live_server_url}/welcome/')
        page.click('text=Skip for now')
        page.wait_for_url('**/dashboard/')
        self.assertIn('Add your first video', page.inner_text('body'))
        self.assertEqual(page.locator('#visibility').count(), 0)
        self.shot(page, '06-dashboard-first-run', full=True)

    def test_dashboard_redirects_new_editor_to_welcome(self):
        page = self.open_page()
        page.goto(f'{self.live_server_url}/dashboard/')
        page.wait_for_url('**/welcome/**')
        self.assertIn('from=dashboard', page.url)

    def test_mobile_layout(self):
        page = self.open_page(width=390, height=844)
        page.goto(f'{self.live_server_url}/welcome/')
        self.paste(page, 0, YT)
        page.wait_for_function("document.querySelector('[data-title]').value.length > 0")
        self.shot(page, '07-welcome-mobile', full=True)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 391, 'no horizontal scroll')
        # The demo iframe is skipped on small screens to save data.
        self.assertEqual(page.evaluate("document.querySelector('.wl-demo iframe').getAttribute('src')"), None)

        page.click('#wl-submit')
        page.wait_for_selector('#sfw-bar')
        self.shot(page, '08-reveal-mobile')
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 391)
        bar_height = page.evaluate("document.getElementById('sfw-bar').getBoundingClientRect().height")
        self.assertLess(bar_height, 844 * 0.6, 'the bar must not cover most of the screen')
        for box in page.locator('#sfw-bar .sfw-btn').all():
            self.assertGreaterEqual(box.bounding_box()['height'], 43, 'tap targets stay >= 44px')
        page.click('.sfw-close')
        self.assertEqual(page.locator('#sfw-bar').count(), 0)

    def test_arabic_welcome_is_rtl(self):
        page = self.open_page()
        page.goto(f'{self.live_server_url}/ar/welcome/')
        self.assertEqual(page.evaluate('document.documentElement.dir'), 'rtl')
        self.assertIn('ابدأ بأقوى فيديو في أعمالك', page.inner_text('h1'))
        self.assertEqual(page.get_attribute('[data-url]', 'dir'), 'ltr')
        self.paste(page, 0, YT)
        page.wait_for_function("document.querySelector('[data-title]').value.length > 0")
        self.shot(page, '09-welcome-arabic')
        page.click('#wl-submit')
        page.wait_for_url('**welcome=1**')
        page.wait_for_selector('#sfw-bar')
        self.assertEqual(page.get_attribute('#sfw-bar', 'dir'), 'rtl')
        self.assertIn('هذا معرض أعمالك يا Sara', page.inner_text('#sfw-bar'))
        self.shot(page, '10-reveal-arabic')

    def test_dashboard_next_step_card(self):
        for i in range(3):
            Project.objects.create(user=self.user, title=f'P{i}', url=YT)
        page = self.open_page(bypass_welcome_redirect=True)
        page.goto(f'{self.live_server_url}/dashboard/')
        self.assertIn('Add WhatsApp', page.inner_text('#next-step'))
        self.shot(page, '11-dashboard-next-step', full=True)

    def test_builder_starts_with_work_and_counts_client_readiness(self):
        page = self.open_page(bypass_welcome_redirect=True)
        page.goto(f'{self.live_server_url}/builder/update/')
        page.wait_for_selector('#panel-projects.is-active')
        # Opening the first section must not move the page or rewrite the URL.
        page.wait_for_timeout(600)   # smooth scrolling would have started by now
        self.assertEqual(page.evaluate('window.scrollY'), 0, 'builder must not auto-scroll on load')
        self.assertEqual(page.evaluate('location.hash'), '')
        self.assertTrue(page.locator('#bx-progress-label').is_visible())
        # Work showcase is section 1, identity section 2, and the counter is the client-ready one.
        # text_content, not inner_text: the kicker is CSS-uppercased.
        self.assertEqual(page.text_content('#panel-projects .bx-panel-kicker').strip(), 'Section 1')
        self.assertEqual(page.text_content('#panel-identity .bx-panel-kicker').strip(), 'Section 2')
        self.assertEqual(page.locator('#bx-nav li').first.locator('.bx-nav-name').text_content(), 'Work showcase')
        self.assertEqual(page.text_content('#bx-progress-label').strip(), 'Client-ready 0/3')
        self.shot(page, '13-builder-projects-first')

        # Pre-filled from signup, so the identity step needs no typing.
        page.click('[data-nav-key="identity"]')
        self.assertEqual(page.input_value('#f-fullname'), 'Sara Ali')
        self.assertEqual(page.input_value('#f-title'), 'Video Editor')
        page.fill('#f-title', 'Colorist')
        page.wait_for_function("document.getElementById('bx-progress-label').textContent.trim() === 'Client-ready 1/3'")
        page.fill('#f-booking', 'wa.me/201001234567')
        page.wait_for_function("document.getElementById('bx-progress-label').textContent.trim() === 'Client-ready 2/3'")

        # Three videos complete it.
        page.click('[data-nav-key="projects"]')
        for i in range(3):
            page.locator('.bx-panel.is-active [data-action="add"][data-prefix="projects"]').first.click()
            # The builder prepends new rows, so the newest one is always first.
            page.locator('#projects-container [name$="-name"]').first.fill(f'Cut {i + 1}')
        self.assertEqual(page.locator('#projects-container [name$="-name"]').count(), 3)
        page.wait_for_function("document.getElementById('bx-progress-label').textContent.trim() === 'Client-ready 3/3'")
        self.assertEqual(
            page.evaluate("document.getElementById('bx-progress-fill').style.width"), '100%',
        )
        self.shot(page, '14-builder-client-ready')

        # Removing one drops it back to 2/3.
        page.locator('#projects-container [data-action="remove-item"]').nth(2).click()
        page.wait_for_function("document.getElementById('bx-progress-label').textContent.trim() === 'Client-ready 2/3'")

    def test_builder_arabic_counter(self):
        page = self.open_page(bypass_welcome_redirect=True)
        page.goto(f'{self.live_server_url}/ar/update/')
        page.wait_for_selector('#panel-projects.is-active')
        self.assertEqual(page.text_content('#bx-progress-label').strip(), 'جاهز للعملاء 0/3')
        self.assertEqual(page.text_content('#panel-projects .bx-panel-kicker').strip(), 'القسم 1')
        self.shot(page, '15-builder-arabic')

    def test_add_more_videos_from_the_reveal_bar(self):
        Profile.objects.create(user=self.user, theme=self.themes['Creative'])
        PersonalInfo.objects.create(user=self.user, full_name='Sara Ali', title='Video Editor',
                                    email='', phone='', bio='')
        Project.objects.create(user=self.user, title='First cut', url=YT)
        page = self.open_page()
        page.goto(f'{self.live_server_url}/sara/?welcome=1')
        page.wait_for_selector('#sfw-bar')
        page.click('#sfw-bar >> text=Add more videos')
        page.wait_for_url('**/welcome/**add=1**')
        self.assertIn('Add more videos', page.inner_text('h1'))
        self.assertEqual(page.locator('text=Step 1 of 2').count(), 0)
        self.paste(page, 0, VIMEO)
        page.wait_for_function("document.querySelector('[data-title]').value.length > 0")
        self.shot(page, '16-add-more-videos')
        page.click('#wl-submit')
        page.wait_for_url('**welcome=1**')
        page.wait_for_selector('#sfw-bar')
        self.assertEqual(Project.objects.filter(user=self.user).count(), 2)
        self.assertEqual(PersonalInfo.objects.get(user=self.user).title, 'Video Editor')  # not recreated
        from core.models import ActivationEvent
        self.assertTrue(ActivationEvent.objects.filter(name='reveal_action', props__action='add').exists())

    def test_arabic_first_run_dashboard(self):
        page = self.open_page(bypass_welcome_redirect=True)
        page.goto(f'{self.live_server_url}/ar/dashboard/')
        self.assertIn('أضف أول فيديو لك', page.inner_text('#first-run-title'))
        self.assertEqual(page.evaluate('document.documentElement.dir'), 'rtl')
        self.assertEqual(page.locator('#visibility').count(), 0)
        href = page.get_attribute('#first-run-title ~ a', 'href')
        self.assertTrue(href.startswith('/ar/welcome/'), href)
        self.shot(page, '17-dashboard-first-run-arabic', full=True)

    def test_arabic_short_signup_suggests_a_username_from_the_email(self):
        self.client.logout()
        context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(20000)
        self.watch_js_errors(page)
        page.goto(f'{self.live_server_url}/ar/signup/')
        self.assertEqual(page.locator('#password2').count(), 0)
        page.fill('#full_name', 'نور حسن')            # Arabic names can't make a username
        self.assertEqual(page.input_value('#username'), '')
        page.fill('#email', 'nour.hassan@example.com')
        page.press('#email', 'Tab')                   # blur -> suggestion from the email
        self.assertEqual(page.input_value('#username'), 'nour-hassan')
        page.fill('#password1', 'Str0ng-pass-99')
        page.click('#toggle-password')
        self.assertEqual(page.get_attribute('#password1', 'type'), 'text')
        self.assertEqual(page.inner_text('#toggle-password').strip(), 'إخفاء')
        self.shot(page, '18-signup-short-arabic')

    def test_short_signup_form(self):
        self.client.logout()
        context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.addCleanup(context.close)
        page = context.new_page()
        page.set_default_timeout(20000)
        self.watch_js_errors(page)
        page.goto(f'{self.live_server_url}/signup/')
        self.assertEqual(page.locator('#password2').count(), 0)
        page.fill('#full_name', 'Nour Hassan')
        self.assertEqual(page.input_value('#username'), 'nour-hassan', 'username is suggested')
        page.fill('#username', 'nour_h')
        page.fill('#full_name', 'Nour A. Hassan')
        self.assertEqual(page.input_value('#username'), 'nour_h', 'a typed username is never overwritten')
        page.fill('#password1', 'Str0ng-pass-99')
        self.assertEqual(page.get_attribute('#password1', 'type'), 'password')
        page.click('#toggle-password')
        self.assertEqual(page.get_attribute('#password1', 'type'), 'text')
        page.click('#toggle-password')
        self.assertEqual(page.get_attribute('#password1', 'type'), 'password')
        self.shot(page, '12-signup-short')
