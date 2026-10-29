"""PR-2 / PR-4 / PR-6 / PR-7: quick wins, welcome flow, reveal bar, deferred verification."""
import json
from datetime import timedelta
from smtplib import SMTPException
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.core import mail
from django.core.files.base import ContentFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import onboarding
from core.forms import RegisterForm
from core.models import (
    ActivationEvent, CustomUser, EmailOTP, PersonalInfo, Profile, Project, UserAccount,
)
from core.oembed import VideoMeta
from core.testing_helpers import (
    TempMediaMixin, builder_post, clear_cache, give_payment, make_editor, png_bytes,
    project_row, seed_themes, site_settings,
)

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])

YT = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


def events(name):
    return ActivationEvent.objects.filter(name=name)


def meta(url=YT, title='Great Edit', video_type='long', ok=True, error='', provider='youtube'):
    return VideoMeta(
        url=url, provider=provider, title=title if ok else '', video_type=video_type, ok=ok, error=error,
        thumbnail_url='https://i.ytimg.com/vi/x/hqdefault.jpg' if ok else '',
        thumbnail_candidates=['https://i.ytimg.com/vi/x/hqdefault.jpg'] if ok else [],
    )


def fake_thumb(*args, **kwargs):
    return ContentFile(png_bytes(), name='oembed_test.png')


class OnboardingTestCase(TestCase):
    def setUp(self):
        clear_cache()
        self.themes = seed_themes()
        self.settings_row = site_settings()
        self.user = make_editor()
        self.client.force_login(self.user)

    def enable(self, **flags):
        flags.setdefault('onboarding_v2_enabled', True)
        site_settings(**flags)

    def skip_welcome_redirect(self):
        session = self.client.session
        session['welcome_routed'] = True
        session.save()


# ---------------------------------------------------------------------------
# PR-2: quick wins
# ---------------------------------------------------------------------------

class BuilderPrefillTests(OnboardingTestCase):
    def test_name_and_title_are_prefilled_for_a_new_editor(self):
        resp = self.client.get(reverse('update_portfolio'))
        self.assertContains(resp, 'value="Sara Ali"')
        self.assertContains(resp, 'value="Video Editor"')

    def test_contact_email_is_not_prefilled(self):
        resp = self.client.get(reverse('update_portfolio'))
        self.assertNotContains(resp, 'value="sara@example.com"')

    def test_arabic_builder_prefills_arabic_title(self):
        resp = self.client.get(reverse('arabic_update_portfolio'))
        self.assertContains(resp, 'مونتير فيديو')

    def test_first_time_builder_route_prefills_too(self):
        resp = self.client.get(reverse('builder'))
        self.assertContains(resp, 'value="Sara Ali"')

    def test_existing_personal_info_wins(self):
        PersonalInfo.objects.create(user=self.user, full_name='Sara A.', title='Colorist', email='', phone='', bio='')
        resp = self.client.get(reverse('update_portfolio'))
        self.assertContains(resp, 'value="Colorist"')
        self.assertNotContains(resp, 'value="Video Editor"')

    def test_link_hint_mentions_instagram_and_drive(self):
        # The paste-a-link box at the top of the Work panel names them.
        self.assertContains(self.client.get(reverse('update_portfolio')), 'TikTok, Instagram or Drive link')
        self.assertContains(self.client.get(reverse('arabic_update_portfolio')), 'إنستجرام أو درايف')


class DefaultThemeTests(OnboardingTestCase):
    def test_editor_gets_creative_when_opening_the_builder(self):
        self.assertIsNone(getattr(self.user, 'profile', None) and self.user.profile.theme)
        use_before = self.themes['Creative'].use_num
        self.client.get(reverse('update_portfolio'))
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Creative'])
        self.themes['Creative'].refresh_from_db()
        self.assertEqual(self.themes['Creative'].use_num, use_before)  # not a user "choice"

    def test_dashboard_also_assigns_it(self):
        self.client.get(reverse('dashboard'))
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Creative'])

    def test_existing_theme_is_never_overwritten(self):
        Profile.objects.create(user=self.user, theme=self.themes['Pro'])
        self.client.get(reverse('update_portfolio'))
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Pro'])

    def test_clients_and_school_admins_get_nothing(self):
        for name, kind in (('cl', 'client'), ('sa', 'school_admin')):
            other = make_editor(name, account_type=kind)
            self.assertIsNone(onboarding.ensure_default_theme(other))
            self.assertFalse(Profile.objects.filter(user=other, theme__isnull=False).exists())

    def test_picture_requiring_theme_is_never_the_default(self):
        self.settings_row.default_editor_theme = self.themes['Animated']
        self.settings_row.save()
        self.assertEqual(onboarding.default_editor_theme(), self.themes['Creative'])

    def test_configured_default_is_used(self):
        self.settings_row.default_editor_theme = self.themes['Pro']
        self.settings_row.save()
        onboarding.ensure_default_theme(self.user)
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Pro'])

    def test_missing_theme_in_database_does_not_crash(self):
        from core.models import Theme
        Theme.objects.all().delete()
        self.assertIsNone(onboarding.ensure_default_theme(self.user))
        self.assertEqual(self.client.get(reverse('update_portfolio')).status_code, 200)

    def test_ensure_default_theme_refreshes_the_cached_profile(self):
        Profile.objects.create(user=self.user)
        user = CustomUser.objects.get(pk=self.user.pk)
        self.assertIsNone(user.profile.theme_id)  # caches the profile on the user object
        onboarding.ensure_default_theme(user)
        self.assertEqual(user.profile.theme, self.themes['Creative'])


class FirstProjectRedirectTests(OnboardingTestCase):
    def test_first_project_goes_to_own_portfolio(self):
        resp = self.client.post(reverse('update_portfolio'), builder_post([project_row('Cut 1')]))
        self.assertRedirects(resp, '/sara/?welcome=1', fetch_redirect_response=False)

    def test_arabic_first_project_keeps_the_language(self):
        resp = self.client.post(reverse('arabic_update_portfolio'), builder_post([project_row('Cut 1')]))
        self.assertRedirects(resp, '/sara/?welcome=1&lang=ar', fetch_redirect_response=False)

    def test_later_saves_go_to_the_dashboard(self):
        Project.objects.create(user=self.user, title='Existing')
        resp = self.client.post(reverse('update_portfolio'), builder_post([project_row('Cut 2')]))
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)

    def test_save_without_a_project_goes_to_the_dashboard(self):
        resp = self.client.post(reverse('update_portfolio'), builder_post([]))
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)

    def test_first_time_builder_route_redirects_to_portfolio(self):
        resp = self.client.post(reverse('builder'), builder_post([project_row('Cut 1')]))
        self.assertRedirects(resp, '/sara/?welcome=1', fetch_redirect_response=False)


class ThemePickerRedirectTests(OnboardingTestCase):
    def pick(self, name='Pro', url='themes'):
        return self.client.post(reverse(url), {'theme': self.themes[name].pk})

    def test_no_project_switch_off_goes_to_builder(self):
        self.assertRedirects(self.pick(), reverse('builder'), fetch_redirect_response=False)

    def test_no_project_switch_on_goes_to_welcome(self):
        self.enable()
        self.assertRedirects(self.pick(), reverse('welcome'), fetch_redirect_response=False)
        self.assertRedirects(self.pick(url='arabic_themes'), reverse('arabic_welcome'), fetch_redirect_response=False)

    def test_arabic_switch_off_goes_to_arabic_builder(self):
        self.assertRedirects(self.pick(url='arabic_themes'), reverse('arabic_update_portfolio'),
                             fetch_redirect_response=False)

    def test_with_projects_first_theme_shows_the_preview(self):
        Project.objects.create(user=self.user, title='P')
        Profile.objects.create(user=self.user)  # no theme yet
        self.assertRedirects(self.pick(), reverse('preview', kwargs={'username': 'sara'}), fetch_redirect_response=False)

    def test_with_projects_changing_theme_goes_to_dashboard(self):
        Project.objects.create(user=self.user, title='P')
        Profile.objects.create(user=self.user, theme=self.themes['Creative'])
        self.assertRedirects(self.pick(), reverse('dashboard'), fetch_redirect_response=False)

    def test_theme_switch_is_tracked(self):
        Profile.objects.create(user=self.user, theme=self.themes['Creative'])
        Project.objects.create(user=self.user, title='P')
        self.pick('Minimal')
        props = events('theme_switched').get().props
        self.assertEqual((props['from'], props['to']), ('Creative', 'Minimal'))


class OtpHardeningTests(OnboardingTestCase):
    def setUp(self):
        super().setUp()
        self.client.logout()
        self.pending = make_editor('pending', is_active=False)
        EmailOTP.objects.create(user=self.pending, otp='123456')
        session = self.client.session
        session['verification_user_id'] = self.pending.pk
        session.save()

    def post_code(self, code):
        return self.client.post(reverse('verify_otp'), {'otp': code})

    def test_correct_code_activates_and_logs_in(self):
        resp = self.post_code('123456')
        self.assertEqual(resp.status_code, 302)
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_active)
        self.assertEqual(self.client.session['_auth_user_id'], str(self.pending.pk))
        self.assertTrue(EmailAddress.objects.get(user=self.pending).verified)

    def test_wrong_codes_are_counted_and_the_sixth_attempt_is_locked_out(self):
        for _ in range(EmailOTP.MAX_ATTEMPTS):
            self.assertContains(self.post_code('000000'), 'Check the latest email and try again')
        self.assertEqual(EmailOTP.objects.get(user=self.pending).attempts, EmailOTP.MAX_ATTEMPTS)
        resp = self.post_code('123456')  # right code, but too late
        self.assertContains(resp, 'Too many wrong attempts')
        self.pending.refresh_from_db()
        self.assertFalse(self.pending.is_active)

    def test_resend_resets_attempts_and_emails_a_new_code(self):
        for _ in range(EmailOTP.MAX_ATTEMPTS):
            self.post_code('000000')
        resp = self.client.post(reverse('resend_otp'))
        self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        otp = EmailOTP.objects.get(user=self.pending)
        self.assertEqual(otp.attempts, 0)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(otp.otp, mail.outbox[0].body)
        self.assertIn('30 minutes', mail.outbox[0].body)
        self.assertEqual(self.post_code(otp.otp).status_code, 302)

    def test_code_is_valid_for_thirty_minutes(self):
        EmailOTP.objects.filter(user=self.pending).update(created_at=timezone.now() - timedelta(minutes=29))
        self.assertEqual(self.post_code('123456').status_code, 302)

    def test_code_expires_after_thirty_minutes(self):
        EmailOTP.objects.filter(user=self.pending).update(created_at=timezone.now() - timedelta(minutes=31))
        self.assertContains(self.post_code('123456'), 'That code has expired')
        self.pending.refresh_from_db()
        self.assertFalse(self.pending.is_active)

    def test_failed_email_on_signup_does_not_500(self):
        self.client.logout()
        data = {'first_name': 'Nour', 'last_name': 'H', 'username': 'nour_h', 'email': 'nour@example.com',
                'password1': 'Str0ng-pass-99', 'password2': 'Str0ng-pass-99'}
        with patch('core.views.send_mail', side_effect=SMTPException('smtp down')):
            resp = self.client.post(reverse('signup'), data)
        self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        user = CustomUser.objects.get(username='nour_h')
        self.assertFalse(user.is_active)
        self.assertContains(self.client.get(reverse('verify_otp')), 'Tap Resend')

    def test_failed_resend_shows_an_error_not_a_500(self):
        with patch('core.views.send_mail', side_effect=SMTPException('smtp down')):
            resp = self.client.post(reverse('resend_otp'), follow=True)
        self.assertContains(resp, "couldn&#x27;t send the code")


class FirstRunDashboardTests(OnboardingTestCase):
    def test_switch_off_dashboard_is_unchanged(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Welcome back')
        self.assertContains(resp, 'Choose a plan')
        self.assertFalse(resp.context['is_first_run'])

    def test_first_run_state_hides_the_paywall_widgets(self):
        self.enable()
        self.skip_welcome_redirect()
        resp = self.client.get(reverse('dashboard'))
        self.assertTrue(resp.context['is_first_run'])
        self.assertContains(resp, 'Add your first video')
        self.assertNotContains(resp, 'Choose a plan')
        self.assertNotContains(resp, 'id="visibility"')
        self.assertNotContains(resp, 'id="payment-banner"')
        self.assertNotContains(resp, 'Welcome back')
        self.assertContains(resp, resp.context['welcome_url'])

    def test_arabic_first_run_state(self):
        self.enable()
        self.skip_welcome_redirect()
        resp = self.client.get(reverse('arabic_dashboard'))
        self.assertContains(resp, 'أضف أول فيديو لك')
        self.assertNotContains(resp, 'id="visibility"')
        self.assertContains(resp, '/ar/welcome/')

    def test_with_a_project_the_normal_dashboard_returns(self):
        self.enable()
        Project.objects.create(user=self.user, title='P')
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['is_first_run'])
        self.assertContains(resp, 'Welcome back')

    def test_expired_payer_still_sees_billing(self):
        self.enable()
        self.skip_welcome_redirect()
        give_payment(self.user, days_ago=60, plan_days=30)
        resp = self.client.get(reverse('dashboard'))
        self.assertFalse(resp.context['is_first_run'])
        self.assertContains(resp, 'Renew plan')

    def test_checklist_puts_projects_first(self):
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual([i['key'] for i in resp.context['checklist_items']],
                         ['projects', 'personal', 'theme', 'skills', 'publish'])

    def test_clients_never_see_first_run(self):
        self.enable()
        client_user = make_editor('buyer', account_type='client')
        self.client.force_login(client_user)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('client_dashboard'),
                             fetch_redirect_response=False)

    def test_dashboard_view_is_tracked_for_new_accounts_only(self):
        self.client.get(reverse('dashboard'))
        self.assertEqual(events('dashboard_viewed').count(), 1)
        old = make_editor('veteran', days_old=40)
        self.client.force_login(old)
        self.client.get(reverse('dashboard'))
        self.assertEqual(events('dashboard_viewed').filter(user=old).count(), 0)


# ---------------------------------------------------------------------------
# PR-4: welcome flow
# ---------------------------------------------------------------------------

class WelcomeRoutingTests(OnboardingTestCase):
    def test_switch_off_welcome_falls_back_to_the_builder(self):
        resp = self.client.get(reverse('welcome'))
        self.assertRedirects(resp, reverse('update_portfolio'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)  # no redirect either

    def test_switch_on_new_editor_is_sent_to_welcome_once_per_session(self):
        self.enable()
        resp = self.client.get(reverse('dashboard'))
        self.assertRedirects(resp, '/welcome/?from=dashboard', fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)  # never trapped

    def test_arabic_dashboard_routes_to_arabic_welcome(self):
        self.enable()
        resp = self.client.get(reverse('arabic_dashboard'))
        self.assertRedirects(resp, '/ar/welcome/?from=dashboard', fetch_redirect_response=False)

    def test_editor_with_projects_is_not_redirected(self):
        self.enable()
        Project.objects.create(user=self.user, title='P')
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertRedirects(self.client.get(reverse('welcome')), reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('welcome') + '?add=1').status_code, 200)

    def test_clients_and_school_admins_are_never_sent_to_welcome(self):
        self.enable()
        for name, kind, target in (('cl', 'client', 'client_dashboard'), ('sa', 'school_admin', 'school_admin_dashboard')):
            other = make_editor(name, account_type=kind)
            self.client.force_login(other)
            self.assertRedirects(self.client.get(reverse('dashboard')), reverse(target), fetch_redirect_response=False)
            # /welcome/ bounces to the dashboard, which forwards to their own.
            self.assertRedirects(self.client.get(reverse('welcome')), reverse('dashboard'), fetch_redirect_response=False)

    def test_legacy_user_without_account_row_is_an_editor(self):
        self.enable()
        legacy = make_editor('legacy', account_type=None)
        self.client.force_login(legacy)
        self.assertRedirects(self.client.get(reverse('dashboard')), '/welcome/?from=dashboard',
                             fetch_redirect_response=False)

    def test_anonymous_is_sent_to_sign_in(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('welcome')).status_code, 302)
        self.assertIn('signin', self.client.get(reverse('welcome'))['Location'])
        self.assertIn('signin', self.client.get(reverse('arabic_welcome'))['Location'])


class WelcomePageTests(OnboardingTestCase):
    def setUp(self):
        super().setUp()
        self.enable()

    def test_english_page(self):
        resp = self.client.get(reverse('welcome'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Start with your best edit')
        self.assertContains(resp, 'Step 1 of 2')
        self.assertContains(resp, 'Skip for now')
        self.assertContains(resp, 'data-src="/preview/creative/?embed=1"')
        self.assertContains(resp, 'dir="ltr"')
        self.assertEqual(events('welcome_viewed').get().props['entry'], 'direct')

    def test_arabic_page_is_rtl(self):
        resp = self.client.get(reverse('arabic_welcome'))
        self.assertContains(resp, 'ابدأ بأقوى فيديو في أعمالك')
        self.assertContains(resp, 'dir="rtl"')
        self.assertContains(resp, 'الخطوة 1 من 2')

    def test_adding_more_hides_the_step_label_and_skip(self):
        Project.objects.create(user=self.user, title='P')
        resp = self.client.get(reverse('welcome') + '?add=1')
        self.assertContains(resp, 'Add more videos')
        self.assertNotContains(resp, 'Step 1 of 2')
        self.assertNotContains(resp, 'Skip for now')

    def test_entry_and_nudge_are_tracked(self):
        self.client.get(reverse('welcome') + '?from=dashboard&utm_source=nudge&utm_campaign=no_project_1h')
        self.assertEqual(events('welcome_viewed').get().props['entry'], 'dashboard')
        self.assertEqual(events('nudge_clicked').get().props['key'], 'no_project_1h')

    def test_reveal_action_is_tracked(self):
        self.client.get(reverse('welcome') + '?add=1&ra=add')
        self.assertEqual(events('reveal_action').get().props['action'], 'add')

    def test_ra_values_are_whitelisted(self):
        self.client.get(reverse('welcome') + '?ra=<script>')
        self.assertEqual(events('reveal_action').count(), 0)

    def test_skip_marks_the_session_and_is_tracked(self):
        resp = self.client.post(reverse('welcome_skip'), {'lang': 'en'})
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(events('welcome_skipped').count(), 1)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertRedirects(self.client.post(reverse('welcome_skip'), {'lang': 'ar'}),
                             reverse('arabic_dashboard'), fetch_redirect_response=False)

    def test_skip_requires_post(self):
        self.assertEqual(self.client.get(reverse('welcome_skip')).status_code, 405)


class WelcomeSubmitTests(TempMediaMixin, OnboardingTestCase):
    def setUp(self):
        super().setUp()
        self.enable()
        self.fetch = patch('core.oembed.fetch', return_value=meta())
        self.thumb = patch('core.oembed.download_thumbnail', side_effect=fake_thumb)
        self.fetch_mock = self.fetch.start()
        self.thumb_mock = self.thumb.start()
        self.addCleanup(self.fetch.stop)
        self.addCleanup(self.thumb.stop)

    def post(self, urls, titles=None, types=None, url='welcome', **extra):
        data = {'url': urls}
        if titles is not None:
            data['title'] = titles
        if types is not None:
            data['video_type'] = types
        data.update(extra)
        return self.client.post(reverse(url), data)

    def test_valid_link_builds_the_whole_portfolio(self):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.post([YT], [''], ['long'])
        self.assertRedirects(resp, '/sara/?welcome=1', fetch_redirect_response=False)

        project = Project.objects.get(user=self.user)
        self.assertEqual((project.title, project.url, project.video_type), ('Great Edit', YT, 'long'))
        self.assertTrue(project.image.name.startswith('projects/'))

        info = PersonalInfo.objects.get(user=self.user)
        self.assertEqual((info.full_name, info.title), ('Sara Ali', 'Video Editor'))
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Creative'])

        self.assertEqual(events('welcome_submitted').get().props['links'], 1)
        self.assertEqual(events('project_created').get().props['source'], 'welcome')

    def test_typed_title_and_type_override_the_lookup(self):
        self.post([YT], ['My Cut'], ['reel'])
        project = Project.objects.get(user=self.user)
        self.assertEqual((project.title, project.video_type), ('My Cut', 'reel'))

    def test_arabic_submit_redirects_with_language(self):
        resp = self.post([YT], [''], ['long'], url='arabic_welcome')
        self.assertRedirects(resp, '/sara/?welcome=1&lang=ar', fetch_redirect_response=False)
        self.assertEqual(PersonalInfo.objects.get(user=self.user).title, 'مونتير فيديو')

    def test_same_link_twice_makes_one_project(self):
        self.post([YT, YT], ['', ''], ['long', 'long'])
        self.assertEqual(Project.objects.filter(user=self.user).count(), 1)
        self.post([YT], [''], ['long'], add='1')  # and again on a later visit
        self.assertEqual(Project.objects.filter(user=self.user).count(), 1)

    def test_at_most_three_links(self):
        urls = [f'https://vimeo.com/{i}' for i in range(1, 6)]
        self.fetch_mock.side_effect = lambda u: meta(url=u, title=f't{u[-1]}', provider='vimeo')
        self.post(urls, [''] * 5, ['long'] * 5)
        self.assertEqual(Project.objects.filter(user=self.user).count(), 3)

    def test_blank_rows_are_ignored(self):
        self.post(['', YT, '   '], ['', '', ''], ['long', 'long', 'long'])
        self.assertEqual(Project.objects.filter(user=self.user).count(), 1)

    def test_private_video_is_refused_with_a_message(self):
        self.fetch_mock.return_value = meta(ok=False, error='private')
        resp = self.post([YT], [''], ['long'])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'This video is private')
        self.assertEqual(Project.objects.filter(user=self.user).count(), 0)
        self.assertFalse(PersonalInfo.objects.filter(user=self.user).exists())

    def test_nonexistent_youtube_video_is_refused(self):
        self.fetch_mock.return_value = meta(ok=False, error='not_found')
        resp = self.post([YT], [''], ['long'])
        self.assertContains(resp, "couldn&#x27;t find that video")
        self.assertEqual(Project.objects.filter(user=self.user).count(), 0)

    def test_not_found_on_a_provider_with_unreliable_400s_is_only_a_warning(self):
        tiktok = 'https://www.tiktok.com/@u/photo/1'
        self.fetch_mock.return_value = meta(url=tiktok, provider='tiktok', ok=False, error='not_found')
        self.post([tiktok], ['My TikTok'], ['reel'])
        self.assertEqual(Project.objects.get(user=self.user).title, 'My TikTok')

    def test_invalid_link_shows_an_error_and_keeps_what_was_typed(self):
        resp = self.post(['not a link'], ['My title'], ['reel'])
        self.assertContains(resp, 'Paste a full link')
        self.assertContains(resp, 'value="not a link"')
        self.assertContains(resp, 'value="My title"')
        self.assertEqual(Project.objects.filter(user=self.user).count(), 0)

    def test_lookup_failure_still_creates_the_project_without_a_thumbnail(self):
        self.fetch_mock.return_value = meta(ok=False, error='timeout')
        resp = self.post([YT], ['Typed title'], ['long'])
        self.assertRedirects(resp, '/sara/?welcome=1', fetch_redirect_response=False)
        project = Project.objects.get(user=self.user)
        self.assertEqual(project.title, 'Typed title')
        self.assertFalse(project.image)
        self.thumb_mock.assert_not_called()

    def test_lookup_failure_without_a_title_falls_back_to_a_default(self):
        self.fetch_mock.return_value = meta(ok=False, error='network')
        self.post([YT], [''], ['long'])
        self.assertEqual(Project.objects.get(user=self.user).title, 'My video')

    def test_thumbnail_failure_does_not_block(self):
        self.thumb_mock.side_effect = None
        self.thumb_mock.return_value = None
        self.post([YT], [''], ['long'])
        project = Project.objects.get(user=self.user)
        self.assertFalse(project.image)

    def test_empty_submit_asks_for_a_link(self):
        resp = self.post([''], [''], ['long'])
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Paste at least one video link')

    def test_adding_more_does_not_recreate_personal_info(self):
        PersonalInfo.objects.create(user=self.user, full_name='Custom', title='Colorist', email='', phone='', bio='')
        Project.objects.create(user=self.user, title='First', url='https://vimeo.com/1')
        self.post(['https://vimeo.com/2'], [''], ['long'], add='1')
        self.assertEqual(Project.objects.filter(user=self.user).count(), 2)
        self.assertEqual(PersonalInfo.objects.get(user=self.user).title, 'Colorist')

    def test_resolved_url_from_the_lookup_is_stored(self):
        self.fetch_mock.return_value = meta(url='https://www.tiktok.com/@u/video/1', provider='tiktok', video_type='reel')
        self.post(['https://vm.tiktok.com/abc/'], [''], [''])
        project = Project.objects.get(user=self.user)
        self.assertEqual((project.url, project.video_type), ('https://www.tiktok.com/@u/video/1', 'reel'))

    def test_clients_cannot_use_welcome(self):
        client_user = make_editor('buyer', account_type='client')
        self.client.force_login(client_user)
        self.post([YT], [''], ['long'])
        self.assertEqual(Project.objects.filter(user=client_user).count(), 0)


class PreviewEndpointTests(OnboardingTestCase):
    def setUp(self):
        super().setUp()
        self.enable()
        self.url = reverse('welcome_preview_link')

    def call(self, payload, raw=None):
        return self.client.post(self.url, raw if raw is not None else json.dumps(payload),
                                content_type='application/json')

    def test_requires_login_and_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(self.url, '{}', content_type='application/json').status_code, 302)

    def test_returns_lookup_result(self):
        with patch('core.oembed.fetch', return_value=meta()):
            data = self.call({'url': YT, 'lang': 'en'}).json()
        self.assertTrue(data['ok'])
        self.assertEqual((data['title'], data['provider'], data['video_type']), ('Great Edit', 'youtube', 'long'))
        self.assertTrue(data['thumbnail_url'].startswith('https://i.ytimg.com/'))
        self.assertFalse(data['duplicate'])
        self.assertEqual(events('link_previewed').get().props['provider'], 'youtube')

    def test_flags_duplicates(self):
        Project.objects.create(user=self.user, title='P', url=YT)
        with patch('core.oembed.fetch', return_value=meta()):
            self.assertTrue(self.call({'url': YT}).json()['duplicate'])

    def test_invalid_url_gets_a_friendly_message_in_the_right_language(self):
        data = self.call({'url': 'hello world', 'lang': 'ar'}).json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['error'], 'invalid')
        self.assertIn('https://', data['message'])
        self.assertIn('رابطًا', data['message'])

    def test_private_message(self):
        with patch('core.oembed.fetch', return_value=meta(ok=False, error='private')):
            data = self.call({'url': YT}).json()
        self.assertEqual(data['error'], 'private')
        self.assertIn('Unlisted', data['message'])

    def test_hard_flag_tells_the_page_whether_to_block_the_row(self):
        cases = (
            (meta(ok=False, error='private'), True),
            (meta(ok=False, error='not_found'), True),
            (meta(provider='tiktok', ok=False, error='not_found'), False),
            (meta(ok=False, error='timeout'), False),
            (meta(), False),
        )
        for result, hard in cases:
            with patch('core.oembed.fetch', return_value=result):
                data = self.call({'url': YT}).json()
            self.assertEqual(data['hard'], hard, (result.provider, result.error))

    def test_soft_failure_has_a_message(self):
        with patch('core.oembed.fetch', return_value=meta(ok=False, error='timeout')):
            data = self.call({'url': YT}).json()
        self.assertIn('type a title', data['message'])

    def test_bad_bodies(self):
        self.assertEqual(self.call(None, raw='{not json').status_code, 400)
        self.assertEqual(self.call(None, raw='[1, 2]').status_code, 400)

    def test_rate_limited_to_thirty_per_hour(self):
        with patch('core.oembed.fetch', return_value=meta()):
            for _ in range(onboarding.PREVIEW_LOOKUPS_PER_HOUR):
                self.assertEqual(self.call({'url': YT}).status_code, 200)
            self.assertEqual(self.call({'url': YT}).status_code, 429)


class RevealBarTests(OnboardingTestCase):
    def setUp(self):
        super().setUp()
        self.enable()
        Profile.objects.create(user=self.user, theme=self.themes['Creative'])
        PersonalInfo.objects.create(user=self.user, full_name='Sara Ali', title='Video Editor',
                                    email='', phone='', bio='')
        Project.objects.create(user=self.user, title='Cut', url=YT)
        self.url = reverse('preview', kwargs={'username': 'sara'})

    def test_owner_sees_the_bar(self):
        resp = self.client.get(self.url + '?welcome=1')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="sfw-bar"')
        self.assertContains(resp, 'This is your portfolio, Sara.')
        self.assertContains(resp, 'Client-ready 0/3')
        self.assertContains(resp, '/welcome/?add=1&amp;ra=add')
        self.assertContains(resp, 'ra=live')
        self.assertEqual(events('reveal_viewed').get().props['projects'], 1)

    def test_no_bar_without_the_flag(self):
        self.assertNotContains(self.client.get(self.url), 'sfw-bar')

    def test_other_users_and_visitors_never_see_it(self):
        Profile.objects.filter(user=self.user).update(is_public=True)
        give_payment(self.user)  # active plan so the page is public
        other = make_editor('other')
        self.client.force_login(other)
        resp = self.client.get(self.url + '?welcome=1')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'sfw-bar')
        self.client.logout()
        self.assertNotContains(self.client.get(self.url + '?welcome=1'), 'sfw-bar')
        self.assertEqual(events('reveal_viewed').count(), 0)

    def test_unpaid_visitors_get_the_private_page_without_a_bar(self):
        self.client.logout()
        resp = self.client.get(self.url + '?welcome=1')
        self.assertEqual(resp.status_code, 403)
        self.assertNotContains(resp, 'sfw-bar', status_code=403)

    def test_first_name_is_escaped(self):
        CustomUser.objects.filter(pk=self.user.pk).update(first_name='<script>alert(1)</script>')
        resp = self.client.get(self.url + '?welcome=1')
        self.assertNotContains(resp, '<script>alert(1)</script>')
        self.assertContains(resp, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_arabic_bar(self):
        resp = self.client.get(self.url + '?welcome=1&lang=ar')
        self.assertContains(resp, 'هذا معرض أعمالك يا Sara')
        self.assertContains(resp, 'dir="rtl"')
        self.assertContains(resp, '/ar/welcome/?add=1')

    def test_embedded_demo_preview_has_no_apply_theme_bar(self):
        # The welcome page shows /preview/<theme>/?embed=1 in an iframe; the "Apply Theme"
        # bar belongs to the standalone theme preview only.
        from core.views import index  # noqa: F401  (landing page uses the same embed flag)
        embedded = self.client.get('/preview/creative/?embed=1')
        self.assertEqual(embedded.status_code, 200)
        self.assertNotContains(embedded, 'preview-bar-container')
        standalone = self.client.get('/preview/creative/')
        self.assertContains(standalone, 'preview-bar-container')

    def test_checklist_reflects_progress(self):
        Project.objects.create(user=self.user, title='B')
        Project.objects.create(user=self.user, title='C')
        PersonalInfo.objects.filter(user=self.user).update(title='Colorist', booking_url='https://wa.me/20100')
        self.assertContains(self.client.get(self.url + '?welcome=1'), 'Client-ready 3/3')

    def test_look_chips_switch_the_theme(self):
        resp = self.client.get(self.url + '?welcome=1')
        self.assertContains(resp, reverse('welcome_set_theme'))
        self.assertContains(resp, 'sfw-looks-label')
        self.assertContains(resp, 'Try another look')
        for name in ('Creative', 'Pro', 'Minimal'):
            self.assertContains(resp, f'>{name}</button>')
        self.assertNotContains(resp, '>Animated</button>')  # needs a profile photo

        resp = self.client.post(reverse('welcome_set_theme'), {'theme': self.themes['Pro'].pk, 'lang': 'en'})
        self.assertRedirects(resp, '/sara/?welcome=1', fetch_redirect_response=False)
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Pro'])
        props = events('theme_switched').get().props
        self.assertEqual((props['from'], props['to'], props['via']), ('Creative', 'Pro', 'reveal_bar'))

    def test_only_curated_themes_can_be_set(self):
        self.client.post(reverse('welcome_set_theme'), {'theme': self.themes['Animated'].pk})
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Creative'])
        self.client.post(reverse('welcome_set_theme'), {'theme': 'abc'})
        self.client.post(reverse('welcome_set_theme'), {})
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Creative'])

    def test_set_theme_requires_post_and_login(self):
        self.assertEqual(self.client.get(reverse('welcome_set_theme')).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('welcome_set_theme'), {'theme': 1}).status_code, 302)


class ClientReadyTests(OnboardingTestCase):
    def test_counts(self):
        self.assertEqual(onboarding.client_ready(self.user)['count'], 0)
        PersonalInfo.objects.create(user=self.user, full_name='S', title='Video Editor', email='', phone='', bio='')
        self.assertFalse(onboarding.client_ready(self.user)['title'])  # placeholder title doesn't count
        PersonalInfo.objects.filter(user=self.user).update(title='Colorist', phone='+201001234567')
        ready = onboarding.client_ready(self.user)
        self.assertTrue(ready['title'] and ready['contact'])
        self.assertEqual(ready['count'], 2)


class ReservedUsernameEnforcementTests(OnboardingTestCase):
    """A route name must not be claimable later by renaming, or generated for a client."""

    def post_profile(self, username, url='profile'):
        return self.client.post(reverse(url), {
            'first_name': 'Sara', 'last_name': 'Ali', 'email': 'sara@example.com', 'username': username,
        })

    def test_profile_rename_to_a_route_name_is_refused(self):
        resp = self.post_profile('Welcome')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'This username is reserved')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'sara')

    def test_arabic_profile_rename_is_refused_too(self):
        resp = self.post_profile('dashboard', url='arabic_profile')
        self.assertContains(resp, 'اختر اسمًا آخر')
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'sara')

    def test_ordinary_rename_still_works(self):
        self.assertEqual(self.post_profile('sara_edits').status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'sara_edits')

    def test_unchanged_username_is_not_rechecked(self):
        CustomUser.objects.filter(pk=self.user.pk).update(username='email')  # legacy account
        self.client.force_login(CustomUser.objects.get(pk=self.user.pk))
        self.assertEqual(self.post_profile('email').status_code, 302)

    def test_generated_client_usernames_skip_route_names(self):
        from core.views import _generate_client_username
        for name in ('Welcome', 'Admin', 'Dashboard'):
            self.assertNotIn(_generate_client_username(name, 'x@example.com'),
                             __import__('django.conf', fromlist=['settings']).settings.RESERVED_USERNAMES)


class ReservedUsernameTests(TestCase):
    data = {'first_name': 'A', 'last_name': 'B', 'email': 'ab@example.com',
            'password1': 'Str0ng-pass-99', 'password2': 'Str0ng-pass-99'}

    def form(self, username):
        return RegisterForm({**self.data, 'username': username})

    def test_route_names_are_rejected_case_insensitively(self):
        for name in ('welcome', 'Dashboard', 'ADMIN', 'ar', 'static', 'email'):
            form = self.form(name)
            self.assertFalse(form.is_valid(), name)
            self.assertIn('username', form.errors)

    def test_ordinary_usernames_still_work(self):
        self.assertTrue(self.form('sara_edits').is_valid())

    def test_google_signup_blacklist_is_configured(self):
        from django.conf import settings
        self.assertIn('welcome', settings.ACCOUNT_USERNAME_BLACKLIST)

    def test_no_reserved_name_collides_with_a_real_route_the_other_way(self):
        # The new routes themselves must be on the list.
        from django.conf import settings
        for name in ('welcome', 'email'):
            self.assertIn(name, settings.RESERVED_USERNAMES)


# ---------------------------------------------------------------------------
# PR-6: deferred email verification
# ---------------------------------------------------------------------------

@FAST_HASH
class DeferredVerificationTests(TestCase):
    data = {'first_name': 'Nour', 'last_name': 'Hassan', 'username': 'nour_h',
            'email': 'nour@example.com', 'password1': 'Str0ng-pass-99', 'password2': 'Str0ng-pass-99'}

    def setUp(self):
        clear_cache()
        seed_themes()
        site_settings(defer_email_verification=True)

    def signup(self, client=None, **overrides):
        client = client or self.client
        return client.post(reverse('signup'), {**self.data, **overrides}, REMOTE_ADDR='7.7.7.7')

    def test_signup_logs_the_user_in_without_a_code(self):
        resp = self.signup()
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)
        user = CustomUser.objects.get(username='nour_h')
        self.assertTrue(user.is_active)
        self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))
        self.assertFalse(EmailAddress.objects.get(user=user).verified)
        self.assertEqual(len(mail.outbox), 1)  # the code is still emailed
        self.assertTrue(onboarding.needs_email_verification(user))

    def test_signup_never_redirects_off_site(self):
        for i, evil in enumerate(('//evil.example.com/x', 'https://evil.example.com/x', 'javascript:alert(1)')):
            from django.test import Client
            resp = Client().post(
                reverse('signup'),
                {**self.data, 'username': f'safe{i}', 'email': f'safe{i}@example.com', 'next': evil},
                REMOTE_ADDR='6.6.6.6',
            )
            self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False, msg_prefix=evil)

    def test_signup_follows_a_safe_next(self):
        resp = self.client.post(reverse('signup'), {**self.data, 'next': '/themes/'}, REMOTE_ADDR='7.7.7.7')
        self.assertRedirects(resp, '/themes/', fetch_redirect_response=False)

    def test_arabic_signup_goes_to_the_arabic_dashboard(self):
        resp = self.client.post(reverse('arabic_signup'), self.data, REMOTE_ADDR='7.7.7.7')
        self.assertRedirects(resp, reverse('arabic_dashboard'), fetch_redirect_response=False)

    def test_deferral_off_keeps_the_old_flow(self):
        site_settings(defer_email_verification=False)
        resp = self.signup()
        self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        self.assertFalse(CustomUser.objects.get(username='nour_h').is_active)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_unverified_user_cannot_publish_or_pay(self):
        self.signup()
        for url in (
            reverse('activate_portfolio'),
        ):
            resp = self.client.post(url)
            self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        for name, args in (
            ('manual_payment', ['monthly']), ('arabic_manual_payment', ['monthly']),
            ('fawaterk_checkout', ['monthly']), ('arabic_fawaterk_checkout', ['monthly']),
        ):
            resp = self.client.get(reverse(name, args=args))
            self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False, msg_prefix=name)
        self.assertEqual(self.client.session['next_url'], '/ar/fawaterk/checkout/monthly/')

    def test_unverified_user_can_still_build_and_see_pricing(self):
        self.signup()
        self.assertEqual(self.client.get(reverse('update_portfolio')).status_code, 200)
        self.assertEqual(self.client.get(reverse('payment')).status_code, 200)

    def test_verify_page_works_for_a_signed_in_user_and_unlocks_everything(self):
        self.signup()
        user = CustomUser.objects.get(username='nour_h')
        self.assertContains(self.client.get(reverse('verify_otp')), 'nour@example.com')
        code = EmailOTP.objects.get(user=user).otp
        resp = self.client.post(reverse('verify_otp'), {'otp': code})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(EmailAddress.objects.get(user=user).verified)
        self.assertFalse(onboarding.needs_email_verification(user))
        # Publishing is no longer blocked by verification (it falls through to the
        # normal "needs a plan" redirect instead).
        resp = self.client.post(reverse('activate_portfolio'))
        self.assertRedirects(resp, reverse('payment'), fetch_redirect_response=False)

    def test_signed_in_unverified_user_can_resend(self):
        self.signup()
        mail.outbox.clear()
        resp = self.client.post(reverse('resend_otp'))
        self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_for_an_active_verified_user_does_nothing(self):
        user = make_editor('verified_one')
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        self.client.force_login(user)
        mail.outbox.clear()
        self.client.post(reverse('resend_otp'))
        self.assertEqual(len(mail.outbox), 0)

    def test_legacy_and_google_users_are_never_gated(self):
        legacy = make_editor('legacy_one')
        self.assertFalse(onboarding.needs_email_verification(legacy))
        google = make_editor('google_one')
        EmailAddress.objects.create(user=google, email=google.email, verified=True, primary=True)
        self.assertFalse(onboarding.needs_email_verification(google))
        mixed = make_editor('mixed_one')
        EmailAddress.objects.create(user=mixed, email='old@example.com', verified=False)
        EmailAddress.objects.create(user=mixed, email=mixed.email, verified=True, primary=True)
        self.assertFalse(onboarding.needs_email_verification(mixed))

    def test_honeypot_blocks_bots(self):
        resp = self.signup(company_website='http://spam.example')
        self.assertRedirects(resp, reverse('signup'), fetch_redirect_response=False)
        self.assertFalse(CustomUser.objects.filter(username='nour_h').exists())

    def test_honeypot_also_applies_when_deferral_is_off(self):
        site_settings(defer_email_verification=False)
        self.signup(company_website='x')
        self.assertFalse(CustomUser.objects.filter(username='nour_h').exists())

    def test_signups_are_rate_limited_per_ip_when_deferred(self):
        from django.test import Client
        for i in range(onboarding.SIGNUP_LIMIT_PER_HOUR):
            resp = self.signup(Client(), username=f'user{i}', email=f'u{i}@example.com')
            self.assertEqual(resp.status_code, 302, i)
        resp = self.signup(Client(), username='one_too_many', email='many@example.com')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Too many signups')
        self.assertFalse(CustomUser.objects.filter(username='one_too_many').exists())

    def test_rate_limit_is_off_without_deferral(self):
        site_settings(defer_email_verification=False)
        request = RequestFactory().post('/signup/', REMOTE_ADDR='5.5.5.5')
        for _ in range(onboarding.SIGNUP_LIMIT_PER_HOUR + 5):
            self.assertFalse(onboarding.signup_rate_limited(request))

    def test_rate_limit_is_per_ip(self):
        request_a = RequestFactory().post('/signup/', REMOTE_ADDR='1.1.1.1')
        request_b = RequestFactory().post('/signup/', REMOTE_ADDR='2.2.2.2')
        for _ in range(onboarding.SIGNUP_LIMIT_PER_HOUR):
            onboarding.signup_rate_limited(request_a)
        self.assertTrue(onboarding.signup_rate_limited(request_a))
        self.assertFalse(onboarding.signup_rate_limited(request_b))
