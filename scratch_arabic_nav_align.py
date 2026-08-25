import os

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
]


def block(route, request):
    route.abort()


def serve_static(route, request):
    import mimetypes
    from urllib.parse import urlparse

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


MEASURE = """() => {
  const label = document.querySelector('.bx-nav-label-cap').getBoundingClientRect();
  const item = document.querySelector('#bx-nav .bx-nav-item');
  const num = item.querySelector('.bx-nav-num').getBoundingClientRect();
  const state = item.querySelector('.bx-nav-state').getBoundingClientRect();
  const ir = item.getBoundingClientRect();
  return {
    dir: document.documentElement.getAttribute('dir'),
    labelStart: %s,
    contentStart: %s,
    stateEnd: %s,
    contentEnd: %s,
  };
}"""


@override_settings(
    DEBUG=False,
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class ArabicNavAlignE2E(LiveServerTestCase):
    def setUp(self):
        cat = Category.objects.create(name="Developer")
        theme = Theme.objects.create(name="Minimal", category=cat)
        User = get_user_model()
        self.user = User.objects.create_user(
            username="artest", email="ar@example.com", password="pass12345"
        )
        Profile.objects.create(user=self.user, theme=theme)
        self.client.force_login(self.user)
        self.session_cookie = self.client.cookies["sessionid"].value

    def _open(self, path):
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.route("**/static/**", serve_static)
        for pattern in CDN_ROUTES:
            ctx.route(pattern, block)
        ctx.add_cookies(
            [{"name": "sessionid", "value": self.session_cookie, "url": self.live_server_url}]
        )
        page = ctx.new_page()
        page.goto(self.live_server_url + path, wait_until="domcontentloaded")
        page.wait_for_function("() => typeof BX !== 'undefined'", timeout=15000)
        page.wait_for_selector("#bx-nav .bx-nav-item .bx-nav-num", timeout=15000)
        page.wait_for_function(
            "() => getComputedStyle(document.querySelector('.bx-nav-item')).borderRadius !== '0px'",
            timeout=15000,
        )
        return pw, browser, page

    def test_sidebar_alignment_rtl_and_ltr(self):
        # --- Arabic (RTL): label/content start at the RIGHT edge, badge at far LEFT
        pw, browser, page = self._open("/ar/builder/")
        rtl = page.evaluate(
            MEASURE
            % ("label.right", "num.right", "state.left", "item.getBoundingClientRect().left")
        )
        page.locator(".bx-sidebar").screenshot(
            path=r"C:\Users\am537\AppData\Local\Temp\opencode\sidebar_ar.png"
        )
        print("RTL:", rtl)
        browser.close()
        pw.stop()

        self.assertEqual(rtl["dir"], "rtl")
        self.assertAlmostEqual(rtl["labelStart"], rtl["contentStart"], delta=2.0,
                               msg="الأقسام label must align with nav items (RTL)")

        # --- English (LTR): unchanged behavior — label/content start LEFT, badge far RIGHT
        pw, browser, page = self._open("/builder/")
        ltr = page.evaluate(
            MEASURE
            % ("label.left", "num.left", "state.right", "item.getBoundingClientRect().right")
        )
        page.locator(".bx-sidebar").screenshot(
            path=r"C:\Users\am537\AppData\Local\Temp\opencode\sidebar_en.png"
        )
        print("LTR:", ltr)
        browser.close()
        pw.stop()

        self.assertEqual(ltr["dir"], "ltr")
        self.assertAlmostEqual(ltr["labelStart"], ltr["contentStart"], delta=2.0,
                               msg="Sections label must align with nav items (LTR)")


if __name__ == "__main__":
    import unittest

    try:
        result = unittest.main(exit=False, verbosity=2).result
    finally:
        teardown_test_environment()
        runner.teardown_databases(old_config)
    ok = result.wasSuccessful()
    print("RESULT:", "OK" if ok else "FAILED")
