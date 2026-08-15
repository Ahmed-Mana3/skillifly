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
