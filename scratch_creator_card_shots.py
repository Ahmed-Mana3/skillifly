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


TAG = os.environ.get("SHOT_TAG", "before")


@override_settings(
    DEBUG=False,
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
)
class CreatorCardShots(LiveServerTestCase):
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

    def test_shots(self):
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)

        for lang, path in (("en", "/builder/"), ("ar", "/ar/builder/")):
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
            page.click('[data-nav-key="creators"]')
            page.wait_for_selector("#panel-creators.is-active", timeout=5000)
            page.click('[data-action="add"][data-prefix="creators"]')
            page.wait_for_selector("#creators-container .bx-item", timeout=5000)
            out = rf"C:\Users\am537\AppData\Local\Temp\opencode\creator_{lang}_{TAG}.png"
            page.locator("#creators-container").screenshot(path=out)
            print("saved:", out)
            ctx.close()

        browser.close()
        pw.stop()


if __name__ == "__main__":
    import unittest

    try:
        result = unittest.main(exit=False, verbosity=0).result
    finally:
        teardown_test_environment()
        runner.teardown_databases(old_config)
    print("RESULT:", "OK" if result.wasSuccessful() else "FAILED")
