"""The signup default title ("Video Editor") counts as the user's own once they keep it."""
from django.test import TestCase

from core import onboarding
from core.models import PersonalInfo, Profile
from core.testing_helpers import make_editor, seed_themes


def info(**fields):
    defaults = {"title": "Video Editor", "title_confirmed": False}
    defaults.update(fields)
    return PersonalInfo(**defaults)


class TitleCountsTests(TestCase):
    def test_rules(self):
        cases = [
            (info(), False, "the untouched signup default"),
            (info(title="video editor"), False, "in any case"),
            (info(title="مونتير فيديو"), False, "Arabic default"),
            (info(title_confirmed=True), True, "the default, kept"),
            (info(title="Colorist"), True, "a title they wrote"),
            (info(title="  "), False, "blank"),
            (None, False, "no personal info"),
        ]
        for value, expected, label in cases:
            with self.subTest(label):
                self.assertEqual(onboarding.title_counts(value), expected)

    def test_client_ready_uses_it(self):
        user = make_editor()
        PersonalInfo.objects.create(user=user, full_name="Sara", title="Video Editor", email="", phone="", bio="")
        self.assertFalse(onboarding.client_ready(user)["title"])
        PersonalInfo.objects.filter(user=user).update(title_confirmed=True)
        self.assertTrue(onboarding.client_ready(user)["title"])


class TitleConfirmedOnSaveTests(TestCase):
    def setUp(self):
        self.user = make_editor()
        Profile.objects.create(user=self.user, theme=seed_themes()["Creative"])
        PersonalInfo.objects.create(user=self.user, full_name="Sara Ali", title="Video Editor", email="", phone="", bio="")
        self.client.force_login(self.user)

    def confirmed(self):
        return PersonalInfo.objects.get(user=self.user).title_confirmed

    def legacy_post(self, **fields):
        post = {"fullname": "Sara Ali", "title": "Video Editor", **fields}
        for prefix in ("skills", "education", "experience", "projects", "links", "creators"):
            post.update({f"{prefix}-TOTAL_FORMS": "0", f"{prefix}-INITIAL_FORMS": "0",
                         f"{prefix}-MIN_NUM_FORMS": "0", f"{prefix}-MAX_NUM_FORMS": "1000"})
        res = self.client.post("/builder/update/", post)
        self.assertEqual(res.status_code, 302)

    # --- autosave API ---------------------------------------------------------------

    def test_autosave_editing_something_else_does_not_confirm(self):
        self.client.post("/builder/api/personal/", {"bio": "Hi"})
        self.assertFalse(self.confirmed())

    def test_autosave_sending_the_title_confirms_it_even_unchanged(self):
        self.client.post("/builder/api/personal/", {"title": "Video Editor"})
        self.assertTrue(self.confirmed())

    # --- full-form Save --------------------------------------------------------------

    def test_save_carrying_the_default_along_does_not_confirm(self):
        self.legacy_post(title_confirmed="0")
        self.assertFalse(self.confirmed())

    def test_save_after_keep_or_typing_confirms(self):
        self.legacy_post(title_confirmed="1")
        self.assertTrue(self.confirmed())

    def test_a_title_of_their_own_counts_without_the_flag(self):
        self.legacy_post(title="Colorist")
        self.assertTrue(self.confirmed())

    def test_a_kept_title_stays_kept(self):
        PersonalInfo.objects.filter(user=self.user).update(title_confirmed=True)
        self.legacy_post(title_confirmed="0", bio="New bio")
        self.assertTrue(self.confirmed())

    # --- other places a title is saved -------------------------------------------------

    def test_launch_about_you_step_confirms(self):
        res = self.client.post("/launch/about-you/", {"fullname": "Sara Ali", "title": "Video Editor"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(self.confirmed())

    def test_the_assistant_setting_the_title_confirms(self):
        from agent.tools import update_personal_info
        update_personal_info(self.user, title="Video Editor")
        self.assertTrue(self.confirmed())

    # --- the builder page --------------------------------------------------------------

    def test_page_offers_to_keep_the_default(self):
        html = self.client.get("/builder/update/").content.decode()
        self.assertIn('id="f-title-confirmed" name="title_confirmed" value="0"', html)
        self.assertIn('data-action="keep-title"', html)
        self.assertIn("Your job title", html)
        PersonalInfo.objects.filter(user=self.user).update(title_confirmed=True)
        html = self.client.get("/builder/update/").content.decode()
        self.assertIn('id="f-title-confirmed" name="title_confirmed" value="1"', html)
