"""
Real-browser walk through the launch checklist (Playwright + Chromium).

Opt-in, like core.test_onboarding_browser (needs Chromium and network for the Tailwind CDN):

    $env:SKILLIFLY_BROWSER_TESTS = "1"
    manage.py test core.test_launch_browser

Screenshots go to $SKILLIFLY_SCREENSHOT_DIR (default: a temp folder, path printed).
"""
import os
import tempfile
from unittest import skipUnless
from unittest.mock import patch

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from core.models import PersonalInfo, Profile, Project, Skill, UserAccount
from core.test_onboarding_browser import LIVE_SETTINGS, RUN, YT, fake_fetch, fake_thumb
from core.testing_helpers import TempMediaMixin, clear_cache, make_editor, png_bytes, seed_themes, site_settings

SHOTS = os.environ.get('SKILLIFLY_SCREENSHOT_DIR') or os.path.join(tempfile.gettempdir(), 'skillifly-launch-shots')


@skipUnless(RUN, 'set SKILLIFLY_BROWSER_TESTS=1 to run the Playwright browser tests')
@override_settings(**LIVE_SETTINGS)
class LaunchBrowserTests(TempMediaMixin, StaticLiveServerTestCase):
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
        self.themes = seed_themes()
        site_settings()
        self.user = make_editor()
        UserAccount.objects.filter(user=self.user).update(launch_status='active')
        for target, fn in (('core.oembed.fetch', fake_fetch), ('core.oembed.download_thumbnail', fake_thumb)):
            patcher = patch(target, side_effect=fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def open_page(self, width=1280, height=860):
        self.client.force_login(self.user)
        context = self.browser.new_context(viewport={'width': width, 'height': height})
        context.add_cookies([{'name': 'sessionid', 'value': self.client.cookies['sessionid'].value,
                              'url': self.live_server_url}])
        page = context.new_page()
        page.set_default_timeout(20000)
        errors, missing = [], []
        page.on('pageerror', lambda exc: errors.append(str(exc)))
        # Launch pages must not reference missing static files (portfolio themes are checked elsewhere).
        page.on('response', lambda r: missing.append(r.url) if r.status == 404 and '/static/' in r.url
                and ('/launch/' in (r.frame.url if r.frame else '') ) else None)
        self.addCleanup(lambda: self.assertEqual(errors, [], 'uncaught JavaScript errors'))
        self.addCleanup(lambda: self.assertEqual(missing, [], 'missing static files on launch pages'))
        self.addCleanup(context.close)
        return page

    def shot(self, page, name, full=False):
        page.screenshot(path=os.path.join(SHOTS, f'{name}.png'), full_page=full)

    def no_sideways_scroll(self, page, width):
        offenders = page.evaluate("""(w) => Array.from(document.querySelectorAll('body *'))
            .filter(el => { const r = el.getBoundingClientRect(); return r.width && (r.right > w + 1 || r.left < -1); })
            .filter(el => !el.closest('.lx-bg'))
            .slice(0, 8).map(el => el.tagName + '.' + el.className + ' ' + Math.round(el.getBoundingClientRect().right))""", width)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), width + 1,
                             f'no horizontal scroll; wide elements: {offenders}')

    def wait_for_toast(self, page):
        page.wait_for_selector('#lc-toast.is-in')
        page.wait_for_timeout(1200)  # let the progress bar finish growing

    def seed_done(self, *steps):
        if 'personal' in steps:
            PersonalInfo.objects.create(user=self.user, full_name='Sara Ali', title='Colorist', email='', phone='', bio='')
        if 'project' in steps:
            Project.objects.create(user=self.user, title='Never Gonna Edit You Up', url=YT)
        if 'theme' in steps:
            UserAccount.objects.filter(user=self.user).update(launch_theme_picked=True)
        if 'skills' in steps:
            Skill.objects.create(user=self.user, name='CapCut')

    # -- the whole flow, desktop -----------------------------------------------

    def test_full_flow_desktop(self):
        page = self.open_page()
        page.goto(f'{self.live_server_url}/dashboard/')
        page.wait_for_url('**/launch/')
        self.assertEqual(page.locator('h1').count(), 0, 'the greeting is hidden on the first visit')
        page.wait_for_timeout(1100)
        self.shot(page, '01-checklist-start')

        # Step 1: about you
        page.click('.lc-current .btn-primary')
        page.wait_for_url('**/launch/about-you/')
        self.assertEqual(page.input_value('#ls-name'), 'Sara Ali')
        page.click('[data-title-chip="Colorist"]')
        self.assertEqual(page.input_value('#ls-title'), 'Colorist')
        page.fill('#ls-bio', 'I edit fast-paced YouTube videos and brand reels that keep viewers watching.')
        page.fill('#ls-contact', '+20 100 123 4567')
        page.set_input_files('#ls-picture', files=[{'name': 'me.png', 'mimeType': 'image/png', 'buffer': png_bytes(400, 400)}])
        self.assertEqual(page.inner_text('[data-pv="title"]'), 'Colorist')
        self.assertTrue(page.locator('[data-pv-hire]').is_visible())
        self.shot(page, '02-about-you')
        page.click('#ls-submit')
        page.wait_for_url('**/launch/**')
        self.wait_for_toast(page)
        self.assertIn('Nice to meet you!', page.inner_text('#lc-toast'))
        self.assertIn('+25 XP', page.inner_text('#lc-toast'))
        self.assertEqual(page.inner_text('[data-xp]'), '25', 'the XP counter counted up')
        self.assertNotIn('done=', page.url, 'the celebration is not replayed on refresh')
        self.shot(page, '03-checklist-after-step-1')
        info = PersonalInfo.objects.get(user=self.user)
        self.assertEqual((info.title, info.booking_url), ('Colorist', 'https://wa.me/201001234567'))
        self.assertTrue(Profile.objects.get(user=self.user).picture)

        # Step 2: first video. Reel is the default; a horizontal YouTube link only offers to switch.
        page.click('.lc-current .btn-primary')
        page.wait_for_url('**/launch/first-video/')
        page.fill('[data-url]', YT)
        page.wait_for_function("document.querySelector('[data-title]').value.length > 0")
        self.assertEqual(page.input_value('[data-type]'), 'reel')
        self.assertTrue(page.locator('[data-type-hint]').is_visible(), 'offers Long video for a horizontal link')
        mockup = page.locator('[data-thumb-box]').bounding_box()
        self.assertAlmostEqual(mockup['width'] / mockup['height'], 4 / 5, delta=0.02, msg='reel thumbnails show at 4:5')
        # "Add thumbnail" sits on the mockup once there is a title, and goes away without one.
        self.assertTrue(page.locator('[data-thumb-add]').is_visible())
        page.fill('[data-title]', '')
        self.assertFalse(page.locator('[data-thumb-add]').is_visible())
        page.fill('[data-title]', 'Nike Reel Cut')
        self.assertTrue(page.locator('[data-thumb-add]').is_visible())
        page.wait_for_timeout(400)
        self.shot(page, '04-first-video-reel')
        page.set_input_files('[data-thumb-input]', files=[{'name': 'cover.png', 'mimeType': 'image/png', 'buffer': png_bytes(360, 640)}])
        page.wait_for_selector('[data-custom-thumb]:not([hidden])')
        self.assertTrue(page.locator('[data-thumb-clear]').is_visible())
        self.assertIn('Change thumbnail', page.inner_text('[data-thumb-add]'))
        page.wait_for_timeout(300)
        self.shot(page, '04b-first-video-own-thumbnail')
        page.click('#lv-submit')
        page.wait_for_url('**/launch/**')
        self.wait_for_toast(page)
        project = Project.objects.get(user=self.user)
        self.assertEqual((project.title, project.video_type), ('Nike Reel Cut', 'reel'))
        self.assertTrue(project.image.name.startswith('projects/thumb_'), project.image.name)  # theirs, not the looked-up one
        self.shot(page, '05-checklist-after-step-2')

        # Step 3: the themes gallery, then straight back
        page.click('.lc-current .btn-primary')
        page.wait_for_url('**/themes/')
        self.assertIn('Back to checklist', page.inner_text('header'))
        self.shot(page, '06-themes-in-launch-mode')
        page.click(f'label[for="theme-{self.themes["Pro"].pk}"]')
        page.click('#apply-btn')
        page.wait_for_url('**/launch/**')
        self.wait_for_toast(page)
        self.assertIn('Looking sharp!', page.inner_text('#lc-toast'))

        # Step 4: skills -> the last step reaches 100 XP
        page.click('.lc-current .btn-primary')
        page.wait_for_url('**/launch/skills/')
        self.assertIn('reach 100 XP', page.inner_text('#lk-submit'))
        for name in ('Adobe Premiere Pro', 'DaVinci Resolve', 'Color grading'):
            page.click(f'.lk-chip:has(input[value="{name}"])')
        page.fill('#lk-own-input', 'Topaz Video AI')
        page.press('#lk-own-input', 'Enter')
        self.assertEqual(page.inner_text('[data-count]'), '4')
        self.assertEqual(page.inner_text('[data-meter-label]'), 'Strong profile')
        self.shot(page, '07-skills')
        page.click('#lk-submit')
        page.wait_for_url('**/launch/**')
        self.wait_for_toast(page)
        self.assertIn("100 XP! You're ready.", page.inner_text('#lc-toast'))
        self.assertEqual(page.inner_text('[data-xp]'), '100')
        self.assertIn("You're ready, Sara", page.inner_text('h1'))
        self.shot(page, '08-checklist-100-xp')
        self.assertEqual(UserAccount.objects.get(user=self.user).launch_status, 'done')
        self.assertEqual(sorted(Skill.objects.filter(user=self.user).values_list('name', flat=True)),
                         ['Adobe Premiere Pro', 'Color grading', 'DaVinci Resolve', 'Topaz Video AI'])

        # At 100 XP: view the portfolio...
        page.click('text=View my portfolio')
        page.wait_for_url('**/sara/?launched=1')
        page.wait_for_selector('#sfl-bar')
        page.wait_for_timeout(600)
        self.assertIn('100 XP', page.inner_text('#sfl-bar'))
        self.shot(page, '09-portfolio-bar')

        # Then on to the dashboard, which no longer bounces to the checklist.
        page.click('#sfl-dashboard')
        page.wait_for_url('**/dashboard/')
        self.shot(page, '10-dashboard-after-launch')

    def test_finished_checklist_at_100_xp(self):
        self.seed_done('personal', 'project', 'theme', 'skills')
        UserAccount.objects.filter(user=self.user).update(launch_status='done')
        page = self.open_page()
        page.goto(f'{self.live_server_url}/launch/')
        page.wait_for_timeout(1100)
        self.assertIn("You're ready", page.inner_text('h1'))
        self.assertEqual(page.locator('#lc-toast').count(), 0, 'no celebration on a later visit')
        self.shot(page, '11-checklist-ready')
        # ...or go straight to the dashboard from the ready card.
        page.click('.sf-card >> text=Go to dashboard')
        page.wait_for_url('**/dashboard/')

    # -- mobile ------------------------------------------------------------------

    def test_mobile(self):
        width = 390
        self.seed_done('personal')
        page = self.open_page(width=width, height=844)
        page.goto(f'{self.live_server_url}/launch/')
        page.wait_for_timeout(1200)
        self.no_sideways_scroll(page, width)
        self.shot(page, '20-mobile-checklist')
        self.shot(page, '21-mobile-checklist-full', full=True)

        page.goto(f'{self.live_server_url}/launch/about-you/')
        page.wait_for_timeout(800)  # entrance animation
        self.no_sideways_scroll(page, width)
        self.shot(page, '22-mobile-about-you')
        self.shot(page, '22b-mobile-about-you-full', full=True)
        button = page.locator('#ls-submit').bounding_box()
        self.assertGreaterEqual(button['height'], 44)

        page.goto(f'{self.live_server_url}/launch/first-video/')
        page.fill('[data-url]', YT)
        page.wait_for_function("document.querySelector('[data-title]').value.length > 0")
        self.assertFalse(page.locator('#lv-submit').is_disabled(), 'a looked-up link enables the button')
        page.wait_for_timeout(400)  # the button fades in when enabled
        self.no_sideways_scroll(page, width)
        self.shot(page, '23-mobile-first-video', full=True)
        box = page.locator('[data-thumb-add]').bounding_box()
        self.assertGreaterEqual(min(box['width'], box['height']), 44, 'the thumbnail button is easy to tap')
        page.click('[data-type-fix]')  # "Use Long video"
        self.assertEqual(page.input_value('[data-type]'), 'long')
        self.assertFalse(page.locator('[data-type-hint]').is_visible())
        mockup = page.locator('[data-thumb-box]').bounding_box()
        self.assertAlmostEqual(mockup['width'] / mockup['height'], 16 / 9, delta=0.03, msg='long videos stay 16:9')
        page.wait_for_timeout(300)
        self.shot(page, '23b-mobile-first-video-long', full=True)

        page.goto(f'{self.live_server_url}/launch/skills/')
        page.click('.lk-chip:has(input[value="CapCut"])')
        self.no_sideways_scroll(page, width)
        self.shot(page, '24-mobile-skills')

        # End of the flow on a phone: 100 XP, then the portfolio.
        self.seed_done('project', 'theme')
        page.click('#lk-submit')
        page.wait_for_url('**/launch/**')
        self.wait_for_toast(page)
        self.no_sideways_scroll(page, width)
        self.shot(page, '25-mobile-100-xp')
        page.click('text=View my portfolio')
        page.wait_for_url('**/sara/?launched=1')
        page.wait_for_selector('#sfl-bar')
        page.wait_for_timeout(600)
        self.no_sideways_scroll(page, width)
        self.shot(page, '26-mobile-bar')
        for box in page.locator('#sfl-bar .sfl-btn').all():
            self.assertGreaterEqual(box.bounding_box()['height'], 44)

    # -- phones of every size ---------------------------------------------------

    PHONE_WIDTHS = (320, 360, 390, 430, 768)

    def small_targets(self, page):
        """Real tap targets (buttons, links, chips, fields) on screen that are smaller than 44px.

        Labels that point at a field are skipped (the field is the target), and so are
        off-screen skip links and the themes gallery's own controls, which are not part of the launch flow.
        """
        return page.evaluate("""() => Array.from(document.querySelectorAll(
              'a, button, label, input:not([type=checkbox]):not([type=file]), textarea'))
            .filter(el => {
              if (el.tagName === 'LABEL' && (el.htmlFor || el.querySelector('input:not([type=checkbox]):not([type=file]), textarea'))) return false;
              if (el.closest('nav, footer, .themes-page, .apply-bar, #sfl-root, .lc-toast, .lx-skip, [hidden]')) return false;
              const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
              if (cs.display === 'none' || cs.visibility === 'hidden' || r.width < 2 || r.height < 2) return false;
              if (r.right < 0 || r.bottom < 0 || r.left > window.innerWidth) return false;
              if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return false;  // fields are 48px+ by design
              return r.height < 43 || r.width < 43;
            })
            .slice(0, 12).map(el => (el.tagName + ' ' + (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30)
              + ' ' + Math.round(el.getBoundingClientRect().width) + 'x' + Math.round(el.getBoundingClientRect().height)))""")
    def phone_pages(self):
        """(name, url, seed) for every launch screen a phone user meets."""
        return [
            ('checklist', '/launch/', ('personal',)),
            ('checklist-ready', '/launch/', ('personal', 'project', 'theme', 'skills')),
            ('about-you', '/launch/about-you/', ()),
            ('first-video', '/launch/first-video/', ('personal',)),
            ('skills', '/launch/skills/', ('personal', 'project', 'theme')),
            ('themes', '/themes/', ('personal',)),
        ]

    def test_phone_layout_at_every_width(self):
        problems = []
        for width in self.PHONE_WIDTHS:
            for name, url, seed in self.phone_pages():
                UserAccount.objects.filter(user=self.user).update(launch_status='active', launch_theme_picked=False)
                Project.objects.filter(user=self.user).delete()
                Skill.objects.filter(user=self.user).delete()
                PersonalInfo.objects.filter(user=self.user).delete()
                self.seed_done(*seed)
                if name == 'checklist-ready':
                    UserAccount.objects.filter(user=self.user).update(launch_status='done')
                page = self.open_page(width=width, height=780)
                page.goto(f'{self.live_server_url}{url}')
                page.wait_for_timeout(900)  # entrance animations
                label = f'{name} @{width}px'
                try:
                    self.no_sideways_scroll(page, width)
                except AssertionError as exc:
                    problems.append(f'{label}: {exc}')
                small = self.small_targets(page)
                if small:
                    problems.append(f'{label}: small tap targets {small}')
                if width in (320, 390):
                    self.shot(page, f'40-phone-{name}-{width}', full=True)
                page.close()
        self.assertEqual(problems, [], '\n'.join(problems))
    # -- Arabic ------------------------------------------------------------------

    def test_arabic(self):
        self.seed_done('personal', 'project')
        page = self.open_page()
        page.goto(f'{self.live_server_url}/ar/launch/?done=project')
        self.assertEqual(page.evaluate('document.documentElement.dir'), 'rtl')
        self.wait_for_toast(page)
        self.assertIn('أضفت أول فيديو!', page.inner_text('#lc-toast'))
        self.shot(page, '30-arabic-checklist')
        page.goto(f'{self.live_server_url}/ar/launch/about-you/')
        page.wait_for_timeout(800)
        self.shot(page, '31-arabic-about-you')
        page.goto(f'{self.live_server_url}/ar/launch/skills/')
        page.wait_for_timeout(800)
        self.shot(page, '32-arabic-skills')
        page.goto(f'{self.live_server_url}/ar/themes/')
        self.assertIn('الخطوة 3 من 4', page.inner_text('body'))
        self.shot(page, '33-arabic-themes')

        mobile = self.open_page(width=390, height=844)
        mobile.goto(f'{self.live_server_url}/ar/launch/')
        mobile.wait_for_timeout(1100)
        self.no_sideways_scroll(mobile, 390)
        self.shot(mobile, '34-arabic-mobile-checklist')
