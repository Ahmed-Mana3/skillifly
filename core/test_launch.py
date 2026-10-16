"""Launch checklist: signup -> full-screen checklist -> step pages -> own portfolio -> dashboard."""
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core import launch
from core.models import (
    ActivationEvent, CustomUser, PersonalInfo, Profile, Project, Skill, UserAccount,
)
from core.oembed import VideoMeta
from core.testing_helpers import (
    TempMediaMixin, clear_cache, give_payment, make_editor, png_bytes, seed_themes, site_settings,
)

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
YT = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


def events(name):
    return ActivationEvent.objects.filter(name=name)


def meta(url=YT, title='Great Edit', ok=True, error='', provider='youtube'):
    return VideoMeta(url=url, provider=provider, title=title if ok else '', video_type='long', ok=ok, error=error)


class LaunchTestCase(TestCase):
    def setUp(self):
        clear_cache()
        self.themes = seed_themes()
        self.settings_row = site_settings()
        self.user = make_editor()
        self.set_status('active')
        self.client.force_login(self.user)

    def set_status(self, status, user=None):
        UserAccount.objects.filter(user=user or self.user).update(launch_status=status)

    def account(self):
        return UserAccount.objects.get(user=self.user)

    def complete(self, *steps):
        if 'personal' in steps:
            PersonalInfo.objects.create(user=self.user, full_name='Sara Ali', title='Colorist', email='', phone='', bio='')
        if 'project' in steps:
            Project.objects.create(user=self.user, title='Cut 1', url=YT)
        if 'theme' in steps:
            UserAccount.objects.filter(user=self.user).update(launch_theme_picked=True)
        if 'skills' in steps:
            Skill.objects.create(user=self.user, name='DaVinci Resolve')


# ---------------------------------------------------------------------------
# Entering the flow
# ---------------------------------------------------------------------------

@FAST_HASH
class SignupEntersTheFlowTests(TestCase):
    data = {'first_name': 'Nour', 'last_name': 'Hassan', 'username': 'nour_h',
            'email': 'nour@example.com', 'password1': 'Str0ng-pass-99', 'password2': 'Str0ng-pass-99'}

    def setUp(self):
        clear_cache()
        seed_themes()

    def status(self):
        return UserAccount.objects.get(user__username='nour_h').launch_status

    def test_email_signup_starts_the_checklist(self):
        site_settings()
        self.client.post(reverse('signup'), self.data)
        self.assertEqual(self.status(), 'active')

    def test_arabic_signup_too(self):
        site_settings()
        self.client.post(reverse('arabic_signup'), self.data)
        self.assertEqual(self.status(), 'active')

    def test_switch_off_keeps_the_old_flow(self):
        site_settings(launch_checklist_enabled=False)
        self.client.post(reverse('signup'), self.data)
        self.assertEqual(self.status(), '')

    def test_switch_is_on_by_default(self):
        self.assertTrue(launch.enabled())  # no SiteSettings row yet
        site_settings()
        self.assertTrue(launch.enabled())

    def test_deferred_signup_lands_on_the_checklist(self):
        site_settings(defer_email_verification=True)
        resp = self.client.post(reverse('signup'), self.data, REMOTE_ADDR='9.9.9.9', follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], reverse('launch'))
        self.assertNotContains(resp, 'Welcome, Nour')  # the greeting is hidden on the first visit

    def test_only_editors_can_start(self):
        site_settings()
        client = make_editor('cl', account_type='client')
        legacy = make_editor('legacy', account_type=None)
        self.assertFalse(launch.start(client))
        self.assertFalse(launch.start(legacy))
        self.assertEqual(UserAccount.objects.get(user=client).launch_status, 'done')  # untouched (the helper's default)

    def test_google_editor_signup_starts_the_checklist(self):
        from core.adapters import SkilliflySocialAccountAdapter
        site_settings()
        user = make_editor('gg', account_type=None)
        request = self.client.request().wsgi_request
        request.session = self.client.session
        request.session['signup_account_type'] = 'editor'
        with patch('allauth.socialaccount.adapter.DefaultSocialAccountAdapter.save_user', return_value=user):
            SkilliflySocialAccountAdapter().save_user(request, sociallogin=None)
        self.assertEqual(UserAccount.objects.get(user=user).launch_status, 'active')


# ---------------------------------------------------------------------------
# Dashboard routing
# ---------------------------------------------------------------------------

class RoutingTests(LaunchTestCase):
    def test_dashboard_sends_new_editors_to_the_checklist(self):
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('launch'), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('arabic_dashboard')), reverse('arabic_launch'),
                             fetch_redirect_response=False)

    def test_every_visit_until_finished(self):
        for _ in range(2):
            self.assertRedirects(self.client.get(reverse('dashboard')), reverse('launch'), fetch_redirect_response=False)

    def test_skip_for_now_lets_them_out_for_the_session(self):
        resp = self.client.post(reverse('launch_skip'))
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(events('launch_skipped').count(), 1)
        self.assertEqual(self.account().launch_status, 'active')  # back next session

    def test_arabic_skip(self):
        resp = self.client.post(reverse('launch_skip'), {'lang': 'ar'})
        self.assertRedirects(resp, reverse('arabic_dashboard'), fetch_redirect_response=False)

    def test_skip_needs_post(self):
        self.assertEqual(self.client.get(reverse('launch_skip')).status_code, 405)

    def test_finished_users_see_the_dashboard(self):
        self.set_status('done')
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_older_accounts_that_have_not_finished_are_sent_too(self):
        self.set_status('')  # an account from before the checklist existed
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('launch'), fetch_redirect_response=False)
        self.assertEqual(self.account().launch_status, 'active')

    def test_older_accounts_keep_credit_for_a_theme_they_chose(self):
        self.set_status('')
        Profile.objects.update_or_create(user=self.user, defaults={'theme': self.themes['Pro']})
        self.client.get(reverse('dashboard'))
        self.assertTrue(self.account().launch_theme_picked)

    def test_older_accounts_that_already_have_100_xp_are_never_bothered(self):
        self.set_status('')
        Profile.objects.update_or_create(user=self.user, defaults={'theme': self.themes['Pro']})
        self.complete('personal', 'project', 'skills')
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        self.assertEqual(self.account().launch_status, 'done')

    def test_the_landing_page_leads_to_the_checklist(self):
        resp = self.client.get('/', follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], reverse('launch'))

    def test_skipping_lasts_only_a_short_while(self):
        self.client.post(reverse('launch_skip'))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        session = self.client.session
        session['launch_skipped_at'] -= (launch.SKIP_MINUTES + 1) * 60  # the next visit, later
        session.save()
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('launch'), fetch_redirect_response=False)

    def test_switch_off_stops_routing_and_closes_the_pages(self):
        site_settings(launch_checklist_enabled=False)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)
        for name in ('launch', 'launch_personal', 'launch_project', 'launch_skills'):
            self.assertRedirects(self.client.get(reverse(name)), reverse('dashboard'), fetch_redirect_response=False)

    def test_clients_are_never_sent(self):
        client = make_editor('cl', account_type='client')
        self.set_status('active', user=client)
        self.client.force_login(client)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('client_dashboard'),
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('launch')), reverse('dashboard'), fetch_redirect_response=False)

    def test_welcome_page_routing_is_suppressed_for_launch_users(self):
        site_settings(onboarding_v2_enabled=True)
        self.client.post(reverse('launch_skip'))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_welcome_page_is_replaced_by_the_checklist_for_every_editor(self):
        site_settings(onboarding_v2_enabled=True)
        self.set_status('')
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('launch'), fetch_redirect_response=False)

    def test_language_cookie_picks_the_arabic_checklist(self):
        self.client.cookies['skillifly_lang'] = 'ar'
        self.assertRedirects(self.client.get(reverse('launch')), reverse('arabic_launch'), fetch_redirect_response=False)

    def test_launch_is_a_reserved_username(self):
        self.assertIn('launch', settings.RESERVED_USERNAMES)


# ---------------------------------------------------------------------------
# The checklist page
# ---------------------------------------------------------------------------

class ChecklistTests(LaunchTestCase):
    def test_first_visit(self):
        resp = self.client.get(reverse('launch'))
        self.assertNotContains(resp, 'Welcome, Sara')  # the greeting is hidden on the first visit
        self.assertNotContains(resp, '<h1')
        self.assertContains(resp, 'Introduce yourself')
        self.assertContains(resp, 'aria-current="step"', count=1)
        self.assertContains(resp, 'Unlocks after step 1')
        self.assertContains(resp, 'href="%s"' % reverse('launch_personal'))
        self.assertNotContains(resp, 'href="%s"' % reverse('launch_project'))  # locked
        self.assertNotContains(resp, 'Skip for now')  # the skip button is hidden
        self.assertNotContains(resp, 'id="lc-toast"')
        self.assertEqual(events('launch_viewed').count(), 1)

    def test_it_is_full_screen(self):
        resp = self.client.get(reverse('launch'))
        self.assertTemplateUsed(resp, 'launch/base.html')
        self.assertTemplateNotUsed(resp, 'core/base.html')

    def test_launch_pages_use_the_dashboard_design_system(self):
        for name in ('launch', 'launch_personal', 'launch_project', 'launch_skills'):
            resp = self.client.get(reverse(name))
            self.assertTemplateUsed(resp, 'dashboard/_dash_system.html', msg_prefix=name)
            self.assertContains(resp, 'class="dash"', msg_prefix=name)

    def test_xp_adds_up_to_100(self):
        self.assertEqual(launch.XP_TOTAL, 100)
        self.assertEqual(launch.STEPS, ('personal', 'project', 'theme', 'skills'))
        self.assertEqual(max(launch.XP, key=launch.XP.get), 'project')  # the video is worth the most

    def test_every_step_shows_its_xp(self):
        resp = self.client.get(reverse('launch'))
        for step in launch.STEPS:
            self.assertContains(resp, f'+{launch.XP[step]} XP', msg_prefix=step)
        self.assertContains(resp, '0</b> / 100 XP')
        self.assertEqual(resp.context['launch']['xp'], 0)

    def test_it_gives_the_portfolio_a_theme(self):
        self.client.get(reverse('launch'))
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Creative'])
        self.assertFalse(self.account().launch_theme_picked)  # the default doesn't tick the step

    def test_progress_and_celebration_after_a_step(self):
        self.complete('personal')
        resp = self.client.get(reverse('launch') + '?done=personal')
        self.assertContains(resp, 'id="lc-toast"')
        self.assertContains(resp, 'Nice to meet you!')
        self.assertContains(resp, '+25 XP</bdi>')
        self.assertContains(resp, '25 / 100 XP</bdi>')
        state = resp.context['launch']
        self.assertEqual((state['done_count'], state['xp'], state['percent'], state['current']), (1, 25, 25, 'project'))
        self.assertEqual(resp.context['start_xp'], 0)  # the XP bar grows from where it was
        self.assertFalse(resp.context['celebrate_ready'])
        self.assertContains(resp, 'href="%s"' % reverse('launch_project'))

    def test_no_celebration_for_a_step_that_is_not_done(self):
        resp = self.client.get(reverse('launch') + '?done=skills')
        self.assertNotContains(resp, 'id="lc-toast"')
        resp = self.client.get(reverse('launch') + '?done=<script>')
        self.assertEqual(resp.status_code, 200)

    def test_reaching_100_xp_elsewhere_finishes_and_celebrates(self):
        self.complete('personal', 'project', 'theme', 'skills')
        resp = self.client.get(reverse('launch'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.account().launch_status, 'done')
        self.assertTrue(resp.context['celebrate_ready'])
        self.assertContains(resp, "100 XP! You're ready.")

    def test_at_100_xp_they_can_view_the_portfolio_or_go_to_the_dashboard(self):
        self.complete('personal', 'project', 'theme', 'skills')
        self.set_status('done')
        resp = self.client.get(reverse('launch'))
        state = resp.context['launch']
        self.assertEqual((state['xp'], state['ready'], state['current']), (100, True, None))
        self.assertContains(resp, "You're ready,")
        self.assertContains(resp, '<span class="lc-name">Sara')  # the name and the bird wrap as one piece
        self.assertContains(resp, 'Your portfolio is ready to view')
        self.assertContains(resp, 'href="/sara/?launched=1"')
        self.assertContains(resp, 'View my portfolio')
        self.assertContains(resp, 'href="%s"' % reverse('dashboard'), count=2)  # top bar + the ready card
        self.assertContains(resp, reverse('payment') + '?ra=live')  # publishing stays one click away
        self.assertNotContains(resp, 'id="lc-toast"')  # no replay on a later visit
        self.assertNotContains(resp, 'Skip for now')

    def test_live_users_are_not_asked_to_publish(self):
        self.complete('personal', 'project', 'theme', 'skills')
        self.set_status('done')
        give_payment(self.user)
        Profile.objects.update_or_create(user=self.user, defaults={'is_public': True})
        resp = self.client.get(reverse('launch'))
        self.assertContains(resp, 'Your portfolio is complete and live')
        self.assertNotContains(resp, 'Publish now')

    def test_photo_hint_for_a_theme_that_shows_one(self):
        self.complete('personal', 'project', 'theme')
        Profile.objects.update_or_create(user=self.user, defaults={'theme': self.themes['Animated']})
        self.assertContains(self.client.get(reverse('launch')), 'This look shows a profile photo.')

    def test_arabic_checklist(self):
        resp = self.client.get(reverse('arabic_launch'))
        self.assertContains(resp, 'dir="rtl"')
        self.assertContains(resp, 'عرّف بنفسك')
        self.assertNotContains(resp, 'تخطَّ الآن')  # the skip button is hidden
        self.assertContains(resp, 'href="%s"' % reverse('arabic_launch_personal'))

    def test_first_name_is_escaped(self):
        CustomUser.objects.filter(pk=self.user.pk).update(first_name='<b>Sara</b>')
        self.complete('personal')  # the greeting shows once a step is done
        resp = self.client.get(reverse('launch'))
        self.assertNotContains(resp, '<b>Sara</b>')
        self.assertContains(resp, '&lt;b&gt;Sara&lt;/b&gt;')

    def test_email_code_step_lands_on_the_checklist_with_its_message(self):
        from core.models import EmailOTP
        pending = make_editor('pending', is_active=False)
        self.set_status('active', user=pending)
        EmailOTP.objects.create(user=pending, otp='123456')
        self.client.logout()
        session = self.client.session
        session['verification_user_id'] = pending.pk
        session.save()
        resp = self.client.post(reverse('verify_otp'), {'otp': '123456'}, follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], reverse('launch'))
        self.assertContains(resp, 'lx-msg-success')
        self.assertContains(resp, 'Email verified successfully!')


# ---------------------------------------------------------------------------
# Step 1: about you
# ---------------------------------------------------------------------------

class PersonalStepTests(TempMediaMixin, LaunchTestCase):
    def post(self, arabic=False, **data):
        body = {'fullname': 'Sara Ali', 'title': 'Colorist', 'bio': '', 'booking_url': ''}
        body.update(data)
        return self.client.post(reverse('arabic_launch_personal' if arabic else 'launch_personal'), body)

    def test_prefilled_from_signup(self):
        resp = self.client.get(reverse('launch_personal'))
        self.assertContains(resp, 'value="Sara Ali"')
        self.assertContains(resp, 'value="Video Editor"')
        self.assertContains(resp, 'Step 1 of 4')
        self.assertContains(resp, '+25 XP')
        self.assertContains(resp, 'enctype="multipart/form-data"')

    def test_save_goes_back_to_the_checklist_with_a_celebration(self):
        resp = self.post(bio='I cut ads.', booking_url='01001234567')
        self.assertRedirects(resp, reverse('launch') + '?done=personal', fetch_redirect_response=False)
        info = PersonalInfo.objects.get(user=self.user)
        self.assertEqual((info.full_name, info.title, info.bio), ('Sara Ali', 'Colorist', 'I cut ads.'))
        self.assertEqual(info.booking_url, 'https://wa.me/01001234567')
        self.assertEqual((info.email, info.phone), ('', ''))
        self.assertEqual(events('launch_step_completed').get().props['step'], 'personal')

    def test_existing_contact_details_are_kept(self):
        PersonalInfo.objects.create(user=self.user, full_name='S', title='T', email='pub@example.com', phone='0100', bio='old')
        self.post(bio='new')
        info = PersonalInfo.objects.get(user=self.user)
        self.assertEqual((info.email, info.phone, info.bio), ('pub@example.com', '0100', 'new'))

    def test_editing_a_done_step_returns_without_a_celebration(self):
        self.complete('personal')
        resp = self.post(title='Motion Designer')
        self.assertRedirects(resp, reverse('launch'), fetch_redirect_response=False)
        self.assertFalse(events('launch_step_completed').exists())

    def test_name_and_title_are_required(self):
        resp = self.post(title='  ')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Add your title')
        self.assertFalse(PersonalInfo.objects.filter(user=self.user).exists())

    def test_bad_booking_link(self):
        resp = self.post(booking_url='not a link')
        self.assertContains(resp, 'Enter a full booking link')
        self.assertContains(resp, 'value="not a link"')

    def test_photo_upload(self):
        photo = SimpleUploadedFile('me.png', png_bytes(), content_type='image/png')
        resp = self.post(picture=photo)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Profile.objects.get(user=self.user).picture.name.startswith('profile_pics/'))

    def test_non_image_is_refused(self):
        resp = self.post(picture=SimpleUploadedFile('me.png', b'not an image', content_type='image/png'))
        self.assertContains(resp, 'Upload a JPG, PNG or WebP photo under 5 MB.')

    def test_oversized_photo_is_refused(self):
        with patch.object(launch, 'MAX_PHOTO_BYTES', 10):
            resp = self.post(picture=SimpleUploadedFile('me.png', png_bytes(), content_type='image/png'))
        self.assertContains(resp, 'under 5 MB')
        self.assertFalse(Profile.objects.filter(user=self.user).exclude(picture='').exclude(picture=None).exists())

    def test_arabic(self):
        self.assertContains(self.client.get(reverse('arabic_launch_personal')), 'مونتير فيديو')
        resp = self.post(arabic=True)
        self.assertRedirects(resp, reverse('arabic_launch') + '?done=personal', fetch_redirect_response=False)
        resp = self.post(arabic=True, fullname='')
        self.assertContains(resp, 'اكتب اسمك.')

    def test_top_bar_shows_the_xp_earned_so_far(self):
        self.assertContains(self.client.get(reverse('launch_personal')), '0/100 XP')
        self.complete('personal', 'project')
        self.assertContains(self.client.get(reverse('launch_personal')), '60/100 XP')  # re-editing a done step

    def test_last_step_label(self):
        self.complete('project', 'theme', 'skills')
        self.assertContains(self.client.get(reverse('launch_personal')), 'Save &amp; reach 100 XP')


# ---------------------------------------------------------------------------
# Step 2: first video
# ---------------------------------------------------------------------------

@patch('core.oembed.download_thumbnail', return_value=None)
class ProjectStepTests(LaunchTestCase):
    def post(self, *urls, arabic=False):
        data = {'url': list(urls), 'title': [''] * len(urls), 'video_type': ['long'] * len(urls)}
        return self.client.post(reverse('arabic_launch_project' if arabic else 'launch_project'), data)

    def test_page(self, _thumb):
        resp = self.client.get(reverse('launch_project'))
        self.assertContains(resp, 'Add your best video')
        self.assertContains(resp, 'Step 2 of 4')
        self.assertContains(resp, '+35 XP')
        self.assertContains(resp, reverse('welcome_preview_link'))

    def test_a_link_becomes_a_project(self, _thumb):
        with patch('core.oembed.fetch', return_value=meta()), self.captureOnCommitCallbacks(execute=True):
            resp = self.post(YT)
        self.assertRedirects(resp, reverse('launch') + '?done=project', fetch_redirect_response=False)
        project = Project.objects.get(user=self.user)
        self.assertEqual(project.title, 'Great Edit')
        self.assertEqual(events('project_created').get().props['source'], 'launch')

    def test_no_link_and_no_videos(self, _thumb):
        resp = self.post('')
        self.assertContains(resp, 'Paste at least one video link.')
        self.assertFalse(Project.objects.filter(user=self.user).exists())

    def test_continue_with_videos_already_added(self, _thumb):
        self.complete('project')
        self.assertContains(self.client.get(reverse('launch_project')), 'Already in your portfolio')
        resp = self.post('')
        self.assertRedirects(resp, reverse('launch'), fetch_redirect_response=False)

    def test_private_video_is_refused(self, _thumb):
        with patch('core.oembed.fetch', return_value=meta(ok=False, error='private')):
            resp = self.post(YT)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'This video is private')
        self.assertFalse(Project.objects.filter(user=self.user).exists())

    def test_arabic(self, _thumb):
        with patch('core.oembed.fetch', return_value=meta()):
            resp = self.post(YT, arabic=True)
        self.assertRedirects(resp, reverse('arabic_launch') + '?done=project', fetch_redirect_response=False)

    def test_reel_is_the_default_format(self, _thumb):
        resp = self.client.get(reverse('launch_project'))
        self.assertContains(resp, 'name="video_type" value="reel"')
        self.assertNotContains(resp, 'name="video_type" value="long"')
        html = resp.content.decode()
        self.assertLess(html.index('data-type-btn="reel"'), html.index('data-type-btn="long"'), 'Reel comes first')
        self.assertContains(resp, 'enctype="multipart/form-data"')
        self.assertContains(resp, 'data-thumb-add')

    def test_the_chosen_format_is_saved(self, _thumb):
        with patch('core.oembed.fetch', return_value=meta()):
            self.client.post(reverse('launch_project'), {'url': YT, 'title': 'Cut', 'video_type': 'reel'})
        self.assertEqual(Project.objects.get(user=self.user).video_type, 'reel')  # even though the lookup said long


class ProjectThumbnailTests(TempMediaMixin, LaunchTestCase):
    def post(self, files=None, urls=(YT,), titles=('My cut',)):
        data = {'url': list(urls), 'title': list(titles), 'video_type': ['reel'] * len(urls)}
        data.update(files or {})
        with patch('core.oembed.fetch', side_effect=lambda url: meta(url=url)):
            return self.client.post(reverse('launch_project'), data)

    def png(self, name='mine.png', fmt='PNG', content_type='image/png'):
        return SimpleUploadedFile(name, png_bytes(fmt=fmt), content_type=content_type)

    @patch('core.oembed.download_thumbnail')
    def test_own_thumbnail_wins_over_the_looked_up_one(self, download):
        resp = self.post({'thumbnail_0': self.png()})
        self.assertRedirects(resp, reverse('launch') + '?done=project', fetch_redirect_response=False)
        image = Project.objects.get(user=self.user).image.name
        self.assertTrue(image.startswith('projects/thumb_') and image.endswith('.png'), image)
        download.assert_not_called()

    @patch('core.oembed.download_thumbnail', return_value=None)
    def test_thumbnails_follow_their_row(self, _download):
        other = 'https://vimeo.com/76979871'
        self.post({'thumbnail_1': self.png(fmt='JPEG', name='second.jpg', content_type='image/jpeg')},
                  urls=(YT, other), titles=('First', 'Second'))
        first, second = Project.objects.filter(user=self.user).order_by('id')
        self.assertFalse(first.image)
        self.assertTrue(second.image.name.endswith('.jpg'), second.image.name)

    @patch('core.oembed.download_thumbnail', return_value=None)
    def test_a_bad_thumbnail_saves_nothing_and_says_so(self, _download):
        resp = self.post({'thumbnail_0': SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'That thumbnail is not a JPG, PNG or WebP image under 5 MB.')
        self.assertContains(resp, 'value="My cut"')  # the row is kept so they can fix it
        self.assertFalse(Project.objects.filter(user=self.user).exists())

    def test_clean_thumbnail(self):
        self.assertIsNone(launch.clean_thumbnail(None))
        self.assertIsNone(launch.clean_thumbnail(SimpleUploadedFile('x.png', b'')))
        self.assertIsNone(launch.clean_thumbnail(SimpleUploadedFile('x.gif', png_bytes(fmt='GIF'))))  # format from the bytes
        self.assertIsNone(launch.clean_thumbnail(SimpleUploadedFile('x.jpg', b'GIF89a not really')))
        with patch.object(launch, 'MAX_PHOTO_BYTES', 10):
            self.assertIsNone(launch.clean_thumbnail(self.png()))
        renamed = launch.clean_thumbnail(SimpleUploadedFile('../../evil.php.png', png_bytes(fmt='WEBP')))
        self.assertRegex(renamed.name, r'^thumb_[0-9a-f]{12}\.webp$')

    def test_only_known_rows_are_read(self):
        thumbnails, bad = launch.posted_thumbnails({'thumbnail_7': self.png(), 'avatar': self.png()}, limit=3)
        self.assertEqual((thumbnails, bad), ({}, set()))


# ---------------------------------------------------------------------------
# Step 3: theme (the existing themes gallery)
# ---------------------------------------------------------------------------

class ThemeStepTests(LaunchTestCase):
    def pick(self, name='Pro', url='themes'):
        return self.client.post(reverse(url), {'theme': self.themes[name].pk})

    def test_gallery_shows_the_step(self):
        resp = self.client.get(reverse('themes'))
        self.assertContains(resp, 'Back to checklist')
        self.assertContains(resp, 'Step 3 of 4')
        self.assertContains(resp, '+15 XP')
        self.assertContains(self.client.get(reverse('arabic_themes')), 'الخطوة 3 من 4')

    def test_picking_returns_to_the_checklist(self):
        resp = self.pick()
        self.assertRedirects(resp, reverse('launch') + '?done=theme', fetch_redirect_response=False)
        self.assertTrue(self.account().launch_theme_picked)
        self.assertEqual(Profile.objects.get(user=self.user).theme, self.themes['Pro'])

    def test_arabic(self):
        self.assertRedirects(self.pick(url='arabic_themes'), reverse('arabic_launch') + '?done=theme',
                             fetch_redirect_response=False)

    def test_picking_the_default_theme_still_counts(self):
        Profile.objects.create(user=self.user, theme=self.themes['Creative'])
        self.pick('Creative')
        self.assertTrue(self.account().launch_theme_picked)

    def test_users_outside_the_flow_keep_the_old_redirects(self):
        self.set_status('done')
        self.assertRedirects(self.pick(), reverse('builder'), fetch_redirect_response=False)
        self.assertNotContains(self.client.get(reverse('themes')), 'Back to checklist')


# ---------------------------------------------------------------------------
# Step 4: skills, and the end of the flow
# ---------------------------------------------------------------------------

class SkillsStepTests(LaunchTestCase):
    def post(self, skills=(), custom='', arabic=False):
        return self.client.post(reverse('arabic_launch_skills' if arabic else 'launch_skills'),
                                {'skills': list(skills), 'custom_skills': custom})

    def names(self):
        return list(Skill.objects.filter(user=self.user).order_by('id').values_list('name', flat=True))

    def test_page(self):
        resp = self.client.get(reverse('launch_skills'))
        self.assertContains(resp, 'DaVinci Resolve')
        self.assertContains(resp, 'Color grading')
        self.assertContains(resp, 'Step 4 of 4')
        self.assertContains(resp, '+25 XP')

    def test_saves_picked_and_custom_skills(self):
        resp = self.post(['Adobe Premiere Pro', 'Color grading', 'color grading '], custom='Topaz Video AI, ')
        self.assertRedirects(resp, reverse('launch') + '?done=skills', fetch_redirect_response=False)
        self.assertEqual(self.names(), ['Adobe Premiere Pro', 'Color grading', 'Topaz Video AI'])

    def test_needs_one(self):
        resp = self.post()
        self.assertContains(resp, 'Pick at least one skill.')

    def test_sync_keeps_rows_that_stay(self):
        keep = Skill.objects.create(user=self.user, name='CapCut')
        Skill.objects.create(user=self.user, name='Old skill')
        self.post(['CapCut', 'Blender'])
        self.assertEqual(self.names(), ['CapCut', 'Blender'])
        self.assertTrue(Skill.objects.filter(pk=keep.pk).exists())

    def test_existing_skills_are_preselected_including_custom_ones(self):
        Skill.objects.create(user=self.user, name='تصحيح الألوان')  # saved from the Arabic page
        Skill.objects.create(user=self.user, name='Topaz Video AI')
        groups, extras = launch.skill_groups(['تصحيح الألوان', 'Topaz Video AI'])
        craft = next(g for g in groups if g['key'] == 'craft')
        chip = next(c for c in craft['chips'] if c['label'] == 'Color grading')
        self.assertTrue(chip['checked'])
        self.assertEqual(chip['value'], 'تصحيح الألوان')  # kept as saved, not duplicated
        self.assertEqual([e['value'] for e in extras], ['Topaz Video AI'])

    def test_skill_names_are_capped(self):
        names = launch.clean_skill_names([f'Skill {i}' for i in range(40)] + ['x' * 200])
        self.assertEqual(len(names), launch.MAX_SKILLS)
        self.assertEqual(launch.clean_skill_names(['x' * 200])[0], 'x' * launch.MAX_SKILL_LENGTH)

    def test_last_step_reaches_100_xp_and_finishes(self):
        self.complete('personal', 'project', 'theme')
        page = self.client.get(reverse('launch_skills'))
        self.assertContains(page, 'Save &amp; reach 100 XP')
        self.assertContains(page, '75/100 XP')
        resp = self.post(['CapCut'])
        self.assertRedirects(resp, reverse('launch') + '?done=skills', fetch_redirect_response=False)
        self.assertEqual(self.account().launch_status, 'done')
        self.assertEqual(events('launch_finished').count(), 1)
        props = events('launch_step_completed').get().props
        self.assertEqual((props['step'], props['xp']), ('skills', 25))
        checklist = self.client.get(resp.url)
        self.assertTrue(checklist.context['celebrate_ready'])
        self.assertContains(checklist, "100 XP! You're ready.")
        self.assertContains(checklist, 'View my portfolio')
        # ...and the dashboard no longer sends them back.
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_arabic_last_step(self):
        self.complete('personal', 'project', 'theme')
        resp = self.post(['CapCut'], arabic=True)
        self.assertRedirects(resp, reverse('arabic_launch') + '?done=skills', fetch_redirect_response=False)
        self.assertContains(self.client.get(resp.url), 'أنت جاهز')


# ---------------------------------------------------------------------------
# The celebration on the user's own portfolio
# ---------------------------------------------------------------------------

class LaunchedBarTests(LaunchTestCase):
    def setUp(self):
        super().setUp()
        self.complete('personal', 'project', 'theme', 'skills')
        self.set_status('done')
        Profile.objects.update_or_create(user=self.user, defaults={'theme': self.themes['Creative']})

    def test_owner_sees_the_bar_with_100_xp_and_the_dashboard_button(self):
        resp = self.client.get('/sara/?launched=1')
        self.assertContains(resp, 'id="sfl-bar"')
        self.assertContains(resp, 'This is your portfolio, Sara.')
        self.assertContains(resp, '100 XP')
        self.assertContains(resp, 'Go to my dashboard')
        self.assertContains(resp, 'href="%s"' % reverse('dashboard'))
        self.assertContains(resp, reverse('payment') + '?ra=live')
        self.assertEqual(events('reveal_viewed').get().props['via'], 'launch')

    def test_arabic(self):
        resp = self.client.get('/sara/?launched=1&lang=ar')
        self.assertContains(resp, 'dir="rtl"')
        self.assertContains(resp, 'هذا معرض أعمالك يا Sara')
        self.assertContains(resp, 'href="%s"' % reverse('arabic_dashboard'))

    def test_live_portfolio_variant(self):
        give_payment(self.user)
        Profile.objects.filter(user=self.user).update(is_public=True)
        resp = self.client.get('/sara/?launched=1')
        self.assertContains(resp, 'Live at')
        self.assertNotContains(resp, 'Publish it')

    def test_first_name_is_escaped(self):
        CustomUser.objects.filter(pk=self.user.pk).update(first_name='<img src=x onerror=alert(1)>')
        resp = self.client.get('/sara/?launched=1')
        self.assertNotContains(resp, '<img src=x onerror=alert(1)>')

    def test_nobody_else_sees_it(self):
        give_payment(self.user)
        Profile.objects.filter(user=self.user).update(is_public=True)
        self.client.force_login(make_editor('other'))
        resp = self.client.get('/sara/?launched=1')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'sfl-bar')
        self.client.logout()
        self.assertNotContains(self.client.get('/sara/?launched=1'), 'sfl-bar')

    def test_plain_portfolio_has_no_bar(self):
        self.assertNotContains(self.client.get('/sara/'), 'sfl-bar')
