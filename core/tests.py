from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from urllib.parse import quote
from core.models import UserPayment, Subscription, Profile, Review, UserAccount
from django.utils import timezone
from datetime import timedelta
import json
import re

User = get_user_model()

class AdminDashboardTests(TestCase):
    def setUp(self):
        # Create a superuser
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='adminpassword'
        )
        
        # Create normal users with different signup dates
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='userpass'
        )
        # We can backdate using update because date_joined is in AbstractUser
        User.objects.filter(id=self.user1.id).update(
            date_joined=timezone.make_aware(timezone.datetime(2026, 6, 1, 10, 0, 0))
        )
        
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='userpass'
        )
        User.objects.filter(id=self.user2.id).update(
            date_joined=timezone.make_aware(timezone.datetime(2026, 6, 15, 12, 0, 0))
        )
        
        # Create a Subscription
        self.sub = Subscription.objects.create(
            name='Pro Plan',
            duration=1,
            days=30
        )
        
        # Create UserPayments
        # 1. Paid payment (will be summed in total_spent because status='paid')
        self.payment1 = UserPayment.objects.create(
            user=self.user1,
            subscription=self.sub,
            amount=150.00,
            status='paid'
        )
        UserPayment.objects.filter(id=self.payment1.id).update(
            date=timezone.make_aware(timezone.datetime(2026, 6, 5, 14, 0, 0))
        )
        
        # 2. Unpaid/Pending payment (should NOT be summed in total_spent)
        self.payment2 = UserPayment.objects.create(
            user=self.user1,
            subscription=self.sub,
            amount=150.00,
            status='pending'
        )
        UserPayment.objects.filter(id=self.payment2.id).update(
            date=timezone.make_aware(timezone.datetime(2026, 6, 6, 15, 0, 0))
        )

    def test_admin_dashboard_access_superuser(self):
        self.client.login(username='admin', password='adminpassword')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_admin_dashboard_access_denied_for_normal_user(self):
        self.client.login(username='user1', password='userpass')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 302) # Redirect to login or admin checks

    def test_admin_dashboard_stats_and_charts(self):
        self.client.login(username='admin', password='adminpassword')
        
        # Test range covering the dates
        response = self.client.get(reverse('admin_dashboard'), {
            'start_date': '2026-06-01',
            'end_date': '2026-06-30',
            'period': 'day'
        })
        self.assertEqual(response.status_code, 200)
        
        # Context checks
        self.assertEqual(response.context['total_users'], 2)
        self.assertEqual(response.context['total_paid_users'], 1)
        self.assertEqual(response.context['total_revenue'], 150.00)
        
        # Verify users list annotation (total_spent)
        users = list(response.context['users_list'])
        user1_obj = next(u for u in users if u.username == 'user1')
        user2_obj = next(u for u in users if u.username == 'user2')
        
        # User 1 spent 150 (the pending payment is excluded)
        self.assertEqual(user1_obj.total_spent, 150.00)
        # User 2 spent 0 / None
        self.assertEqual(user2_obj.total_spent, None)

        # Check chart values JSON
        signup_values = json.loads(response.context['signup_values'])
        paid_values = json.loads(response.context['paid_values'])
        
        # June 1 should show 1 signup
        # June 15 should show 1 signup
        # June 5 should show 1 payment
        # June 6 should show 0 payments (since payment2 is pending)
        self.assertEqual(sum(signup_values), 2)
        self.assertEqual(sum(paid_values), 1)


class ClientReviewImageFallbackTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='editor', email='editor@example.com', password='pass')
        self.client_user = User.objects.create_user(
            username='client1',
            email='client1@example.com',
            password='pass',
            first_name='Sara',
        )
        self.profile = Profile.objects.create(user=self.client_user)

    def test_client_review_sets_reviewer(self):
        self.client.login(username='client1', password='pass')
        response = self.client.post(reverse('client_review', args=['editor']), {
            'user_name': 'Sara',
            'content': 'Loved it!',
            'rating': 5,
        })
        self.assertEqual(response.status_code, 200)
        review = Review.objects.get(user=self.owner)
        self.assertEqual(review.reviewer, self.client_user)
        self.assertFalse(review.is_featured)

    def test_review_image_url_prefers_user_image(self):
        review = Review.objects.create(
            user=self.owner,
            reviewer=self.client_user,
            user_name='Sara',
            content='Great',
            rating=5,
            user_image=SimpleUploadedFile('review.png', b'fakeimage'),
        )
        self.assertEqual(review.image_url, review.user_image.url)

    def test_review_image_url_falls_back_to_reviewer_profile_picture(self):
        self.profile.picture = SimpleUploadedFile('pic.png', b'fakeimage')
        self.profile.save()
        review = Review.objects.create(
            user=self.owner,
            reviewer=self.client_user,
            user_name='Sara',
            content='Great',
            rating=5,
        )
        self.assertEqual(review.image_url, self.profile.picture.url)

    def test_review_image_url_none_without_images(self):
        review = Review.objects.create(
            user=self.owner,
            reviewer=self.client_user,
            user_name='Sara',
            content='Great',
            rating=5,
        )
        self.assertIsNone(review.image_url)


class ClientReviewRedirectFunnelTests(TestCase):
    """Anonymous reviewers on the review page must be funneled through client
    signup and bounced back to the review page after signing up."""

    def setUp(self):
        self.owner = User.objects.create_user(username='reviewowner', email='reviewowner@example.com', password='pass')

    def test_anonymous_review_redirects_to_client_signup_with_next(self):
        response = self.client.get(reverse('client_review', args=['reviewowner']))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/signup/client/?next=', response.url)
        self.assertIn('/review/reviewowner/', response.url)

    def test_anonymous_arabic_review_redirects_to_arabic_client_signup_with_next(self):
        response = self.client.get(reverse('arabic_client_review', args=['reviewowner']))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/ar/signup/client/?next=', response.url)
        self.assertIn('/ar/review/reviewowner/', response.url)

    def test_client_lands_back_on_review_page_after_signing_up(self):
        signup_url = reverse('client_signup') + '?next=' + quote('/review/reviewowner/')
        response = self.client.post(signup_url, {
            'name': 'Review Client',
            'email': 'reviewclient@example.com',
            'password': 'reviewpass123',
            'next': '/review/reviewowner/',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/review/reviewowner/')
        review_page = self.client.get(response.url)
        self.assertEqual(review_page.status_code, 200)

    def test_arabic_client_lands_back_on_arabic_review_page_after_signing_up(self):
        signup_url = reverse('arabic_client_signup') + '?next=' + quote('/ar/review/reviewowner/')
        response = self.client.post(signup_url, {
            'name': 'عميل',
            'email': 'reviewclient@example.com',
            'password': 'reviewpass123',
            'next': '/ar/review/reviewowner/',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/ar/review/reviewowner/')
        review_page = self.client.get(response.url)
        self.assertEqual(review_page.status_code, 200)

    def test_auth_pages_render_with_next_preserved_in_google_forms(self):
        for url in [
            reverse('client_signup') + '?next=/review/reviewowner/',
            reverse('arabic_client_signup') + '?next=/ar/review/reviewowner/',
            reverse('editor_signup') + '?next=/review/reviewowner/',
            reverse('arabic_editor_signup') + '?next=/ar/review/reviewowner/',
            reverse('signin') + '?next=/review/reviewowner/',
            reverse('arabic_signin') + '?next=/ar/review/reviewowner/',
        ]:
            response = self.client.get(url, follow=True)
            self.assertEqual(response.status_code, 200, msg=f'{url} did not render')
            self.assertContains(response, '/accounts/google/login/', msg_prefix=f'{url}: ')
            self.assertContains(response, 'reviewowner', msg_prefix=f'{url}: ')


    def test_matching_language_cookie_keeps_reviewer_on_same_page(self):
        reviewer = User.objects.create_user(username='langclient', email='langclient@example.com', password='pass')
        self.client.force_login(reviewer)
        self.client.cookies['skillifly_lang'] = 'ar'
        response = self.client.get(reverse('arabic_client_review', args=['reviewowner']))
        self.assertEqual(response.status_code, 200)
        self.client.cookies['skillifly_lang'] = 'en'
        response = self.client.get(reverse('client_review', args=['reviewowner']))
        self.assertEqual(response.status_code, 200)

    def test_language_cookie_switches_review_page_to_arabic_twin(self):
        self.client.cookies['skillifly_lang'] = 'ar'
        response = self.client.get(reverse('client_review', args=['reviewowner']))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/ar/review/reviewowner/')

    def test_language_cookie_switches_arabic_review_page_to_english_twin(self):
        self.client.cookies['skillifly_lang'] = 'en'
        response = self.client.get(reverse('arabic_client_review', args=['reviewowner']))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/review/reviewowner/')

    def test_stale_csrf_token_redirects_back_to_review_form_instead_of_403(self):
        reviewer = User.objects.create_user(username='csrfclient', email='csrfclient@example.com', password='pass')
        client = Client(enforce_csrf_checks=True)
        client.force_login(reviewer)

        page = client.get(reverse('client_review', args=['reviewowner']))
        match = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())
        self.assertIsNotNone(match)
        valid_token = match.group(1)

        stale_token = 'invalid-stale-token'
        response = client.post(
            reverse('client_review', args=['reviewowner']),
            {
                'user_name': 'Stale Client',
                'content': 'Should bounce back to the form.',
                'rating': 5,
                'csrfmiddlewaretoken': stale_token,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/review/reviewowner/')
        self.assertNotEqual(valid_token, stale_token)


    def test_full_anonymous_review_flow_submits_without_csrf_error(self):
        response = self.client.get(reverse('client_review', args=['reviewowner']), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(reverse('client_signup'), response.redirect_chain[0][0])

        response = self.client.post(
            reverse('client_signup') + '?next=' + quote('/review/reviewowner/'),
            {
                'name': 'Full Flow Client',
                'email': 'fullflow@example.com',
                'password': 'fullflowpass123',
                'next': '/review/reviewowner/',
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], '/review/reviewowner/')

        response = self.client.post(
            reverse('client_review', args=['reviewowner']),
            {
                'user_name': 'Full Flow Client',
                'user_title': 'Producer',
                'content': 'Great work, loved the turnaround time.',
                'rating': 5,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Thank')
        self.assertEqual(Review.objects.filter(user=self.owner, reviewer__email='fullflow@example.com').count(), 1)


class ClientDashboardRoutingTests(TestCase):
    def setUp(self):
        self.client_user = User.objects.create_user(
            username='clientdash',
            email='clientdash@example.com',
            password='pass12345'
        )
        UserAccount.objects.create(user=self.client_user, account_type='client')
        self.editor = User.objects.create_user(
            username='editorx',
            email='editorx@example.com',
            password='pass12345'
        )
        Review.objects.create(
            user=self.editor,
            reviewer=self.client_user,
            user_name='Client Dash',
            content='Very good work',
            rating=5,
        )

    def test_dashboard_redirects_client_to_client_dashboard(self):
        self.client.login(username='clientdash', password='pass12345')
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, reverse('client_dashboard'))

    def test_arabic_dashboard_redirects_client_to_arabic_client_dashboard(self):
        self.client.login(username='clientdash', password='pass12345')
        response = self.client.get(reverse('arabic_dashboard'))
        self.assertRedirects(response, reverse('arabic_client_dashboard'))

    def test_client_dashboard_shows_hiring_and_reviews_cards(self):
        self.client.login(username='clientdash', password='pass12345')
        response = self.client.get(reverse('client_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hire Exceptional Talent')
        self.assertContains(response, 'Own Your Review Presence')

    def test_arabic_client_dashboard_renders_with_warm_arabic_style(self):
        self.client.login(username='clientdash', password='pass12345')
        response = self.client.get(reverse('arabic_client_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مركز تحكم العميل')
        self.assertContains(response, 'وظّف مواهب استثنائية')
        self.assertContains(response, 'أدر حضورك بالتقييمات')
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'إجمالي التقييمات')

    def test_arabic_client_dashboard_blocks_editors(self):
        self.client.login(username='editorx', password='pass12345')
        response = self.client.get(reverse('arabic_client_dashboard'))
        self.assertRedirects(response, reverse('arabic_dashboard'))

    def test_language_cookie_switches_client_dashboard_to_arabic_twin(self):
        self.client.login(username='clientdash', password='pass12345')
        self.client.cookies['skillifly_lang'] = 'ar'
        response = self.client.get(reverse('client_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('arabic_client_dashboard'))

    def test_language_cookie_switches_arabic_client_dashboard_to_english_twin(self):
        self.client.login(username='clientdash', password='pass12345')
        self.client.cookies['skillifly_lang'] = 'en'
        response = self.client.get(reverse('arabic_client_dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('client_dashboard'))

    def test_client_reviews_page_lists_submitted_reviews(self):
        self.client.login(username='clientdash', password='pass12345')
        response = self.client.get(reverse('client_reviews'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '@editorx')
        self.assertContains(response, 'Very good work')
        self.assertContains(response, reverse('preview', kwargs={'username': 'editorx'}))

    def test_arabic_client_reviews_page_lists_submitted_reviews(self):
        self.client.login(username='clientdash', password='pass12345')
        response = self.client.get(reverse('arabic_client_reviews'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '@editorx')
        self.assertContains(response, 'Very good work')

    def test_language_cookie_switches_client_reviews_to_arabic_twin(self):
        self.client.login(username='clientdash', password='pass12345')
        self.client.cookies['skillifly_lang'] = 'ar'
        response = self.client.get(reverse('client_reviews'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('arabic_client_reviews'))

    def test_language_cookie_switches_arabic_client_reviews_to_english_twin(self):
        self.client.login(username='clientdash', password='pass12345')
        self.client.cookies['skillifly_lang'] = 'en'
        response = self.client.get(reverse('arabic_client_reviews'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('client_reviews'))


class ReviewsManagementAvatarTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username='avowner',
            email='avowner@example.com',
            password='pass12345'
        )
        self.other = User.objects.create_user(
            username='avother',
            email='avother@example.com',
            password='pass12345'
        )
        self.review = Review.objects.create(
            user=self.owner,
            user_name='Happy Client',
            content='Great work!',
            rating=5,
        )

    def _png(self, name='avatar.png'):
        import base64
        png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGM8YVPBgA0wYRUdtBIALU8BjAnZpn0AAAAASUVORK5CYII='
        )
        return SimpleUploadedFile(name, png, content_type='image/png')

    def test_reviews_management_page_offers_add_avatar(self):
        self.client.login(username='avowner', password='pass12345')
        response = self.client.get(reverse('reviews_management'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add avatar')

    def test_owner_can_upload_review_avatar(self):
        self.client.login(username='avowner', password='pass12345')
        response = self.client.post(
            reverse('update_review_avatar', args=[self.review.id]),
            {'user_image': self._png()},
            follow=True
        )
        self.review.refresh_from_db()
        self.assertIsNotNone(self.review.user_image)
        self.assertRedirects(response, reverse('reviews_management'))

    def test_non_owner_cannot_upload_avatar(self):
        self.client.login(username='avother', password='pass12345')
        response = self.client.post(
            reverse('update_review_avatar', args=[self.review.id]),
            {'user_image': self._png()},
        )
        self.assertEqual(response.status_code, 404)
        self.review.refresh_from_db()
        self.assertFalse(bool(self.review.user_image))

    def test_invalid_image_is_rejected(self):
        self.client.login(username='avowner', password='pass12345')
        bad = SimpleUploadedFile('notanimage.txt', b'this is not an image', content_type='text/plain')
        response = self.client.post(
            reverse('update_review_avatar', args=[self.review.id]),
            {'user_image': bad},
        )
        self.review.refresh_from_db()
        self.assertFalse(bool(self.review.user_image))
        self.assertEqual(response.status_code, 302)
