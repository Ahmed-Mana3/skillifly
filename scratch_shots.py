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
from core.models import Category, Profile, Project, Skill, Theme  # noqa: E402

SOURCE_STATIC = str(settings.STATICFILES_DIRS[0])
OUT_DIR = r"C:\Users\am537\AppData\Local\Temp\opencode\shots"
os.makedirs(OUT_DIR, exist_ok=True)


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
class Shots(LiveServerTestCase):
    def setUp(self):
        cat = Category.objects.create(name="Video Editor")
        theme = Theme.objects.create(name="Minimal", category=cat)
        User = get_user_model()
        self.user = User.objects.create_user(username="shot", email="s@x.com", password="pass12345")
        profile = Profile.objects.create(user=self.user, theme=theme)
        profile.save()
        for i, name in enumerate(["Premiere Pro", "After Effects", "DaVinci Resolve"], start=1):
            Skill.objects.create(user=self.user, name=name)
        for i in range(1, 4):
            Project.objects.create(
                user=self.user,
                title=f"Brand Campaign {i}",
                url=f"https://youtube.com/watch?v={i}",
                details="Cut, color and sound design for a national campaign.",
                video_type="long" if i % 2 else "reel",
            )

    def test_shots(self):
        self.client.force_login(self.user)
        cookie = self.client.cookies["sessionid"].value

        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)

        for label, vw, vh, mobile in [("desktop", 1280, 900, False), ("phone", 390, 844, True)]:
            ctx = browser.new_context(viewport={"width": vw, "height": vh}, is_mobile=mobile, has_touch=mobile)
            ctx.route("**/static/**", serve_static)
            for p in ["**cdn.tailwindcss.com**", "**fonts.googleapis.com**", "**fonts.gstatic.com**",
                      "**/sw.js*", "**analytics.google.com/**", "**googletagmanager/**"]:
                ctx.route(p, block)
            ctx.add_cookies([{"name": "sessionid", "value": cookie, "url": self.live_server_url}])
            page = ctx.new_page()
            page.goto(self.live_server_url + "/builder/", wait_until="domcontentloaded")
            page.wait_for_function("() => typeof BX !== 'undefined' && BX.panels && BX.panels.length === 8")

            page.evaluate("() => BX.goTo('projects')")
            page.wait_for_timeout(700)
            page.screenshot(path=os.path.join(OUT_DIR, f"projects_{label}.png"), full_page=False)

            page.evaluate("() => BX.goTo('skills')")
            page.wait_for_timeout(600)
            page.screenshot(path=os.path.join(OUT_DIR, f"skills_{label}.png"), full_page=False)

            page.evaluate("() => BX.goTo('identity')")
            page.wait_for_timeout(600)
            page.screenshot(path=os.path.join(OUT_DIR, f"identity_{label}.png"), full_page=False)

            # focus-within state on first project card
            page.evaluate("() => BX.goTo('projects')")
            page.wait_for_timeout(500)
            page.focus('#projects-container .bx-item input[name$="-name"]')
            page.wait_for_timeout(400)
            page.screenshot(path=os.path.join(OUT_DIR, f"focus_{label}.png"), full_page=False)
            ctx.close()

        browser.close()
        pw.stop()


if __name__ == "__main__":
    try:
        unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromTestCase(Shots))
    finally:
        try:
            runner.teardown_databases(old_config)
            teardown_test_environment()
        except Exception as e:
            print("[cleanup]", e)
    print("done ->", OUT_DIR)
