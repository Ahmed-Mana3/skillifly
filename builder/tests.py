import base64

from django.test import TestCase, RequestFactory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model

from core.models import Profile, Project, ProjectCategory
from builder.forms import (
    PersonalInfoForm,
    SkillFormSet,
    EducationFormSet,
    ExperienceFormSet,
    ProjectFormSet,
    ProjectFormSetUpdate,
    LinkFormSet,
    CreatorFormSet,
)
from builder.views import save_portfolio_data


class BookingUrlFieldTests(TestCase):
    """The booking field is free text; it must never store a dead link."""

    def _clean(self, value):
        form = PersonalInfoForm({
            "fullname": "Editor One",
            "title": "Video Editor",
            "booking_url": value,
        })
        self.assertTrue(form.is_valid(), form.errors)
        return form.cleaned_data["booking_url"]

    def test_phone_number_becomes_a_whatsapp_link(self):
        self.assertEqual(self._clean("01018344501"), "https://wa.me/01018344501")
        self.assertEqual(self._clean("wa.me/201001234567"), "https://wa.me/201001234567")
        self.assertEqual(
            self._clean("https://wa.me/+20 11 50431732"),
            "https://wa.me/+201150431732",
        )

    def test_bare_domain_gets_a_scheme(self):
        self.assertEqual(self._clean("calendly.com/you"), "https://calendly.com/you")

    def test_half_typed_host_is_rejected_instead_of_saved(self):
        form = PersonalInfoForm({
            "fullname": "Editor One",
            "title": "Video Editor",
            "booking_url": "https://Mm",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("booking_url", form.errors)


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


class ProjectCategoryAssignmentTests(TestCase):
    """Assigning a category chip to a project row must never break validation.

    Regression: ProjectFormSet is built with extra=1, so the builder always
    renders one blank placeholder row. Clicking a category chip writes into the
    hidden ``category_id`` input, which used to flip ``has_changed()`` to True,
    defeat Django's ``empty_permitted`` shortcut and raise a bogus
    "name: This field is required." on the untouched row.
    """

    def _formset(self, cls=ProjectFormSet, user=None, **kwargs_row):
        row = {"video_type": "long"}
        row.update(kwargs_row)
        data = {
            "projects-TOTAL_FORMS": "1",
            "projects-INITIAL_FORMS": "0",
            "projects-MIN_NUM_FORMS": "0",
            "projects-MAX_NUM_FORMS": "1000",
        }
        data.update({f"projects-0-{k}": v for k, v in row.items()})
        return cls(data=data, prefix="projects", form_kwargs={"user": user})

    def _pick_theme(self, name):
        from core.models import Theme, Category
        cat, _ = Category.objects.get_or_create(name="Video Editor")
        theme, _ = Theme.objects.get_or_create(name=name, defaults={"category": cat})
        if theme.category is None:
            theme.category = cat
            theme.save()
        return theme

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="catuser", email="catuser@example.com", password="pass12345"
        )
        # A "categories" theme is what renders the collection chips in the builder.
        Profile.objects.create(user=self.user, theme=self._pick_theme("Categories"))
        self.client.force_login(self.user)
        # Simulates the AJAX call the builder makes when the user creates a
        # collection: the category is persisted immediately and returned with its
        # fresh id, which the chips then carry as data-value.
        res = self.client.post(
            "/builder/ajax/save-category/",
            {"name": "Brand Work", "description": "Client campaigns"},
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.category = ProjectCategory.objects.get(user=self.user, name="Brand Work")

    def _post_builder(self, **project_row):
        row = {"video_type": "long", "url": "", "description": ""}
        row.update(project_row)
        post = {"fullname": "Editor One", "title": "Video Editor"}
        for prefix, rows in [
            ("skills", []),
            ("education", []),
            ("experience", []),
            ("projects", [row]),
            ("links", []),
            ("creators", []),
        ]:
            post[f"{prefix}-TOTAL_FORMS"] = str(len(rows))
            post[f"{prefix}-INITIAL_FORMS"] = "0"
            post[f"{prefix}-MIN_NUM_FORMS"] = "0"
            post[f"{prefix}-MAX_NUM_FORMS"] = "1000"
            for i, r in enumerate(rows):
                for key, value in r.items():
                    post[f"{prefix}-{i}-{key}"] = value
        return self.client.post("/builder/", post)

    # --- form-level guard ---

    def test_chip_on_blank_placeholder_row_does_not_require_a_name(self):
        formset = self._formset(category_id=str(self.category.id))
        form = formset.forms[0]
        self.assertTrue(form.empty_permitted)
        self.assertFalse(form.has_changed())
        self.assertTrue(formset.is_valid(), formset.errors)

    def test_chip_on_blank_row_is_still_ignored_in_update_flow(self):
        formset = self._formset(ProjectFormSetUpdate, category_id=str(self.category.id))
        self.assertTrue(formset.is_valid(), formset.errors)

    def test_uncategorized_blank_row_still_passes(self):
        formset = self._formset(category_id="")
        self.assertTrue(formset.is_valid(), formset.errors)

    def test_genuinely_filled_row_is_detected_as_changed(self):
        formset = self._formset(name="Brand Campaign", category_id=str(self.category.id))
        self.assertTrue(formset.forms[0].has_changed())
        self.assertTrue(formset.is_valid(), formset.errors)

    def test_blank_name_still_errors_when_the_row_is_really_filled(self):
        """The fix must not blanket-disable required-field validation."""
        formset = self._formset(name="", url="https://example.com",
                               category_id=str(self.category.id))
        self.assertFalse(formset.is_valid())
        self.assertIn("name", formset.forms[0].errors)

    # --- end-to-end through the builder view ---

    def test_new_project_saves_with_the_brand_new_category(self):
        res = self._post_builder(name="Nike Campaign", category_id=str(self.category.id))
        self.assertEqual(res.status_code, 302, getattr(res, "context_data", ""))
        project = Project.objects.get(user=self.user, title="Nike Campaign")
        self.assertEqual(project.category, self.category)

    def test_blank_chip_only_row_creates_no_phantom_project(self):
        res = self._post_builder(name="", category_id=str(self.category.id))
        self.assertEqual(res.status_code, 302)
        self.assertEqual(Project.objects.filter(user=self.user).count(), 0)

    def test_reassignment_to_the_new_category_persists(self):
        existing = Project.objects.create(user=self.user, title="Old Cut")
        post = {
            "fullname": "Editor One",
            "title": "Video Editor",
            "projects-TOTAL_FORMS": "1",
            "projects-INITIAL_FORMS": "1",
            "projects-MIN_NUM_FORMS": "0",
            "projects-MAX_NUM_FORMS": "1000",
            "projects-0-id": str(existing.id),
            "projects-0-name": "Old Cut",
            "projects-0-url": "",
            "projects-0-description": "",
            "projects-0-video_type": "long",
            "projects-0-category_id": str(self.category.id),
        }
        for prefix in ("skills", "education", "experience", "links", "creators"):
            post[f"{prefix}-TOTAL_FORMS"] = "0"
            post[f"{prefix}-INITIAL_FORMS"] = "0"
            post[f"{prefix}-MIN_NUM_FORMS"] = "0"
            post[f"{prefix}-MAX_NUM_FORMS"] = "1000"

        res = self.client.post("/builder/update/", post)
        self.assertEqual(res.status_code, 302)
        existing.refresh_from_db()
        self.assertEqual(existing.category, self.category)

    def test_server_side_name_error_is_rendered_next_to_the_field(self):
        """The generic banner alone is not actionable; the error must be inline."""
        res = self._post_builder(name="", category_id=str(self.category.id),
                                 url="https://example.com")
        self.assertEqual(res.status_code, 200)
        self.assertIn("This field is required.", res.content.decode())

    def test_rendered_builder_offers_the_newly_created_category_chip(self):
        res = self.client.get("/builder/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(f'data-value="{self.category.id}"', res.content.decode())


class ProjectCategoryOwnershipTests(TestCase):
    """A submitted category id must belong to the signed-in user.

    ``category_id`` is a hidden CharField, so without an ownership check a
    tampered or stale id used to resolve to None in ``_category_for`` and the
    assignment was dropped with no feedback at all.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="owner1", email="owner1@example.com", password="pass12345"
        )
        self.other = User.objects.create_user(
            username="owner2", email="owner2@example.com", password="pass12345"
        )
        self.mine = ProjectCategory.objects.create(user=self.user, name="Mine")
        self.theirs = ProjectCategory.objects.create(user=self.other, name="Theirs")

    def _formset(self, category_id, user):
        data = {
            "projects-TOTAL_FORMS": "1",
            "projects-INITIAL_FORMS": "0",
            "projects-MIN_NUM_FORMS": "0",
            "projects-MAX_NUM_FORMS": "1000",
            "projects-0-video_type": "long",
            "projects-0-name": "Some Campaign",
            "projects-0-category_id": str(category_id),
        }
        return ProjectFormSet(data=data, prefix="projects", form_kwargs={"user": user})

    def test_own_category_is_accepted_and_normalised_to_int(self):
        formset = self._formset(self.mine.id, self.user)
        self.assertTrue(formset.is_valid(), formset.errors)
        cleaned = formset.forms[0].cleaned_data["category_id"]
        self.assertEqual(cleaned, self.mine.id)
        self.assertIsInstance(cleaned, int)

    def test_another_users_category_is_rejected(self):
        formset = self._formset(self.theirs.id, self.user)
        self.assertFalse(formset.is_valid())
        self.assertIn("category_id", formset.forms[0].errors)

    def test_unknown_id_is_rejected(self):
        formset = self._formset(99999, self.user)
        self.assertFalse(formset.is_valid())
        self.assertIn("category_id", formset.forms[0].errors)

    def test_non_numeric_id_is_rejected(self):
        formset = self._formset("abc", self.user)
        self.assertFalse(formset.is_valid())
        self.assertIn("category_id", formset.forms[0].errors)

    def test_blank_id_is_allowed(self):
        data = {
            "projects-TOTAL_FORMS": "1",
            "projects-INITIAL_FORMS": "0",
            "projects-MIN_NUM_FORMS": "0",
            "projects-MAX_NUM_FORMS": "1000",
            "projects-0-video_type": "long",
            "projects-0-name": "Some Campaign",
            "projects-0-category_id": "",
        }
        formset = ProjectFormSet(data=data, prefix="projects", form_kwargs={"user": self.user})
        self.assertTrue(formset.is_valid(), formset.errors)

    def test_builder_view_refuses_to_save_a_foreign_category(self):
        """End-to-end: the tampered id must not silently become None."""
        from core.models import Profile, Theme, Category
        cat, _ = Category.objects.get_or_create(name="Video Editor")
        theme, _ = Theme.objects.get_or_create(name="Categories", defaults={"category": cat})
        Profile.objects.create(user=self.user, theme=theme)
        self.client.force_login(self.user)

        post = {"fullname": "Editor One", "title": "Video Editor"}
        for prefix in ("skills", "education", "experience", "links", "creators"):
            post[f"{prefix}-TOTAL_FORMS"] = "0"
            post[f"{prefix}-INITIAL_FORMS"] = "0"
            post[f"{prefix}-MIN_NUM_FORMS"] = "0"
            post[f"{prefix}-MAX_NUM_FORMS"] = "1000"
        post.update({
            "projects-TOTAL_FORMS": "1",
            "projects-INITIAL_FORMS": "0",
            "projects-MIN_NUM_FORMS": "0",
            "projects-MAX_NUM_FORMS": "1000",
            "projects-0-name": "Stolen Category Project",
            "projects-0-video_type": "long",
            "projects-0-category_id": str(self.theirs.id),
        })

        res = self.client.post("/builder/", post)
        self.assertEqual(res.status_code, 200)  # re-rendered with an error
        self.assertFalse(Project.objects.filter(user=self.user).exists())
        self.assertIn("no longer available", res.content.decode())

    def test_builder_update_view_refuses_a_foreign_category(self):
        from core.models import Profile, Theme, Category
        existing = Project.objects.create(user=self.user, title="Existing")
        cat, _ = Category.objects.get_or_create(name="Video Editor")
        theme, _ = Theme.objects.get_or_create(name="Categories", defaults={"category": cat})
        Profile.objects.create(user=self.user, theme=theme)
        self.client.force_login(self.user)

        post = {"fullname": "Editor One", "title": "Video Editor"}
        for prefix in ("skills", "education", "experience", "links", "creators"):
            post[f"{prefix}-TOTAL_FORMS"] = "0"
            post[f"{prefix}-INITIAL_FORMS"] = "0"
            post[f"{prefix}-MIN_NUM_FORMS"] = "0"
            post[f"{prefix}-MAX_NUM_FORMS"] = "1000"
        post.update({
            "projects-TOTAL_FORMS": "1",
            "projects-INITIAL_FORMS": "1",
            "projects-MIN_NUM_FORMS": "0",
            "projects-MAX_NUM_FORMS": "1000",
            "projects-0-id": str(existing.id),
            "projects-0-name": "Existing",
            "projects-0-video_type": "long",
            "projects-0-category_id": str(self.theirs.id),
        })

        res = self.client.post("/builder/update/", post)
        self.assertEqual(res.status_code, 200)
        existing.refresh_from_db()
        self.assertIsNone(existing.category)
        self.assertFalse(Project.objects.filter(category=self.theirs).exists())

    def test_arabic_builder_uses_the_arabic_message(self):
        from core.models import Profile, Theme, Category
        cat, _ = Category.objects.get_or_create(name="Video Editor")
        theme, _ = Theme.objects.get_or_create(name="Categories", defaults={"category": cat})
        Profile.objects.create(user=self.user, theme=theme)
        self.client.force_login(self.user)

        post = {"fullname": "محرر", "title": "مونتير"}
        for prefix in ("skills", "education", "experience", "links", "creators"):
            post[f"{prefix}-TOTAL_FORMS"] = "0"
            post[f"{prefix}-INITIAL_FORMS"] = "0"
            post[f"{prefix}-MIN_NUM_FORMS"] = "0"
            post[f"{prefix}-MAX_NUM_FORMS"] = "1000"
        post.update({
            "projects-TOTAL_FORMS": "1",
            "projects-INITIAL_FORMS": "0",
            "projects-MIN_NUM_FORMS": "0",
            "projects-MAX_NUM_FORMS": "1000",
            "projects-0-name": "حملة",
            "projects-0-video_type": "long",
            "projects-0-category_id": str(self.theirs.id),
        })

        res = self.client.post("/ar/builder/", post)
        self.assertEqual(res.status_code, 200)
        self.assertIn("لم تعد متاحة", res.content.decode())

    def test_deleted_category_is_reported_not_silently_dropped(self):
        """The chip can outlive its category if it is deleted in another tab."""
        stale_id = self.mine.id
        self.mine.delete()
        formset = self._formset(stale_id, self.user)
        self.assertFalse(formset.is_valid())
        self.assertIn("category_id", formset.forms[0].errors)


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
