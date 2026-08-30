import base64

from django.test import TestCase, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from core.models import Profile, Project
from builder.forms import (
    PersonalInfoForm,
    SkillFormSet,
    EducationFormSet,
    ExperienceFormSet,
    ProjectFormSet,
    LinkFormSet,
    CreatorFormSet,
)
from builder.views import save_portfolio_data


class SavePortfolioDataTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="editor1", email="editor1@example.com", password="pass12345"
        )
        Profile.objects.create(user=self.user)
        self.request = RequestFactory().get("/builder/")
        self.request.user = self.user

    def _base_post(self, projects_rows):
        post = {
            "fullname": "Editor One",
            "title": "Video Editor",
        }
        for prefix, rows in [
            ("skills", []),
            ("education", []),
            ("experience", []),
            ("projects", projects_rows),
            ("links", []),
            ("creators", []),
        ]:
            post[f"{prefix}-TOTAL_FORMS"] = str(len(rows))
            post[f"{prefix}-INITIAL_FORMS"] = str(len([r for r in rows if r.get("id")]))
            post[f"{prefix}-MIN_NUM_FORMS"] = "0"
            post[f"{prefix}-MAX_NUM_FORMS"] = "1000"
            for i, row in enumerate(rows):
                for key, value in row.items():
                    post[f"{prefix}-{i}-{key}"] = value
        return post

    def _project_row(self, name, project_id="", video_type="long", url="https://example.com"):
        return {
            "id": str(project_id) if project_id else "",
            "name": name,
            "url": url,
            "description": "",
            "video_type": video_type,
            "category_id": "",
        }

    def _call_save(self, post_data, files=None):
        personal_form = PersonalInfoForm(post_data)
        skill_formset = SkillFormSet(post_data, prefix="skills")
        education_formset = EducationFormSet(post_data, prefix="education")
        experience_formset = ExperienceFormSet(post_data, prefix="experience")
        project_formset = ProjectFormSet(post_data, files, prefix="projects")
        link_formset = LinkFormSet(post_data, prefix="links")
        creator_formset = CreatorFormSet(post_data, files, prefix="creators")
        self.assertTrue(personal_form.is_valid(), personal_form.errors)
        self.assertTrue(skill_formset.is_valid(), skill_formset.errors)
        self.assertTrue(education_formset.is_valid(), education_formset.errors)
        self.assertTrue(experience_formset.is_valid(), experience_formset.errors)
        self.assertTrue(project_formset.is_valid(), project_formset.errors)
        self.assertTrue(link_formset.is_valid(), link_formset.errors)
        self.assertTrue(creator_formset.is_valid(), creator_formset.errors)
        save_portfolio_data(
            self.request, personal_form, skill_formset, education_formset,
            experience_formset, project_formset, link_formset, creator_formset,
        )

    def test_existing_projects_updated_in_place_not_duplicated(self):
        p1 = Project.objects.create(user=self.user, title="Project A", url="https://a.example")
        p2 = Project.objects.create(user=self.user, title="Project B", url="https://b.example")

        post = self._base_post([
            self._project_row("Project A", project_id=p1.id),
            self._project_row("Project B Renamed", project_id=p2.id),
            self._project_row("Project C", video_type="reel"),
        ])
        self._call_save(post)

        projects = list(Project.objects.filter(user=self.user).order_by("id"))
        self.assertEqual(len(projects), 3)

        updated = Project.objects.get(id=p2.id)
        self.assertEqual(updated.title, "Project B Renamed")

        self.assertTrue(Project.objects.filter(user=self.user, title="Project C", video_type="reel").exists())
        self.assertTrue(Project.objects.filter(user=self.user, title="Project A").exists())

    def test_removed_projects_are_deleted(self):
        p1 = Project.objects.create(user=self.user, title="Project A")
        p2 = Project.objects.create(user=self.user, title="Project B")

        post = self._base_post([
            self._project_row("Project A", project_id=p1.id),
        ])
        self._call_save(post)

        self.assertFalse(Project.objects.filter(id=p2.id).exists())
        self.assertEqual(Project.objects.filter(user=self.user).count(), 1)

    def _png(self, name="thumb.png"):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        return SimpleUploadedFile(name, png, content_type="image/png")

    def test_existing_thumbnail_preserved_when_no_new_file(self):
        image = self._png()
        p1 = Project.objects.create(user=self.user, title="Project A", image=image)

        post = self._base_post([
            self._project_row("Project A Renamed", project_id=p1.id),
        ])
        self._call_save(post)

        p1.refresh_from_db()
        self.assertEqual(p1.title, "Project A Renamed")
        self.assertTrue(p1.image)

    def test_new_project_with_uploaded_thumbnail(self):
        image = self._png("new.png")
        post = self._base_post([
            self._project_row("Brand New"),
        ])
        self._call_save(post, files={"projects-0-thumbnail": image})

        project = Project.objects.get(user=self.user, title="Brand New")
        self.assertTrue(project.image)


class SectionLayoutEndpointTests(TestCase):
    """ajax_save_section_layout: save, validation, and reset."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="layout1", email="layout1@example.com", password="pass12345"
        )
        Profile.objects.create(user=self.user)
        self.client.force_login(self.user)
        self.url = "/builder/ajax/save-section-layout/"

    def test_save_valid_order_and_visibility(self):
        payload = {
            "section_order": '["reviews", "projects", "skills", "experience", "education", "links", "contact", "creators"]',
            "section_visibility": '{"creators": false, "education": false}',
        }
        res = self.client.post(self.url, payload)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.section_order[0], "reviews")
        self.assertFalse(profile.section_visibility["creators"])

    def test_unknown_keys_rejected(self):
        res = self.client.post(self.url, {"section_order": '["bogus_section"]'})
        self.assertEqual(res.status_code, 400)
        self.assertIn("bogus_section", res.json()["invalid_keys"])

    def test_missing_sections_appended(self):
        res = self.client.post(self.url, {"section_order": '["skills"]'})
        self.assertEqual(res.status_code, 200)
        saved = Profile.objects.get(user=self.user).section_order
        self.assertEqual(saved[0], "skills")
        # Every supported section stays reachable.
        self.assertEqual(len(saved), 8)

    def test_hiding_every_section_rejected(self):
        payload = {
            "section_order": '["projects", "skills"]',
            "section_visibility": '{"projects": false, "skills": false, "experience": false, "education": false, "reviews": false, "creators": false, "links": false, "contact": false}',
        }
        res = self.client.post(self.url, payload)
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.json())

    def test_reset_clears_layout(self):
        profile = Profile.objects.get(user=self.user)
        profile.section_order = ["reviews", "projects"]
        profile.section_visibility = {"creators": False}
        profile.save()
        res = self.client.post(self.url, {"reset": "1"})
        self.assertEqual(res.status_code, 200)
        profile.refresh_from_db()
        self.assertEqual(profile.section_order, [])
        self.assertEqual(profile.section_visibility, {})

    def test_login_required(self):
        self.client.logout()
        res = self.client.post(self.url, {"reset": "1"})
        self.assertEqual(res.status_code, 302)


class SectionLayoutPanelTests(TestCase):
    """The layout panel renders only for themes whose public template ships
    the section_layout_css block (core.section_order.LAYOUT_ENABLED_THEMES).
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="paneluser", email="panel@example.com", password="pass12345"
        )

    def _pick_theme(self, name):
        """Get or seed the named theme under the Video Editor category."""
        from core.models import Theme, Category
        cat, _ = Category.objects.get_or_create(name="Video Editor")
        theme, _ = Theme.objects.get_or_create(name=name, defaults={"category": cat})
        if theme.category is None:
            theme.category = cat
            theme.save()
        return theme

    def test_minimal_theme_gets_layout_panel(self):
        theme = self._pick_theme("Minimal")
        Profile.objects.create(user=self.user, theme=theme)
        self.client.force_login(self.user)
        res = self.client.get("/builder/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertTrue(res.context["section_layout_enabled"])
        self.assertIn('data-key="order"', html)
        self.assertIn("bx-order-list", html)
        self.assertTrue(res.context["section_presets"])

    def test_non_video_editor_theme_has_no_layout_panel(self):
        from core.models import Theme, Category
        cat, _ = Category.objects.get_or_create(name="Developer")
        theme, _ = Theme.objects.get_or_create(name="Creative", defaults={"category": cat})
        if theme.category is None:
            theme.category = cat
            theme.save()
        Profile.objects.create(user=self.user, theme=theme)
        self.client.force_login(self.user)
        res = self.client.get("/builder/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context["section_layout_enabled"])
        self.assertNotIn('data-key="order"', res.content.decode())

    def test_custom_order_persists_to_context(self):
        from core.section_order import resolve_section_layout
        theme = self._pick_theme("Minimal")
        Profile.objects.create(
            user=self.user, theme=theme,
            section_order=["reviews", "projects", "skills", "experience", "education", "links", "contact", "creators"],
        )
        layout = resolve_section_layout(Profile.objects.get(user=self.user), "video_editor")
        self.assertTrue(layout["custom"])
        self.assertEqual(layout["order_keys"][0], "reviews")


class PresetsForTests(TestCase):
    """presets_for filters unsupported keys per theme family."""

    def test_video_editor_presets_complete(self):
        from core.section_order import presets_for
        rows = presets_for("video_editor")
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertTrue(set(row["order"]).issubset(set(row["order"])))
            self.assertEqual(len(row["order"]), 8)
            self.assertIn("label_ar", row)

    def test_display_name_category_matches_slug(self):
        # The builder UI and the public page must agree whether the category
        # is stored as "Video Editor" (label) or "video_editor" (slug).
        from core.section_order import presets_for, supported_keys
        self.assertEqual(supported_keys("Video Editor"), supported_keys("video_editor"))
        self.assertEqual([r["key"] for r in presets_for("Video Editor")],
                         [r["key"] for r in presets_for("video_editor")])

    def test_developer_presets_filter_unsupported_keys(self):
        from core.section_order import presets_for
        rows = presets_for("developer")
        for row in rows:
            self.assertNotIn("reviews", row["order"])
            self.assertNotIn("contact", row["order"])
