"""Rebuilt sign-up / sign-in / verify pages (EN + AR): rendering, friendlier errors, safer sign-in."""
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import EmailOTP, Profile, Review
from core.testing_helpers import clear_cache, seed_themes, site_settings

User = get_user_model()
FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


class AuthPageTestCase(TestCase):
    def setUp(self):
        clear_cache()
        seed_themes()
        site_settings()


@FAST_HASH
class SignupPageTests(AuthPageTestCase):
    def test_page_has_the_live_link_check_and_preview(self):
        resp = self.client.get(reverse('signup'))
        self.assertContains(resp, 'data-check-url="%s"' % reverse('check_username'))
        self.assertContains(resp, 'data-preview-handle')
        self.assertContains(resp, 'name="full_name"')
        self.assertNotContains(resp, 'name="password2"')
        self.assertContains(resp, reverse('client_signup'))   # route clients to their own signup
        self.assertNotContains(resp, 'id="mobile-menu"')      # focused page: no site navigation

    def test_claimed_handle_becomes_the_heading(self):
        resp = self.client.get(reverse('signup'), {'username': 'sara-edits'})
        self.assertContains(resp, 'skillifly.cloud/<b>sara-edits</b>')

    def test_panel_shows_real_numbers_and_a_featured_review(self):
        User.objects.create_user('one', 'one@example.com', None)
        Profile.objects.get_or_create(user=User.objects.get(username='one'))
        Review.objects.create(user_name='Mona', user_title='Colorist', rating=5, is_featured=True,
                              content='Clients finally see my reels the way I cut them. Booked two jobs in a week.')
        resp = self.client.get(reverse('signup'))
        self.assertEqual(resp.context['auth_count'], 0)   # too few to brag about
        self.assertNotContains(resp, 'professionals getting hired')
        self.assertContains(resp, 'Booked two jobs in a week.')
        User.objects.bulk_create([User(username=f'u{i}', email=f'u{i}@example.com') for i in range(60)])
        Profile.objects.bulk_create([Profile(user=u) for u in User.objects.filter(username__startswith='u')
                                     if not Profile.objects.filter(user=u).exists()])
        resp = self.client.get(reverse('signup'))
        self.assertEqual(resp.context['auth_count'], Profile.objects.count())
        self.assertContains(resp, 'professionals getting hired')
        self.assertContains(resp, '★★★★★')

    def test_existing_email_gets_a_friendly_message_and_a_sign_in_link(self):
        User.objects.create_user('taken', 'Sara@Example.com', 'Str0ng-pass-99')
        resp = self.client.post(reverse('signup'), {
            'full_name': 'Sara Ali', 'username': 'sara-new', 'email': 'sara@example.com', 'password1': 'Str0ng-pass-99',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'An account with this email already exists.')
        self.assertContains(resp, '%s?login=sara%%40example.com' % reverse('signin'))
        self.assertFalse(User.objects.filter(username='sara-new').exists())

    def test_messages_render_once_inside_the_card(self):
        resp = self.client.get(reverse('signup'))
        self.assertNotContains(resp, 'max-w-7xl mx-auto px-6 pt-4')   # the base layout's message strip is off


@FAST_HASH
class ArabicSignupTests(AuthPageTestCase):
    def post(self, **data):
        base = {'full_name': 'سارة علي', 'username': 'sara-ar', 'email': 'sara@example.com', 'password1': 'Str0ng-pass-99'}
        base.update(data)
        return self.client.post(reverse('arabic_signup'), base)

    def test_django_password_messages_are_in_arabic(self):
        resp = self.post(password1='12345678')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'This password is too common')
        self.assertContains(resp, 'شائعة')   # "كلمة المرور هذه شائعة جدًا."

    def test_project_messages_are_in_arabic(self):
        User.objects.create_user('taken', 'sara@example.com', 'Str0ng-pass-99')
        resp = self.post(full_name='')
        self.assertContains(resp, 'من فضلك اكتب اسمك.')
        self.assertContains(resp, 'يوجد حساب بهذا البريد الإلكتروني بالفعل.')
        self.assertContains(resp, '%s?login=' % reverse('arabic_signin'))
        self.assertNotContains(resp, 'Please enter your name.')

    def test_valid_post_still_creates_the_account(self):
        resp = self.post()
        self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username='sara-ar').exists())


@FAST_HASH
class SigninTests(AuthPageTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('sara', 'Sara@Example.com', 'Str0ng-pass-99')

    def test_email_sign_in_ignores_case(self):
        resp = self.client.post(reverse('signin'), {'username': 'sara@example.com', 'password': 'Str0ng-pass-99', 'remember': 'on'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_wrong_password_shows_a_friendly_error_and_keeps_the_identifier(self):
        resp = self.client.post(reverse('signin'), {'username': 'sara', 'password': 'nope'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "don't match")
        self.assertContains(resp, reverse('account_reset_password'))
        self.assertContains(resp, 'value="sara"')

    def test_arabic_wrong_password_error_is_arabic(self):
        resp = self.client.post(reverse('arabic_signin'), {'username': 'sara', 'password': 'nope'})
        self.assertContains(resp, 'لا يطابق كلمة المرور')

    def test_keep_me_signed_in(self):
        self.client.post(reverse('signin'), {'username': 'sara', 'password': 'Str0ng-pass-99', 'remember': 'on'})
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.client.logout()
        self.client.post(reverse('signin'), {'username': 'sara', 'password': 'Str0ng-pass-99'})
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_external_next_is_ignored(self):
        resp = self.client.post(reverse('signin') + '?next=//evil.example/x',
                                {'username': 'sara', 'password': 'Str0ng-pass-99', 'remember': 'on'})
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)

    def test_local_next_is_followed(self):
        resp = self.client.post(reverse('signin') + '?next=/themes/',
                                {'username': 'sara', 'password': 'Str0ng-pass-99', 'remember': 'on'})
        self.assertRedirects(resp, '/themes/', fetch_redirect_response=False)

    def test_login_param_prefills_the_identifier(self):
        resp = self.client.get(reverse('signin'), {'login': 'sara@example.com'})
        self.assertContains(resp, 'value="sara@example.com"')


@FAST_HASH
class UnverifiedSigninTests(AuthPageTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user('pending', 'pending@example.com', 'Str0ng-pass-99', is_active=False)

    def test_wrong_password_does_not_open_the_verify_page(self):
        resp = self.client.post(reverse('signin'), {'username': 'pending', 'password': 'wrong'})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('verification_user_id', self.client.session)

    def test_right_password_goes_to_verify_with_a_fresh_code(self):
        resp = self.client.post(reverse('signin'), {'username': 'pending@example.com', 'password': 'Str0ng-pass-99'})
        self.assertRedirects(resp, reverse('verify_otp'), fetch_redirect_response=False)
        self.assertTrue(EmailOTP.objects.filter(user=self.user).exists())
        self.assertEqual(len(mail.outbox), 1)

    def test_verify_page(self):
        self.client.post(reverse('signin'), {'username': 'pending', 'password': 'Str0ng-pass-99'})
        resp = self.client.get(reverse('verify_otp'))
        self.assertContains(resp, 'pending@example.com')
        self.assertContains(resp, 'data-otp')
        self.assertContains(resp, 'autocomplete="one-time-code"')
        self.assertContains(resp, '%d minutes' % EmailOTP.LIFETIME_MINUTES)

    def test_verify_error_is_shown_once(self):
        self.client.post(reverse('signin'), {'username': 'pending', 'password': 'Str0ng-pass-99'})
        resp = self.client.post(reverse('verify_otp'), {'otp': '000000'})
        self.assertContains(resp, 'Check the latest email and try again', count=1)
