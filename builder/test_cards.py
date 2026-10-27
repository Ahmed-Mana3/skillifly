"""Builder video cards, skill chips, link names, readiness card and video order (stages 1-2)."""
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase

from builder import services
from core.models import Link, PersonalInfo, Profile, Project, Skill
from core.oembed import VideoMeta
from core.testing_helpers import TempMediaMixin, give_payment, make_editor, png_bytes, seed_themes

YT = "https://www.youtube.com/watch?v=abcdefghijk"


def management(prefix, rows):
    post = {
        f"{prefix}-TOTAL_FORMS": str(len(rows)),
        f"{prefix}-INITIAL_FORMS": str(len([r for r in rows if r.get("id")])),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }
    for i, row in enumerate(rows):
        post.update({f"{prefix}-{i}-{key}": value for key, value in row.items()})
    return post


class PlatformFromUrlTests(TestCase):
    def test_known_and_unknown_hosts(self):
        cases = {
            "instagram.com/sara": "Instagram",
            "https://www.youtube.com/@sara": "YouTube",
            "https://wa.me/201001234567": "WhatsApp",
            "twitter.com/sara": "X",
            "https://m.facebook.com/sara": "Facebook",
            "https://sara.studio": "sara.studio",
            "": "",
        }
        for url, name in cases.items():
            with self.subTest(url):
                self.assertEqual(services.platform_from_url(url), name)


class LinkTitleTests(TestCase):
    def test_the_video_title_when_the_lookup_has_one(self):
        with patch("core.oembed.fetch", return_value=VideoMeta(url=YT, title="Nike — Run Cairo")):
            self.assertEqual(services.link_title(YT), "Nike — Run Cairo")

    def test_a_friendly_default_otherwise(self):
        with patch("core.oembed.fetch", return_value=VideoMeta(url=YT, ok=False, error="network")):
            self.assertEqual(services.link_title(YT), "My video")
            self.assertEqual(services.link_title(YT, arabic=True), "فيديو من أعمالي")


class LinkThumbnailTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.user = make_editor()

    def save(self, url, instance=None):
        data = {"name": "Cut", "url": url, "description": "", "video_type": "long", "category_id": "", "thumbnail": None}
        with patch("core.oembed.fetch", return_value=VideoMeta(url=url, thumbnail_url="https://i.ytimg.com/x.jpg")), \
             patch("core.oembed.download_thumbnail", return_value=ContentFile(png_bytes(), name="t.png")) as dl, \
             self.captureOnCommitCallbacks(execute=True):
            row, _ = services.save_row(self.user, "projects", data, instance=instance)
        row.refresh_from_db()
        return row, dl

    def test_a_new_video_gets_its_link_thumbnail_after_saving(self):
        row, _ = self.save(YT)
        self.assertTrue(row.image)

    def test_a_video_with_its_own_image_keeps_it(self):
        project = Project.objects.create(user=self.user, title="Cut", url=YT)
        project.image.save("mine.png", ContentFile(png_bytes()), save=True)
        name = project.image.name
        row, dl = self.save(YT + "x", instance=project)
        self.assertEqual(row.image.name, name)
        dl.assert_not_called()

    def test_a_new_link_replaces_the_old_links_thumbnail(self):
        project = Project.objects.create(user=self.user, title="Cut", url=YT)
        project.image.save("oembed_old.png", ContentFile(png_bytes()), save=True)
        old = project.image.name
        row, dl = self.save(YT + "x", instance=project)
        dl.assert_called_once()
        self.assertTrue(row.image)
        self.assertNotEqual(row.image.name, old)

    def test_an_unchanged_link_is_not_looked_up_again(self):
        project = Project.objects.create(user=self.user, title="Cut", url=YT)
        _, dl = self.save(YT, instance=project)
        dl.assert_not_called()


class ReorderApiTests(TestCase):
    def setUp(self):
        self.user = make_editor()
        self.client.force_login(self.user)
        self.a, self.b, self.c = (Project.objects.create(user=self.user, title=t, order=i) for i, t in enumerate("abc"))

    def titles(self):
        return list(Project.objects.filter(user=self.user).values_list("title", flat=True))

    def test_the_order_sent_is_saved(self):
        res = self.client.post("/builder/api/projects/order/", {"ids": [self.c.id, self.a.id, self.b.id]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.titles(), ["c", "a", "b"])

    def test_videos_not_listed_follow_and_foreign_ids_are_ignored(self):
        theirs = Project.objects.create(user=make_editor(username="other"), title="theirs")
        self.client.post("/builder/api/projects/order/", {"ids": [self.b.id, theirs.id]})
        self.assertEqual(self.titles(), ["b", "a", "c"])
        theirs.refresh_from_db()
        self.assertEqual(theirs.order, 0)

    def test_bad_ids_and_signed_out(self):
        self.assertEqual(self.client.post("/builder/api/projects/order/", {"ids": ["x"]}).status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.post("/builder/api/projects/order/", {"ids": [self.a.id]}).status_code, 401)


class LegacyFormSaveTests(TempMediaMixin, TestCase):
    """The full-form Save (autosave off) follows the same new rules."""

    def setUp(self):
        self.user = make_editor()
        Profile.objects.create(user=self.user, theme=seed_themes()["Creative"])
        self.client.force_login(self.user)

    def post(self, projects=(), links=()):
        post = {"fullname": "Sara Ali", "title": "Colorist"}
        for prefix, rows in (("skills", []), ("education", []), ("experience", []),
                             ("projects", list(projects)), ("links", list(links)), ("creators", [])):
            post.update(management(prefix, rows))
        with patch("core.oembed.fetch", return_value=VideoMeta(url=YT, title="From the link")):
            return self.client.post("/builder/update/", post)

    def test_a_video_with_only_its_link(self):
        res = self.post(projects=[{"name": "", "url": YT, "description": "", "video_type": "reel", "category_id": ""}])
        self.assertEqual(res.status_code, 302)
        project = Project.objects.get(user=self.user)
        self.assertEqual((project.title, project.video_type), ("From the link", "reel"))

    def test_a_link_without_a_name_is_named_after_its_site(self):
        res = self.post(links=[{"name": "", "url": "instagram.com/sara"}])
        self.assertEqual(res.status_code, 302)
        link = Link.objects.get(user=self.user)
        self.assertEqual((link.platform, link.url), ("Instagram", "https://instagram.com/sara"))


class BuilderPageTests(TestCase):
    def setUp(self):
        self.user = make_editor()
        Profile.objects.create(user=self.user, theme=seed_themes()["Creative"])
        self.client.force_login(self.user)

    def page(self, path="/builder/update/"):
        res = self.client.get(path)
        self.assertEqual(res.status_code, 200)
        return res.content.decode()

    def test_no_blank_rows_for_a_new_user(self):
        for path in ("/builder/", "/builder/update/", "/ar/builder/"):
            with self.subTest(path):
                html = self.page(path)
                for prefix in ("skills", "education", "experience", "projects", "links", "creators"):
                    self.assertIn(f'name="{prefix}-TOTAL_FORMS" value="0"', html)

    def test_video_editor_page_parts(self):
        html = self.page()
        self.assertIn('id="bx-ready"', html)
        self.assertIn('id="bx-paste-input"', html)
        self.assertIn('data-names="davinci resolve"', html)       # skill presets
        self.assertIn('data-names="color grading|تصحيح الألوان"', html)
        self.assertIn('id="projects-empty-form"', html)
        self.assertIn('class="bx-vcard"', html)                   # the add template is a card
        self.assertIn('<option value="long" selected>Full video</option>', html)
        self.assertIn('id="bx-done-tpl"', html)

    def test_saved_rows_render_as_cards_and_chips(self):
        Project.objects.create(user=self.user, title="Brand film", url=YT)
        Skill.objects.create(user=self.user, name="Blender")
        Link.objects.create(user=self.user, platform="Instagram", url="https://instagram.com/sara")
        html = self.page()
        self.assertIn('data-vcard-title data-empty="New video">Brand film</p>', html)
        self.assertIn('<span class="bx-skill-label" data-skill-label>Blender</span>', html)
        self.assertIn('data-link-platform>Instagram</span>', html)

    def test_preview_until_live(self):
        html = self.page()
        self.assertIn("Preview", html)
        self.assertIn('?ra=live" data-ready-action', html)  # Publish, once client-ready
        self.assertNotIn('data-action="copy-link"', html)

        give_payment(self.user)
        Profile.objects.filter(user=self.user).update(is_public=True)
        html = self.page()
        self.assertIn("View live site", html)
        self.assertIn('data-action="copy-link"', html)
        self.assertIn('data-portfolio-url="http://testserver/sara/"', html)

    def test_arabic_page(self):
        html = self.page("/ar/update/")
        self.assertIn("جهّز معرضك للعملاء", html)
        self.assertIn('<option value="long" selected>فيديو كامل</option>', html)
        self.assertIn("معاينة", html)
        self.assertIn("moreSections: 'أقسام إضافية ({n})'", html)
