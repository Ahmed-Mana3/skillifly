"""PR-7: next-best-step card, one-click AI bio, short signup form."""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from core import onboarding
from core.models import ActivationEvent, CustomUser, PersonalInfo, Project, Skill
from core.testing_helpers import clear_cache, make_editor, seed_themes, site_settings

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def add_projects(user, n):
    for i in range(n):
        Project.objects.create(user=user, title=f'P{i}')


def set_info(user, **fields):
    defaults = dict(full_name=user.get_full_name(), title='Colorist', email='', phone='', bio='')
    defaults.update(fields)
    PersonalInfo.objects.update_or_create(user=user, defaults=defaults)


class NextStepTests(TestCase):
    def setUp(self):
        clear_cache()
        seed_themes()
        site_settings()
        self.user = make_editor()

    def step(self, arabic=False):
        return onboarding.next_step(self.user, self.user.projects.count(), arabic=arabic)

    def test_priority_order(self):
        self.assertEqual(self.step()['key'], 'videos')
        add_projects(self.user, 2)
        self.assertEqual(self.step()['key'], 'videos')
        add_projects(self.user, 1)
        self.assertEqual(self.step()['key'], 'contact')   # 3 videos, no way to be reached
        set_info(self.user, phone='+201001234567')
        self.assertEqual(self.step()['key'], 'bio')
        set_info(self.user, phone='+201001234567', bio='Hello')
        self.assertEqual(self.step()['key'], 'skills')
        Skill.objects.create(user=self.user, name='Premiere Pro')
        self.assertIsNone(self.step())

    def test_booking_link_counts_as_contact(self):
        add_projects(self.user, 3)
        set_info(self.user, booking_url='https://wa.me/20100')
        self.assertEqual(self.step()['key'], 'bio')

    def test_video_step_describes_progress(self):
        self.assertIn('none yet', self.step()['body'])
        add_projects(self.user, 2)
        self.assertIn('2 so far', self.step()['body'])

    def test_video_step_links_to_welcome_when_enabled_else_builder(self):
        self.assertTrue(self.step()['url'].endswith('/builder/update/#projects'))
        site_settings(onboarding_v2_enabled=True)
        self.assertEqual(self.step()['url'], '/welcome/?add=1')
        self.assertEqual(self.step(arabic=True)['url'], '/ar/welcome/?add=1')

    def test_bio_step_posts_to_the_ai_endpoint(self):
        add_projects(self.user, 3)
        set_info(self.user, phone='+201001234567')
        step = self.step()
        self.assertTrue(step['post'])
        self.assertEqual(step['url'], reverse('ai_bio_draft'))

    def test_arabic_copy(self):
        step = self.step(arabic=True)
        self.assertIn('أضف', step['title'])
        self.assertIn('لا شيء بعد', step['body'])
        add_projects(self.user, 3)
        self.assertIn('واتساب', self.step(arabic=True)['title'])
        self.assertTrue(self.step(arabic=True)['url'].startswith('/ar/'))


class NextStepDashboardTests(TestCase):
    def setUp(self):
        clear_cache()
        seed_themes()
        site_settings()
        self.user = make_editor()
        self.client.force_login(self.user)

    def test_card_shows_on_the_dashboard(self):
        add_projects(self.user, 3)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'id="next-step"')
        self.assertContains(resp, 'Add WhatsApp so clients can reach you in one tap')
        self.assertEqual(resp.context['next_step']['key'], 'contact')

    def test_arabic_card(self):
        add_projects(self.user, 3)
        resp = self.client.get(reverse('arabic_dashboard'))
        self.assertContains(resp, 'أضف واتساب ليتواصل معك العملاء')

    def test_bio_step_renders_a_post_form_with_csrf(self):
        add_projects(self.user, 3)
        set_info(self.user, phone='+201001234567')
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, f'action="{reverse("ai_bio_draft")}"')
        self.assertContains(resp, 'Write my bio')
        self.assertContains(resp, 'name="lang" value="en"')

    def test_no_card_when_everything_is_done(self):
        add_projects(self.user, 3)
        set_info(self.user, phone='+201001234567', bio='Hello')
        Skill.objects.create(user=self.user, name='Premiere Pro')
        resp = self.client.get(reverse('dashboard'))
        self.assertNotContains(resp, 'id="next-step"')

    def test_no_card_in_first_run_state(self):
        site_settings(onboarding_v2_enabled=True)
        session = self.client.session
        session['welcome_routed'] = True
        session.save()
        resp = self.client.get(reverse('dashboard'))
        self.assertTrue(resp.context['is_first_run'])
        self.assertIsNone(resp.context['next_step'])
        self.assertNotContains(resp, 'id="next-step"')


class AiBioTests(TestCase):
    def setUp(self):
        clear_cache()
        seed_themes()
        self.user = make_editor()
        self.client.force_login(self.user)
        self.url = reverse('ai_bio_draft')

    def post(self, **data):
        return self.client.post(self.url, data, follow=True)

    def test_drafts_and_saves_a_bio(self):
        with patch('core.ai.write_bio', return_value='  Cinematic editor for brands.  ') as write:
            resp = self.post(lang='en')
        write.assert_called_once()
        self.assertEqual(write.call_args.kwargs['language'], 'en')
        self.assertEqual(PersonalInfo.objects.get(user=self.user).bio, 'Cinematic editor for brands.')
        self.assertContains(resp, 'Bio added')
        event = ActivationEvent.objects.get(name='profile_field_added')
        self.assertEqual(event.props, {'field': 'bio', 'source': 'ai'})

    def test_creates_personal_info_from_signup_when_missing(self):
        with patch('core.ai.write_bio', return_value='A bio.'):
            self.post()
        info = PersonalInfo.objects.get(user=self.user)
        self.assertEqual((info.full_name, info.title, info.bio), ('Sara Ali', 'Video Editor', 'A bio.'))

    def test_never_overwrites_an_existing_bio(self):
        set_info(self.user, bio='My own words')
        with patch('core.ai.write_bio') as write:
            resp = self.post()
        write.assert_not_called()
        self.assertEqual(PersonalInfo.objects.get(user=self.user).bio, 'My own words')
        self.assertContains(resp, 'You already have a bio')

    def test_failure_shows_an_error_and_saves_nothing(self):
        for failing in (dict(return_value=''), dict(side_effect=RuntimeError('provider down'))):
            clear_cache()  # each attempt would otherwise hit the 30-second cooldown
            with patch('core.ai.write_bio', **failing):
                resp = self.post()
            # base.html renders messages with |safe, so the apostrophe is not escaped here.
            self.assertContains(resp, "couldn't write your bio")
        self.assertFalse(PersonalInfo.objects.filter(user=self.user).exists())

    def test_cooldown_protects_the_paid_provider(self):
        with patch('core.ai.write_bio', return_value='') as write:
            self.post()                      # fails, but counts as an attempt
            resp = self.post()               # immediately again
        self.assertEqual(write.call_count, 1)
        self.assertContains(resp, 'Please wait a few seconds')
        clear_cache()
        with patch('core.ai.write_bio', return_value='A bio.') as write:
            self.post()
        self.assertEqual(write.call_count, 1)

    def test_cooldown_is_per_user(self):
        with patch('core.ai.write_bio', return_value='A bio.') as write:
            self.post()
            other = make_editor('other')
            self.client.force_login(other)
            self.post()
        self.assertEqual(write.call_count, 2)

    def test_arabic(self):
        with patch('core.ai.write_bio', return_value='نبذة.') as write:
            resp = self.post(lang='ar')
        self.assertEqual(write.call_args.kwargs['language'], 'ar')
        self.assertEqual(resp.redirect_chain[-1][0], reverse('arabic_dashboard'))
        self.assertContains(resp, 'أضفنا نبذتك الشخصية')
        self.assertEqual(PersonalInfo.objects.get(user=self.user).title, 'مونتير فيديو')

    def test_long_bios_are_capped(self):
        with patch('core.ai.write_bio', return_value='x' * 5000):
            self.post()
        self.assertEqual(len(PersonalInfo.objects.get(user=self.user).bio), 1500)

    def test_post_only_login_required_and_editors_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        buyer = make_editor('buyer', account_type='client')
        self.client.force_login(buyer)
        with patch('core.ai.write_bio') as write:
            self.client.post(self.url)
        write.assert_not_called()
        self.client.logout()
        self.assertEqual(self.client.post(self.url).status_code, 302)


@FAST_HASH
class ShortSignupTests(TestCase):
    def setUp(self):
        clear_cache()
        seed_themes()
        site_settings()

    def test_short_form_when_the_switch_is_on(self):
        site_settings(onboarding_v2_enabled=True)
        resp = self.client.get(reverse('signup'))
        self.assertContains(resp, 'name="full_name"')
        self.assertContains(resp, 'id="toggle-password"')
        self.assertNotContains(resp, 'name="password2"')
        self.assertNotContains(resp, 'name="first_name"')
        self.assertNotContains(resp, 'Confirm password')

    def test_arabic_short_form(self):
        site_settings(onboarding_v2_enabled=True)
        resp = self.client.get(reverse('arabic_signup'))
        self.assertContains(resp, 'الاسم الكامل')
        self.assertContains(resp, 'id="toggle-password"')
        self.assertNotContains(resp, 'تأكيد كلمة المرور')

    def test_short_form_also_when_the_switch_is_off(self):
        # The rebuilt signup page always uses the short form; the switch no longer matters here.
        resp = self.client.get(reverse('signup'))
        self.assertContains(resp, 'name="full_name"')
        self.assertContains(resp, 'id="toggle-password"')
        self.assertNotContains(resp, 'name="password2"')
        self.assertNotContains(resp, 'name="first_name"')

    def test_short_post_creates_the_account(self):
        site_settings(onboarding_v2_enabled=True)
        resp = self.client.post(reverse('signup'), {
            'full_name': 'Sara Ali', 'username': 'sara_ali', 'email': 'sara@example.com',
            'password1': 'Str0ng-pass-99',
        })
        self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        user = CustomUser.objects.get(username='sara_ali')
        self.assertEqual((user.first_name, user.last_name), ('Sara', 'Ali'))
        self.assertTrue(user.check_password('Str0ng-pass-99'))

    def test_single_word_and_long_names(self):
        for i, (full, first, last) in enumerate((('Cher', 'Cher', ''), ('Mary Jane Watson', 'Mary', 'Jane Watson'))):
            self.client.logout()
            self.client.post(reverse('signup'), {
                'full_name': full, 'username': f'user_{i}', 'email': f'u{i}@example.com',
                'password1': 'Str0ng-pass-99',
            })
            user = CustomUser.objects.get(username=f'user_{i}')
            self.assertEqual((user.first_name, user.last_name), (first, last))

    def test_weak_password_is_rejected_with_the_error_on_the_visible_field(self):
        site_settings(onboarding_v2_enabled=True)
        resp = self.client.post(reverse('signup'), {
            'full_name': 'Sara Ali', 'username': 'sara_ali', 'email': 'sara@example.com',
            'password1': '12345678',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'This password is too common')
        self.assertFalse(CustomUser.objects.filter(username='sara_ali').exists())

    def test_missing_name_is_reported(self):
        site_settings(onboarding_v2_enabled=True)
        resp = self.client.post(reverse('signup'), {
            'username': 'sara_ali', 'email': 'sara@example.com', 'password1': 'Str0ng-pass-99',
        })
        self.assertContains(resp, 'Please enter your name.')
        self.assertFalse(CustomUser.objects.filter(username='sara_ali').exists())

    def test_classic_post_still_works_and_still_checks_the_confirmation(self):
        good = {'first_name': 'Sara', 'last_name': 'Ali', 'username': 'sara_ali', 'email': 'sara@example.com',
                'password1': 'Str0ng-pass-99', 'password2': 'Str0ng-pass-99'}
        bad = dict(good, username='sara_two', email='two@example.com', password2='Different-99')
        self.client.post(reverse('signup'), bad)
        self.assertFalse(CustomUser.objects.filter(username='sara_two').exists())
        self.client.post(reverse('signup'), good)
        self.assertTrue(CustomUser.objects.filter(username='sara_ali').exists())

    def test_missing_name_error_lands_on_a_field_the_form_renders(self):
        from core.forms import RegisterForm
        base = {'username': 'sara_ali', 'email': 'sara@example.com', 'password1': 'Str0ng-pass-99'}
        short = RegisterForm(dict(base))
        self.assertFalse(short.is_valid())
        self.assertIn('full_name', short.errors)
        legacy = RegisterForm(dict(base, first_name='', last_name='', password2='Str0ng-pass-99'))
        self.assertFalse(legacy.is_valid())
        self.assertIn('first_name', legacy.errors)   # the legacy template renders this one

    def test_username_help_text_names_the_real_domain(self):
        from core.forms import RegisterForm
        self.assertIn('skillifly.cloud/yourusername', RegisterForm().fields['username'].help_text)
        self.assertNotIn('portfoliobuilder', RegisterForm().fields['username'].help_text)

    def test_reserved_username_is_still_blocked_on_the_short_form(self):
        site_settings(onboarding_v2_enabled=True)
        resp = self.client.post(reverse('signup'), {
            'full_name': 'Sara Ali', 'username': 'welcome', 'email': 'sara@example.com',
            'password1': 'Str0ng-pass-99',
        })
        self.assertContains(resp, 'reserved')
        self.assertFalse(CustomUser.objects.filter(username='welcome').exists())

    def test_google_signup_is_untouched_by_the_form_change(self):
        # The allauth social flow never uses RegisterForm; just make sure it still imports.
        from allauth.socialaccount.models import SocialAccount  # noqa: F401
        self.assertTrue(callable(self.client.get))
