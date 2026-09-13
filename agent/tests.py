from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch, MagicMock
import json
from core.models import (
    CustomUser,
    Profile,
    PersonalInfo,
    Skill,
    Project,
    ProjectCategory,
    Experience,
    Education,
    Link,
    Theme,
    Category,
    AgentConversation,
    AgentMessage,
    PortfolioSnapshot,
    ClientReview,
)
from agent import tools
from agent.services import AgentService


class AgentToolsTestCase(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="alex_editor",
            email="alex@example.com",
            password="securepassword123",
        )
        self.other_user = CustomUser.objects.create_user(
            username="sarah_motion",
            email="sarah@example.com",
            password="securepassword123",
        )
        self.cat = Category.objects.create(name="Video Editor")
        self.theme = Theme.objects.create(name="Creative", category=self.cat)
        self.theme_min = Theme.objects.create(name="Minimal", category=self.cat)

        self.profile = Profile.objects.create(user=self.user, theme=self.theme)
        self.personal_info = PersonalInfo.objects.create(
            user=self.user,
            full_name="Alex Mercer",
            title="Senior Colorist & Editor",
            email="alex@example.com",
            bio="Original bio text",
        )

    def test_update_personal_info(self):
        res = tools.update_personal_info(
            self.user,
            full_name="Alexander Mercer",
            bio="Cinematic storyteller and commercial editor.",
            title="Lead Commercial Editor",
        )
        self.assertTrue(res["success"])
        self.assertIn("diff", res)

        self.personal_info.refresh_from_db()
        self.assertEqual(self.personal_info.full_name, "Alexander Mercer")
        self.assertEqual(self.personal_info.bio, "Cinematic storyteller and commercial editor.")
        self.assertEqual(self.personal_info.title, "Lead Commercial Editor")

        # Check that a snapshot was created
        self.assertIsNotNone(res["snapshot_id"])
        self.assertTrue(PortfolioSnapshot.objects.filter(id=res["snapshot_id"]).exists())

    def test_add_project_success_and_clarification(self):
        # 1. Missing title should trigger clarification
        res_clarify = tools.add_project(self.user, title="")
        self.assertTrue(res_clarify.get("clarification_needed"))
        self.assertIn("title", res_clarify.get("missing_fields"))

        # 2. Complete project addition
        res = tools.add_project(
            self.user,
            title="Red Bull Ad 2024",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            video_type="reel",
            category_name="Commercials",
            details="Dynamic sports commercial cut in Premiere Pro.",
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["project"]["video_type"], "reel")

        proj = Project.objects.get(id=res["project"]["id"])
        self.assertEqual(proj.title, "Red Bull Ad 2024")
        self.assertEqual(proj.user, self.user)
        self.assertEqual(proj.category.name, "Commercials")

    def test_manage_skills(self):
        # Add initial skills
        tools.manage_skills(self.user, add_skills=["Premiere Pro", "After Effects", "DaVinci Resolve"])
        skills = list(Skill.objects.filter(user=self.user).values_list("name", flat=True))
        self.assertEqual(set(skills), {"Premiere Pro", "After Effects", "DaVinci Resolve"})

        # Remove one skill and add a new one
        tools.manage_skills(self.user, add_skills=["Sound Design"], remove_skills=["Premiere Pro"])
        skills_updated = list(Skill.objects.filter(user=self.user).values_list("name", flat=True))
        self.assertIn("Sound Design", skills_updated)
        self.assertNotIn("Premiere Pro", skills_updated)

    def test_add_and_delete_experience(self):
        res = tools.add_experience(
            self.user,
            title="Senior Video Editor",
            company="Vox Media",
            start_date="2022-01",
            still_working=True,
            details="Edited explainer documentaries with over 10M views.",
        )
        self.assertTrue(res["success"])
        exp_id = res["experience"]["id"]

        exp = Experience.objects.get(id=exp_id)
        self.assertEqual(exp.company, "Vox Media")
        self.assertTrue(exp.still_working)

        # Delete experience
        del_res = tools.delete_experience(self.user, experience_id=exp_id)
        self.assertTrue(del_res["success"])
        self.assertFalse(Experience.objects.filter(id=exp_id).exists())

    def test_change_theme(self):
        res = tools.change_theme(self.user, "Minimal")
        self.assertTrue(res["success"])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme, self.theme_min)

    def test_multi_tenant_isolation(self):
        # Create project for other_user
        p_other = Project.objects.create(
            user=self.other_user,
            title="Other User Project",
            video_type="long",
        )
        # Attempt to delete from self.user
        res = tools.delete_project(self.user, project_id=p_other.id)
        # Should ask for clarification because project was not found in self.user's scope
        self.assertTrue(res.get("clarification_needed"))
        self.assertTrue(Project.objects.filter(id=p_other.id).exists())

    def test_snapshot_and_undo(self):
        # 1. Modify bio and skills
        tools.manage_skills(self.user, add_skills=["Color Grading"])
        snap = tools.create_snapshot(self.user, description="Before big change")

        # 2. Make destructive changes
        tools.update_personal_info(self.user, bio="Accidental bad bio")
        tools.manage_skills(self.user, replace_all=True, add_skills=["Python"])

        self.personal_info.refresh_from_db()
        self.assertEqual(self.personal_info.bio, "Accidental bad bio")
        self.assertEqual(list(Skill.objects.filter(user=self.user).values_list("name", flat=True)), ["Python"])

        # 3. Restore snapshot
        restore_res = tools.restore_snapshot(self.user, snap.id)
        self.assertTrue(restore_res["success"])

        self.personal_info.refresh_from_db()
        self.assertEqual(self.personal_info.bio, "Original bio text")
        skills_restored = list(Skill.objects.filter(user=self.user).values_list("name", flat=True))
        self.assertIn("Color Grading", skills_restored)


class AgentViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            username="test_client_user",
            email="test@skillifly.dev",
            password="testpass123",
        )
        self.client.login(username="test_client_user", password="testpass123")

    def test_history_and_clear_views(self):
        # Test history view
        resp = self.client.get(reverse("agent_history"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("messages", data)
        self.assertIn("portfolio_state", data)

        # Test clear view
        resp_clear = self.client.post(reverse("agent_clear"))
        self.assertEqual(resp_clear.status_code, 200)
        self.assertTrue(resp_clear.json()["success"])

    def test_undo_view(self):
        snap = tools.create_snapshot(self.user, description="Initial State")
        resp = self.client.post(reverse("agent_undo", kwargs={"snapshot_id": snap.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

    @patch("agent.services.Groq", create=True)
    def test_chat_view_with_mocked_groq(self, mock_groq_cls):
        mock_instance = MagicMock()
        mock_groq_cls.return_value = mock_instance

        # Mock function call from Groq (OpenAI-compatible format)
        mock_func = MagicMock()
        mock_func.name = "update_personal_info"
        mock_func.arguments = '{"bio": "Award-winning commercial video editor."}'

        mock_tool_call = MagicMock()
        mock_tool_call.function = mock_func

        mock_message = MagicMock()
        mock_message.tool_calls = [mock_tool_call]
        mock_message.content = "I have updated your bio to sound more compelling!"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_instance.chat.completions.create.return_value = mock_response

        with patch.dict("os.environ", {"GROQ_API_KEY": "gsk_MockKeyForTesting12345678901234567890"}):
            resp = self.client.post(
                reverse("agent_chat"),
                data='{"message": "Polish my personal info section"}',
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200)
            json_res = resp.json()
            self.assertTrue(json_res["success"])
            self.assertIn("I have updated your bio", json_res["data"]["message"])
            self.assertEqual(len(json_res["data"]["actions"]), 1)

            # Check database updated
            p_info = PersonalInfo.objects.filter(user=self.user).first()
            self.assertEqual(p_info.bio, "Award-winning commercial video editor.")

    def test_chat_view_dev_fallback(self):
        # When key is placeholder, dev simulator should handle it gracefully
        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key"}, clear=False):
            resp = self.client.post(
                reverse("agent_chat"),
                data='{"message": "Add the skill DaVinci Resolve and color grading"}',
                content_type="application/json",
            )
            self.assertEqual(resp.status_code, 200)
            json_res = resp.json()
            self.assertTrue(json_res["success"])
            self.assertIn("skills", json_res["data"]["message"].lower())
            self.assertEqual(len(json_res["data"]["actions"]), 1)

    def _post_chat(self, message):
        resp = self.client.post(
            reverse("agent_chat"),
            data=json.dumps({"message": message}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()["data"]

    def test_guided_add_project_flow(self):
        cat = Category.objects.create(name="Video Editor")
        Theme.objects.create(name="Minimal", category=cat)

        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key"}, clear=False):
            # 1. Request to add a project -> asks for the LINK first
            r1 = self._post_chat("Add a new video project")
            self.assertIn("link", r1["message"].lower())
            self.assertEqual(r1["actions"], [])

            # 2. Provide the link -> asks for the TITLE
            r2 = self._post_chat("https://youtu.be/dQw4w9WgXcQ")
            self.assertIn("title", r2["message"].lower())

            # 3. Provide the title -> asks LONG or SHORT
            r3 = self._post_chat("Red Bull Ad 2024")
            self.assertIn("long", r3["message"].lower())
            self.assertIn("reel", r3["message"].lower())

            # 4. Choose SHORT -> project created as a reel and workflow cleared
            r4 = self._post_chat("Short reel")
            self.assertEqual(len(r4["actions"]), 1)

        proj = Project.objects.get(user=self.user, title="Red Bull Ad 2024")
        self.assertEqual(proj.video_type, "reel")
        self.assertEqual(proj.url, "https://youtu.be/dQw4w9WgXcQ")
        conv = AgentConversation.objects.get(user=self.user, is_active=True)
        self.assertIsNone(conv.workflow_state)

    def test_guided_change_theme_flow(self):
        cat = Category.objects.create(name="Video Editor")
        Theme.objects.create(name="Minimal", category=cat)
        Theme.objects.create(name="Cyan", category=cat)

        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key"}, clear=False):
            # 1. Request a theme change -> asks light or dark
            r1 = self._post_chat("Change the theme")
            self.assertIn("light", r1["message"].lower())
            self.assertIn("dark", r1["message"].lower())
            self.assertEqual(r1["actions"], [])

            # 2. Choose dark -> a random dark theme is applied
            r2 = self._post_chat("I like dark colors")
            self.assertEqual(len(r2["actions"]), 1)

        profile = Profile.objects.get(user=self.user)
        self.assertIsNotNone(profile.theme)
        self.assertEqual(profile.theme.name, "Cyan")
        conv = AgentConversation.objects.get(user=self.user, is_active=True)
        self.assertIsNone(conv.workflow_state)

    def test_guided_bio_flow(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key"}, clear=False):
            # 1. Ask for a new bio -> asks years of experience
            r1 = self._post_chat("Write me a new bio")
            self.assertIn("years", r1["message"].lower())
            self.assertEqual(r1["actions"], [])

            # 2. Give years -> asks apps used for editing
            r2 = self._post_chat("5 years")
            self.assertIn("apps", r2["message"].lower())

            # 3. Give apps -> asks about specialization
            r3 = self._post_chat("Premiere Pro and DaVinci Resolve")
            self.assertIn("special", r3["message"].lower())

            # 4. Give specialty -> asks for anything else
            r4 = self._post_chat("Commercials")
            self.assertIn("anything else", r4["message"].lower())

            # 5. Wrap up -> bio generated and saved
            r5 = self._post_chat("That's all")
            self.assertEqual(len(r5["actions"]), 1)

        info = PersonalInfo.objects.get(user=self.user)
        self.assertIn("Commercials", info.bio)
        self.assertIn("5+ years", info.bio)
        conv = AgentConversation.objects.get(user=self.user, is_active=True)
        self.assertIsNone(conv.workflow_state)

    def test_guided_workflow_cancel(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key"}, clear=False):
            r1 = self._post_chat("Add a new project")
            self.assertEqual(r1["actions"], [])
            r2 = self._post_chat("Cancel")
            self.assertIn("cancel", r2["message"].lower())
        conv = AgentConversation.objects.get(user=self.user, is_active=True)
        self.assertIsNone(conv.workflow_state)
        self.assertFalse(Project.objects.filter(user=self.user).exists())

    def test_guided_add_review_flow(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key"}, clear=False):
            # 1. Trigger add review -> asks for client name
            r1 = self._post_chat("Add a review")
            self.assertIn("name", r1["message"].lower())
            self.assertEqual(r1["actions"], [])

            # 2. Provide client name -> asks for client position/title
            r2 = self._post_chat("Ahmed Saleh")
            self.assertIn("title", r2["message"].lower())

            # 3. Provide position -> asks for review content
            r3 = self._post_chat("Marketing Director")
            self.assertIn("say", r3["message"].lower())

            # 4. Provide content -> asks for star rating
            r4 = self._post_chat("Outstanding editing quality and very fast turnaround!")
            self.assertIn("rating", r4["message"].lower())

            # 5. Provide rating -> creates review in DB
            r5 = self._post_chat("5")
            self.assertEqual(len(r5["actions"]), 1)

        rev = ClientReview.objects.get(user=self.user, user_name="Ahmed Saleh")
        self.assertEqual(rev.user_title, "Marketing Director")
        self.assertEqual(rev.content, "Outstanding editing quality and very fast turnaround!")
        self.assertEqual(rev.rating, 5)
        conv = AgentConversation.objects.get(user=self.user, is_active=True)
        self.assertIsNone(conv.workflow_state)

    def test_guided_fix_project_url_flow(self):
        # Create a project with placeholder URL
        p = Project.objects.create(
            user=self.user,
            title="Nike Commercial 2024",
            url="https://skillifly.cloud/placeholder",
            video_type="long",
        )

        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key"}, clear=False):
            # 1. Trigger fix project url -> shows existing projects and asks which one
            r1 = self._post_chat("Fix project URLs")
            self.assertIn("Nike Commercial 2024", r1["quick_replies"])
            self.assertEqual(r1["actions"], [])

            # 2. Pick project name -> asks for link specifically for that project without generic platform examples
            r2 = self._post_chat("Nike Commercial 2024")
            self.assertIn("Nike Commercial 2024", r2["message"])
            self.assertNotIn("vimeo", r2["message"].lower())

            # 3. Paste link -> updates project URL
            r3 = self._post_chat("https://youtu.be/real_video_id")
            self.assertEqual(len(r3["actions"]), 1)

        p.refresh_from_db()
        self.assertEqual(p.url, "https://youtu.be/real_video_id")
        conv = AgentConversation.objects.get(user=self.user, is_active=True)
        self.assertIsNone(conv.workflow_state)

    def test_guided_reorder_sections_flow(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key"}, clear=False):
            # 1. Ask to change section order -> asks for order and provides quick presets
            r1 = self._post_chat("Change portfolio sections order")
            self.assertIn("Recruiter first", r1["quick_replies"])
            self.assertIn("Client first", r1["quick_replies"])
            self.assertIn("Social proof first", r1["quick_replies"])
            self.assertIn("Theme default", r1["quick_replies"])
            self.assertEqual(r1["actions"], [])

            # 2. Choose "Client first" preset -> applies layout and clears workflow
            r2 = self._post_chat("Client first")
            self.assertEqual(len(r2["actions"]), 1)

        profile = Profile.objects.get(user=self.user)
        self.assertIn("projects", profile.section_order)
        self.assertIn("reviews", profile.section_order)
        # In client first, reviews appears immediately after projects or before skills
        self.assertLess(profile.section_order.index("reviews"), profile.section_order.index("skills"))
        conv = AgentConversation.objects.get(user=self.user, is_active=True)
        self.assertIsNone(conv.workflow_state)
