"""Per-item save API (builder.api): one row, or the personal info, per request."""
import re
import shutil
import tempfile
from datetime import date
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import (
    ActivationEvent, Creator, Education, Experience, Link, PersonalInfo, Profile, Project, ProjectCategory, Skill,
)
from core.oembed import VideoMeta
from core.testing_helpers import give_payment, make_editor, png_bytes

ARABIC = re.compile(r"[؀-ۿ]")
MEDIA_ROOT = tempfile.mkdtemp(prefix="builder_api_media_")


def png(name="thumb.png"):
    return SimpleUploadedFile(name, png_bytes(), content_type="image/png")


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class BuilderApiTests(TestCase):
    # kind -> (fields to create a row with, the model, how to read those back)
    CREATE = {
        "skills": ({"skill": "DaVinci Resolve"}, Skill, lambda r: r.name == "DaVinci Resolve"),
        "education": (
            {"school": "Cairo University", "degree": "BA", "field": "Film", "year": "2020"},
            Education, lambda r: (r.school, r.grade_year) == ("Cairo University", date(2020, 1, 1)),
        ),
        "experience": (
            {"title": "Editor", "company": "Studio", "start": "2021-03", "end": ""},
            Experience, lambda r: (r.company, r.start_date, r.still_working) == ("Studio", date(2021, 3, 1), True),
        ),
        "projects": (
            {"name": "Brand Film", "url": "youtube.com/watch?v=abc", "video_type": "reel"},
            Project, lambda r: (r.title, r.url, r.video_type) == ("Brand Film", "https://youtube.com/watch?v=abc", "reel"),
        ),
        "links": ({"name": "Instagram", "url": "instagram.com/me"}, Link,
                  lambda r: (r.platform, r.url) == ("Instagram", "https://instagram.com/me")),
        "creators": ({"name": "MrBeast", "url": ""}, Creator, lambda r: r.name == "MrBeast"),
    }

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.user = make_editor(username="autosaver")
        Profile.objects.create(user=self.user)
        self.client.force_login(self.user)

    def post(self, path, data=None):
        return self.client.post(f"/builder/api/{path}", data or {})

    def events(self, name):
        return list(ActivationEvent.objects.filter(user=self.user, name=name).order_by("id")
                    .values_list("props", flat=True))

    # --- create / update / delete --------------------------------------------------

    def test_create_each_kind(self):
        for kind, (fields, model, check) in self.CREATE.items():
            with self.subTest(kind):
                res = self.post(f"{kind}/", fields)
                self.assertEqual(res.status_code, 201, res.content)
                body = res.json()
                row = model.objects.get(id=body["id"], user=self.user)
                self.assertTrue(check(row))
                self.assertTrue(body["ok"])
                self.assertEqual(body["item"]["id"], row.id)

    def test_update_changes_only_the_fields_sent(self):
        project = Project.objects.create(
            user=self.user, title="Old title", url="https://vimeo.com/1", details="Colour and cut", video_type="reel",
        )
        res = self.post(f"projects/{project.id}/", {"name": "New title"})
        self.assertEqual(res.status_code, 200, res.content)
        project.refresh_from_db()
        self.assertEqual(project.title, "New title")
        self.assertEqual((project.url, project.details, project.video_type), ("https://vimeo.com/1", "Colour and cut", "reel"))
        self.assertEqual(res.json()["item"]["name"], "New title")

    def test_update_each_kind(self):
        rows = {
            "skills": (Skill.objects.create(user=self.user, name="CapCut"), {"skill": "Premiere Pro"}, "name", "Premiere Pro"),
            "education": (Education.objects.create(user=self.user, school="A", degree="BA", field="Film",
                                                   grade_year=date(2019, 1, 1)), {"year": "2022"}, "grade_year", date(2022, 1, 1)),
            "experience": (Experience.objects.create(user=self.user, title="Editor", company="A", start_date=date(2020, 1, 1),
                                                     duration=0), {"end": "2023-06"}, "end_date", date(2023, 6, 1)),
            "projects": (Project.objects.create(user=self.user, title="Cut"), {"video_type": "reel"}, "video_type", "reel"),
            "links": (Link.objects.create(user=self.user, platform="X", url="https://x.com/me"), {"name": "Behance"},
                      "platform", "Behance"),
            "creators": (Creator.objects.create(user=self.user, name="A"), {"url": "https://youtube.com/@a"}, "url",
                         "https://youtube.com/@a"),
        }
        for kind, (row, fields, attr, expected) in rows.items():
            with self.subTest(kind):
                res = self.post(f"{kind}/{row.id}/", fields)
                self.assertEqual(res.status_code, 200, res.content)
                row.refresh_from_db()
                self.assertEqual(getattr(row, attr), expected)

    def test_delete_removes_only_that_row(self):
        gone = Link.objects.create(user=self.user, platform="X", url="https://x.com/me")
        kept = Link.objects.create(user=self.user, platform="Behance", url="https://behance.net/me")
        res = self.post(f"links/{gone.id}/delete/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"ok": True, "id": gone.id})
        self.assertFalse(Link.objects.filter(id=gone.id).exists())
        self.assertTrue(Link.objects.filter(id=kept.id).exists())

    # --- ownership and routing -------------------------------------------------------

    def test_another_users_row_is_404_and_unchanged(self):
        other = make_editor(username="someone_else")
        theirs = Project.objects.create(user=other, title="Not yours")
        self.assertEqual(self.post(f"projects/{theirs.id}/", {"name": "Mine now"}).status_code, 404)
        self.assertEqual(self.post(f"projects/{theirs.id}/delete/").status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "Not yours")

    def test_unknown_kind_is_404(self):
        self.assertEqual(self.post("reviews/", {"name": "x"}).status_code, 404)

    def test_signed_out_gets_401_json(self):
        self.client.logout()
        res = self.post("skills/", {"skill": "Premiere Pro"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json(), {"ok": False, "error": "signed_out"})
        self.assertFalse(Skill.objects.exists())

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get("/builder/api/skills/").status_code, 405)

    def test_another_users_collection_is_refused(self):
        other = make_editor(username="someone_else")
        their_collection = ProjectCategory.objects.create(user=other, name="Theirs")
        project = Project.objects.create(user=self.user, title="Cut")
        res = self.post(f"projects/{project.id}/", {"category_id": str(their_collection.id)})
        self.assertEqual(res.status_code, 400)
        self.assertIn("category_id", res.json()["errors"])
        project.refresh_from_db()
        self.assertIsNone(project.category)

    # --- validation ----------------------------------------------------------------

    def test_invalid_value_returns_field_errors_and_saves_nothing(self):
        res = self.post("links/", {"name": "Instagram"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(list(res.json()["errors"]), ["url"])
        self.assertFalse(Link.objects.exists())

    def test_new_video_needs_a_link_or_a_title(self):
        res = self.post("projects/", {"description": "Colour and cut"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(list(res.json()["errors"]), ["url"])
        self.assertFalse(Project.objects.exists())

    def test_a_video_added_by_link_takes_the_link_title(self):
        meta = VideoMeta(url="https://www.youtube.com/watch?v=abcdefghijk", provider="youtube", title="Nike — Run Cairo")
        with patch("core.oembed.fetch", return_value=meta):
            res = self.post("projects/", {"url": "https://www.youtube.com/watch?v=abcdefghijk"})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Project.objects.get(id=res.json()["id"]).title, "Nike — Run Cairo")
        self.assertEqual(res.json()["item"]["name"], "Nike — Run Cairo")

    def test_bad_booking_link_does_not_save_the_other_fields_sent_with_it(self):
        PersonalInfo.objects.create(user=self.user, full_name="Sara Ali", title="Colorist", email="", phone="", bio="")
        res = self.post("personal/", {"booking_url": "not a link", "bio": "Hi"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(list(res.json()["errors"]), ["booking_url"])
        self.assertEqual(PersonalInfo.objects.get(user=self.user).bio, "")

    def test_an_old_invalid_value_does_not_block_editing_another_field(self):
        """A phone saved before today's rules must not stop the user changing their title."""
        PersonalInfo.objects.create(user=self.user, full_name="Sara Ali", title="Video Editor", email="",
                                    phone="call me", bio="")
        res = self.post("personal/", {"title": "Colorist"})
        self.assertEqual(res.status_code, 200, res.content)
        info = PersonalInfo.objects.get(user=self.user)
        self.assertEqual((info.title, info.phone), ("Colorist", "call me"))

    def test_sending_the_invalid_value_itself_is_refused(self):
        PersonalInfo.objects.create(user=self.user, full_name="Sara Ali", title="Video Editor", email="",
                                    phone="", bio="")
        res = self.post("personal/", {"phone": "call me"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("phone", res.json()["errors"])

    def test_arabic_errors(self):
        res = self.post("links/", {"name": "Instagram", "lang": "ar"})
        self.assertRegex(res.json()["errors"]["url"][0], ARABIC)
        PersonalInfo.objects.create(user=self.user, full_name="Sara", title="Editor", email="", phone="", bio="")
        res = self.post("personal/", {"booking_url": "not a link", "lang": "ar"})
        self.assertRegex(res.json()["errors"]["booking_url"][0], ARABIC)

    # --- personal info -------------------------------------------------------------

    def test_personal_info_is_created_for_a_new_user(self):
        res = self.post("personal/", {"fullname": "Sara Ali", "title": "Colorist"})
        self.assertEqual(res.status_code, 200, res.content)
        info = PersonalInfo.objects.get(user=self.user)
        self.assertEqual((info.full_name, info.title), ("Sara Ali", "Colorist"))
        self.assertEqual(res.json()["item"]["fullname"], "Sara Ali")

    def test_profile_picture_upload(self):
        PersonalInfo.objects.create(user=self.user, full_name="Sara", title="Editor", email="", phone="", bio="")
        res = self.post("personal/", {"picture": png("me.png")})
        self.assertEqual(res.status_code, 200, res.content)
        profile = Profile.objects.get(user=self.user)
        self.assertTrue(profile.picture)
        self.assertEqual(res.json()["item"]["picture"], profile.picture.url)

    # --- images --------------------------------------------------------------------

    def test_thumbnail_is_stored_under_a_generated_name(self):
        project = Project.objects.create(user=self.user, title="Cut")
        res = self.post(f"projects/{project.id}/", {"thumbnail": png("../../evil name.png")})
        self.assertEqual(res.status_code, 200, res.content)
        project.refresh_from_db()
        self.assertRegex(project.image.name, r"thumb_[0-9a-f]{12}\.png$")
        self.assertEqual(res.json()["item"]["thumbnail"], project.image.url)

    def test_image_upload_with_a_new_row(self):
        res = self.post("creators/", {"name": "MrBeast", "image": png()})
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(Creator.objects.get(id=res.json()["id"]).image)

    def test_a_file_that_is_not_an_image_is_refused(self):
        project = Project.objects.create(user=self.user, title="Cut")
        fake = SimpleUploadedFile("thumb.png", b"not really a png", content_type="image/png")
        res = self.post(f"projects/{project.id}/", {"thumbnail": fake, "name": "Renamed"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("thumbnail", res.json()["errors"])
        project.refresh_from_db()
        self.assertEqual((project.title, bool(project.image)), ("Cut", False))

    def test_an_image_over_5_mb_is_refused(self):
        project = Project.objects.create(user=self.user, title="Cut")
        big = SimpleUploadedFile("big.png", png_bytes() + b"\0" * (5 * 1024 * 1024), content_type="image/png")
        res = self.post(f"projects/{project.id}/", {"thumbnail": big})
        self.assertEqual(res.status_code, 400)
        self.assertIn("thumbnail", res.json()["errors"])

    def test_no_upload_keeps_the_current_thumbnail(self):
        project = Project.objects.create(user=self.user, title="Cut", image=png())
        name = project.image.name
        self.post(f"projects/{project.id}/", {"name": "Renamed"})
        project.refresh_from_db()
        self.assertEqual(project.image.name, name)

    # --- side effects --------------------------------------------------------------

    def test_first_project_returns_the_reveal_link(self):
        first = self.post("projects/", {"name": "First"}).json()
        second = self.post("projects/", {"name": "Second"}).json()
        self.assertIn("/autosaver/", first["reveal_url"])
        self.assertNotIn("reveal_url", second)

    def test_saves_are_tracked(self):
        created = self.post("skills/", {"skill": "CapCut"}).json()
        self.post(f"skills/{created['id']}/", {"skill": "Premiere Pro"})
        self.post("links/", {"name": "Instagram"})
        self.post(f"skills/{created['id']}/delete/")
        self.assertEqual(self.events("builder_item_saved"), [
            {"kind": "skills", "created": True}, {"kind": "skills", "created": False},
        ])
        self.assertEqual(self.events("builder_item_save_failed"), [
            {"kind": "links", "fields": ["url"], "reason": "invalid"},
        ])
        self.assertEqual(self.events("builder_item_deleted"), [{"kind": "skills"}])

    def test_a_save_makes_a_paid_portfolio_public(self):
        give_payment(self.user)
        self.post("skills/", {"skill": "CapCut"})
        self.assertTrue(Profile.objects.get(user=self.user).is_public)

    def test_an_unpaid_portfolio_stays_private(self):
        self.post("skills/", {"skill": "CapCut"})
        self.assertFalse(Profile.objects.get(user=self.user).is_public)
