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


def block(route, request):
    route.abort()


@override_settings(
    DEBUG=False,
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class Diag(LiveServerTestCase):
    def setUp(self):
        cat = Category.objects.create(name="Developer")
        theme = Theme.objects.create(name="Minimal", category=cat)
        User = get_user_model()
        self.user = User.objects.create_user(username="d1", email="d@x.com", password="pass12345")
        Profile.objects.create(user=self.user, theme=theme)

    def test_diag(self):
        self.client.force_login(self.user)
        cookie = self.client.cookies["sessionid"].value

        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context()
        ctx.route("**/static/**", serve_static)
        for p in [
            "**cdn.tailwindcss.com**",
            "**fonts.googleapis.com**",
            "**fonts.gstatic.com**",
            "**/sw.js*",
            "**analytics.google.com/**",
            "**googletagmanager/**",
        ]:
            ctx.route(p, block)
        ctx.add_cookies([{"name": "sessionid", "value": cookie, "url": self.live_server_url}])
        page = ctx.new_page()
        msgs = []
        page.on("pageerror", lambda e: msgs.append(f"PAGEERROR: {e}"))
        page.on("console", lambda m: msgs.append(f"console.{m.type}: {m.text}"))

        page.goto(self.live_server_url + "/builder/", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        state = page.evaluate(
            """() => ({
                bxType: typeof BX,
                bxString: String(window.BX).slice(0, 120),
                bxKeys: window.BX ? Object.keys(window.BX).slice(0, 8) : null,
                currentKey: window.BX ? BX.currentKey : 'NO_BX',
                domReady: document.readyState,
                scriptCount: document.querySelectorAll('script[src*=\"builder_v2\"]').length,
            })"""
        )
        print("\n=== STATE ===")
        for k, v in state.items():
            print(f"  {k}: {v}")

        resp = page.request.get(self.live_server_url + "/static/js/builder_v2.js?v=1")
        body = resp.text()
        print("=== SERVED SCRIPT ===")
        print("  status:", resp.status, "len:", len(body))
        print("  head:", body[:80].replace(chr(10), ' '))
        print("  has updateFooterButtons:", "updateFooterButtons" in body)
        print("  tail:", body[-80:].replace(chr(10), ' '))
        print("=== MESSAGES ===")
        for m in msgs[:20]:
            print(" ", m)
        browser.close()
        pw.stop()


if __name__ == "__main__":
    try:
        unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromTestCase(Diag))
    finally:
        try:
            runner.teardown_databases(old_config)
            teardown_test_environment()
        except Exception as e:
            print("[cleanup]", e)
