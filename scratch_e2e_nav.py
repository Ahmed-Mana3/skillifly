import mimetypes
import os
import sys
import unittest
from urllib.parse import urlparse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "skillifly.settings")

import django  # noqa: E402

django.setup()

from django.test.runner import DiscoverRunner  # noqa: E402
from django.test.utils import setup_test_environment, teardown_test_environment  # noqa: E402

setup_test_environment()
runner = DiscoverRunner(verbosity=0, interactive=False)
old_config = runner.setup_databases()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.test import LiveServerTestCase, override_settings  # noqa: E402
from core.models import Category, Profile, Theme  # noqa: E402

SOURCE_STATIC = str(settings.STATICFILES_DIRS[0])

CDN_ROUTES = [
    "**cdn.tailwindcss.com**",
    "**fonts.googleapis.com**",
    "**fonts.gstatic.com**",
    "**/sw.js*",
    "**analytics.google.com/**",
    "**googletagmanager/**",
]


def block(route, request):
    route.abort()


def serve_static(route, request):
    path = urlparse(request.url).path
    rel = path[len("/static/"):]
    fs_path = os.path.join(SOURCE_STATIC, rel.replace("/", os.sep))
    if os.path.isfile(fs_path):
        ctype = mimetypes.guess_type(fs_path)[0] or "application/octet-stream"
        if fs_path.endswith(".js"):
            ctype = "text/javascript"
        with open(fs_path, "rb") as f:
            route.fulfill(status=200, content_type=ctype, body=f.read())
    else:
        route.fulfill(status=404, content_type="text/plain", body="missing")


@override_settings(
    DEBUG=False,
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class BuilderNavigationE2E(LiveServerTestCase):
    def setUp(self):
        self.cat_dev = Category.objects.create(name="Developer")
        self.theme_dev = Theme.objects.create(name="Minimal", category=self.cat_dev)
        User = get_user_model()
        self.user = User.objects.create_user(
            username="navtest", email="nav@example.com", password="pass12345"
        )
        Profile.objects.create(user=self.user, theme=self.theme_dev)

        self.js_errors = []
        self.client.force_login(self.user)
        self.session_cookie = self.client.cookies["sessionid"].value

    def tearDown(self):
        pw = getattr(self, "_pw", None)
        browser = getattr(self, "_browser", None)
        try:
            if browser:
                browser.close()
            if pw:
                pw.stop()
        except Exception:
            pass

    def _start(self, viewport=None):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        ctx = self._browser.new_context(
            viewport=viewport or {"width": 1280, "height": 900},
            is_mobile=bool(viewport),
            has_touch=bool(viewport),
        )
        ctx.route("**/static/**", serve_static)
        for pattern in CDN_ROUTES:
            ctx.route(pattern, block)
        ctx.add_cookies(
            [{"name": "sessionid", "value": self.session_cookie, "url": self.live_server_url}]
        )
        page = ctx.new_page()
        page.on("pageerror", lambda e: self.js_errors.append(str(e)))
        page.on(
            "console",
            lambda m: self.js_errors.append(f"console.{m.type}: {m.text}")
            if m.type == "error"
            and not any(
                tag in m.text
                for tag in (
                    "net::ERR_FAILED",
                    "Failed to load resource",
                    "ServiceWorker",
                    "fetching the script",
                )
            )
            else None,
        )
        return page, ctx

    def _open(self, page, suffix=""):
        page.goto(self.live_server_url + "/builder/" + suffix, wait_until="domcontentloaded")
        page.add_style_tag(
            content="""
                body > nav.fixed { display: none !important; }
                #main-content { padding-top: 16px !important; }
                a.sr-only { display: none !important; }
            """
        )
        page.wait_for_function(
            "() => typeof BX !== 'undefined' && BX.panels && BX.panels.length === 8", timeout=15000
        )

    def _nav_debug(self, page):
        return page.evaluate(
            """() => ({
                active: document.querySelector('.bx-panel.is-active')?.dataset.key || null,
                nextBtns: document.querySelectorAll('.bx-panel.is-active [data-action="next"]').length,
                panelsInDom: document.querySelectorAll('#bx-panels > .bx-panel').length,
                hash: location.hash,
                category: document.getElementById('builder-root')?.dataset.category,
                order: window.BX ? BX.order : null,
                currentKey: window.BX ? BX.currentKey : null,
            })"""
        )

    def _active_key(self, page):
        return page.evaluate(
            "() => { const p = document.querySelector('.bx-panel.is-active'); return p ? p.dataset.key : null; }"
        )

    def _assert_clean(self, label):
        self.assertEqual(self.js_errors, [], f"JS errors during {label}: {self.js_errors}")

    def test_init_healthy(self):
        page, _ = self._start()
        self._open(page)
        state = page.evaluate(
            """() => ({
                panels: BX.panels ? BX.panels.length : -1,
                navItems: document.querySelectorAll('#bx-nav .bx-nav-item').length,
                orderLen: BX.order.length,
                active: BX.currentKey,
            })"""
        )
        self.assertEqual(state["panels"], 8)
        self.assertEqual(state["navItems"], 8)
        self.assertEqual(state["orderLen"], 8)
        self.assertEqual(state["active"], "identity")
        hidden = page.evaluate(
            "() => getComputedStyle(document.getElementById('panel-skills')).display"
        )
        self.assertEqual(hidden, "none")
        css_loaded = page.evaluate("() => getComputedStyle(document.querySelector('.bx-panel')).borderRadius")
        self.assertNotIn(css_loaded, ("", "0px"), "builder_v2.css must be applied")
        self._assert_clean("init")

    def test_sidebar_clicks_visit_every_section_in_order(self):
        page, _ = self._start()
        self._open(page)
        order = page.evaluate("() => BX.order")
        self.assertEqual(len(order), 8)

        for key in order:
            page.click(f'[data-nav-key="{key}"]')
            page.wait_for_function(
                f"() => document.querySelector('.bx-panel.is-active')?.dataset.key === '{key}'",
                timeout=3000,
            )
            self.assertEqual(self._active_key(page), key)
            self.assertEqual(page.get_attribute(f'[data-nav-key="{key}"]', "aria-current"), "true")

        count = page.evaluate("() => document.querySelectorAll('.bx-panel.is-active').length")
        self.assertEqual(count, 1)
        self.assertIn("#" + order[-1], page.url)
        self._assert_clean("sidebar navigation")

    def test_nav_numbers_match_reorder(self):
        page, _ = self._start()
        self._open(page)
        order = page.evaluate("() => BX.order")
        nums = page.evaluate(
            "() => Array.from(document.querySelectorAll('#bx-nav .bx-nav-num')).map(n => n.textContent)"
        )
        self.assertEqual(nums, [str(i + 1) for i in range(8)])
        panel_keys = page.evaluate(
            "() => Array.from(document.querySelectorAll('#bx-panels > .bx-panel')).map(p => p.dataset.key)"
        )
        self.assertEqual(panel_keys, order)
        kickers = page.evaluate(
            "() => Array.from(document.querySelectorAll('.bx-panel-kicker')).map(k => k.textContent)"
        )
        self.assertEqual(kickers[0], "Section 1")
        self.assertEqual(kickers[-1], "Section 8")
        self._assert_clean("reorder numbering")

    def test_next_back_buttons_step_through_order(self):
        page, _ = self._start()
        self._open(page)
        order = page.evaluate("() => BX.order")

        for expected in order[1:]:
            page.click('.bx-panel.is-active [data-action="next"]')
            page.wait_for_function(
                f"() => document.querySelector('.bx-panel.is-active')?.dataset.key === '{expected}'",
                timeout=3000,
            )
        self.assertEqual(self._active_key(page), order[-1])

        last_state = page.evaluate(
            """() => {
                const panel = document.querySelector('.bx-panel.is-active');
                const next = panel.querySelector('[data-nav-next]');
                const save = panel.querySelector('[data-nav-save]');
                return {
                    key: panel.dataset.key,
                    nextHidden: next ? next.hidden : null,
                    saveExists: !!save,
                    saveHidden: save ? save.hidden : null,
                    saveIsSubmit: save ? save.type === 'submit' : false,
                    saveBoundToForm: save ? save.getAttribute('form') === 'portfolio-form' : false,
                };
            }"""
        )
        self.assertEqual(last_state["key"], order[-1])
        self.assertTrue(last_state["nextHidden"], "Next must be hidden on the last section")
        self.assertTrue(last_state["saveExists"], "Save must exist on the last section")
        self.assertFalse(last_state["saveHidden"], "Save must be visible on the last section")
        self.assertTrue(last_state["saveIsSubmit"])
        self.assertTrue(last_state["saveBoundToForm"])

        mid_panel_save = page.evaluate(
            """() => {
                const panel = document.getElementById('panel-identity');
                const save = panel.querySelector('[data-nav-save]');
                const next = panel.querySelector('[data-nav-next]');
                return { saveHidden: save.hidden, nextHidden: next.hidden };
            }"""
        )
        self.assertFalse(mid_panel_save["nextHidden"], "non-last sections keep Next visible")
        self.assertTrue(mid_panel_save["saveHidden"], "non-last sections keep Save hidden")

        for expected in reversed(order[:-1]):
            page.click('.bx-panel.is-active [data-action="prev"]')
            page.wait_for_function(
                f"() => document.querySelector('.bx-panel.is-active')?.dataset.key === '{expected}'",
                timeout=3000,
            )
        self.assertEqual(self._active_key(page), order[0])
        self._assert_clean("next/back stepping")

    def test_hash_deep_link_opens_section(self):
        page, _ = self._start()
        self._open(page, "#experience")
        self.assertEqual(self._active_key(page), "experience")
        self._assert_clean("hash deep link")

    def test_video_editor_category_reorder(self):
        cat = Category.objects.filter(name="Video Editor").first()
        if not cat:
            cat = Category.objects.create(name="Video Editor")
        theme = Theme.objects.filter(name="Minimal", category=cat).first()
        if not theme:
            theme = Theme.objects.create(name="Minimal", category=cat)
        profile = Profile.objects.get(user=self.user)
        profile.theme = theme
        profile.save()

        page, _ = self._start()
        self._open(page)
        order = page.evaluate("() => BX.order")
        self.assertEqual(order[0], "identity")
        self.assertEqual(order[1], "projects")
        page.click('[data-nav-key="projects"]')
        page.wait_for_function(
            "() => document.querySelector('.bx-panel.is-active')?.dataset.key === 'projects'",
            timeout=3000,
        )
        self._assert_clean("video_editor reorder")

    def test_mobile_viewport_navigation_and_dirty_state(self):
        page, ctx = self._start(viewport={"width": 390, "height": 844})
        self._open(page)

        sticky = page.evaluate(
            "() => { const cs = getComputedStyle(document.querySelector('.bx-sidebar')); return cs.position.includes('sticky'); }"
        )
        self.assertTrue(sticky)

        order = page.evaluate("() => BX.order")
        for key in order[:4]:
            boxes = page.evaluate(
                """() => {
                    const l = document.getElementById('bx-nav');
                    return {
                        scrollLeft: l.scrollLeft,
                        listRect: JSON.parse(JSON.stringify(l.getBoundingClientRect())),
                        pills: Array.from(l.querySelectorAll('.bx-nav-item')).map(b => ({
                            key: b.dataset.navKey,
                            x: Math.round(b.getBoundingClientRect().x),
                            w: Math.round(b.getBoundingClientRect().width),
                        })),
                    };
                }"""
            )
            print(f"[mobile] before clicking '{key}': {boxes}")
            page.click(f'[data-nav-key="{key}"]')
            page.wait_for_function(
                f"() => document.querySelector('.bx-panel.is-active')?.dataset.key === '{key}'",
                timeout=3000,
            )

        scroller_metrics = page.evaluate(
            """() => {
                const l = document.getElementById('bx-nav');
                const cs = getComputedStyle(l);
                const first = l.querySelector('.bx-nav-item');
                return {
                    scrollWidth: l.scrollWidth,
                    clientWidth: l.clientWidth,
                    display: cs.display,
                    direction: cs.flexDirection,
                    wrap: cs.flexWrap,
                    firstWidth: first ? first.offsetWidth : null,
                    itemCount: l.children.length,
                };
            }"""
        )
        scroller = scroller_metrics["scrollWidth"] > scroller_metrics["clientWidth"]
        self.assertTrue(
            scroller,
            f"mobile nav should scroll horizontally; metrics={scroller_metrics}",
        )

        dirty_before = page.evaluate("() => document.body.classList.contains('bx-is-dirty')")
        page.click('[data-nav-key="identity"]')
        page.wait_for_function(
            "() => document.querySelector('.bx-panel.is-active')?.dataset.key === 'identity'",
            timeout=3000,
        )
        page.fill('input[name="fullname"]', "Mobile Tester")
        dirty_after = page.evaluate("() => document.body.classList.contains('bx-is-dirty')")
        self.assertFalse(dirty_before)
        self.assertTrue(dirty_after)

        page.wait_for_function(
            "() => { const r = document.getElementById('bx-savebar').getBoundingClientRect(); return r.top < window.innerHeight && r.height > 0; }",
            timeout=3000,
        )

        input_font = page.evaluate(
            "() => parseFloat(getComputedStyle(document.querySelector('input[name=\"fullname\"]')).fontSize)"
        )
        self.assertGreaterEqual(input_font, 16)
        self.assertEqual(self.js_errors, [], f"JS errors on mobile: {self.js_errors}")
        ctx.close()


if __name__ == "__main__":
    try:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(BuilderNavigationE2E)
        )
    finally:
        try:
            runner.teardown_databases(old_config)
            teardown_test_environment()
        except Exception as e:
            print(f"[cleanup] {e}")

    sys.exit(0 if result.wasSuccessful() else 1)
