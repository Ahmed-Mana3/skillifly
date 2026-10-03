from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from urllib.parse import quote
from core.models import UserPayment, Subscription, Profile, Review, ClientReview, UserAccount, School, CustomDomain, PersonalInfo
from django.utils import timezone
from datetime import timedelta
import json
import re
from unittest.mock import patch

from core.theme_colors import (
    ACCENT_INK_MIN_CONTRAST, SLOT_GLOW, SLOT_INK, SLOT_PARTNER, SLOT_PRIMARY,
    SLOT_SOFT, SLOT_TRIO,
)

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
        review = ClientReview.objects.get(user=self.owner)
        self.assertEqual(review.reviewer, self.client_user)
        self.assertFalse(review.is_featured)

    def test_review_image_url_prefers_user_image(self):
        review = ClientReview.objects.create(
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
        review = ClientReview.objects.create(
            user=self.owner,
            reviewer=self.client_user,
            user_name='Sara',
            content='Great',
            rating=5,
        )
        self.assertEqual(review.image_url, self.profile.picture.url)

    def test_review_image_url_none_without_images(self):
        review = ClientReview.objects.create(
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
        self.assertEqual(ClientReview.objects.filter(user=self.owner, reviewer__email='fullflow@example.com').count(), 1)


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
        ClientReview.objects.create(
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
        self.review = ClientReview.objects.create(
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


class ProjectOrderTests(TestCase):
    """Project order: reorder page renders and the AJAX save endpoint works."""

    def setUp(self):
        from core.models import Project
        self.user = User.objects.create_user(
            username='punkeditor',
            email='punk@example.com',
            password='pass12345',
        )
        self.other = User.objects.create_user(
            username='othereditor',
            email='other@example.com',
            password='pass12345',
        )
        self.p1 = Project.objects.create(user=self.user, title="Project Alpha", video_type="long")
        self.p2 = Project.objects.create(user=self.user, title="Project Beta", video_type="reel")
        self.p3 = Project.objects.create(user=self.user, title="Project Gamma", video_type="long")
        self.foreign = Project.objects.create(user=self.other, title="Their Project")

    def test_page_requires_login(self):
        response = self.client.get(reverse('customize_project_order'))
        self.assertEqual(response.status_code, 302)

    def test_arabic_page_requires_login(self):
        response = self.client.get(reverse('arabic_customize_project_order'))
        self.assertEqual(response.status_code, 302)

    def test_page_renders_projects_in_display_order(self):
        self.client.login(username='punkeditor', password='pass12345')
        response = self.client.get(reverse('customize_project_order'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(reverse('customize_project_order_save'), html)
        self.assertIn('id="projList"', html)
        self.assertLess(html.index('Project Alpha'), html.index('Project Beta'))

    def test_arabic_page_renders(self):
        self.client.login(username='punkeditor', password='pass12345')
        response = self.client.get(reverse('arabic_customize_project_order'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'id="projList"')
        self.assertContains(response, 'المشاريع')

    def test_save_persists_order(self):
        self.client.login(username='punkeditor', password='pass12345')
        response = self.client.post(
            reverse('customize_project_order_save'),
            data=json.dumps({"order": [self.p3.id, self.p1.id, self.p2.id]}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)

        from core.models import Project
        ordered = list(Project.objects.filter(user=self.user).order_by('order', 'id').values_list('id', flat=True))
        self.assertEqual(ordered, [self.p3.id, self.p1.id, self.p2.id])

    def test_save_rejects_foreign_ids(self):
        self.client.login(username='punkeditor', password='pass12345')
        response = self.client.post(
            reverse('customize_project_order_save'),
            data=json.dumps({"order": [self.p1.id, self.foreign.id]}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

        from core.models import Project
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.order, 0)

    def test_save_rejects_invalid_json(self):
        self.client.login(username='punkeditor', password='pass12345')
        response = self.client.post(
            reverse('customize_project_order_save'),
            data='not-json',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_save_rejects_missing_order_list(self):
        self.client.login(username='punkeditor', password='pass12345')
        response = self.client.post(
            reverse('customize_project_order_save'),
            data=json.dumps({"order": "nope"}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)

    def test_save_requires_login(self):
        response = self.client.post(
            reverse('customize_project_order_save'),
            data=json.dumps({"order": []}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 302)

    def test_default_display_order_is_oldest_first(self):
        from core.models import Project
        ordered = list(Project.objects.filter(user=self.user).values_list('id', flat=True))
        self.assertEqual(ordered, [self.p1.id, self.p2.id, self.p3.id])


class CrawlerFilesTests(TestCase):
    """Crawler-facing files: sitemap.xml, robots.txt and llms.txt."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='mapme',
            email='mapme@example.com',
            password='pass12345',
        )
        Profile.objects.create(user=self.user, is_public=True)
        self.school = School.objects.create(
            name='Map High',
            slug='map-high',
            discount_code='MAPHIGH',
        )

    def test_llms_txt_is_served(self):
        response = self.client.get('/llms.txt')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/plain', response['Content-Type'])
        self.assertIn(b'# Skillifly', response.content)
        self.assertIn(b'https://skillifly.cloud/payment/', response.content)

    def test_sitemap_lists_marketing_pages_schools_and_profiles(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        xml = response.content.decode()
        self.assertIn('xmlns:xhtml', xml)
        self.assertIn('/ar/', xml)
        self.assertIn('hreflang="ar"', xml)
        self.assertIn('hreflang="x-default"', xml)
        self.assertIn('/school/map-high/', xml)
        self.assertIn('/@mapme/', xml)

    def test_sitemap_has_no_fabricated_static_lastmod(self):
        response = self.client.get('/sitemap.xml')
        self.assertNotContains(response, '<lastmod>2024-01-01</lastmod>')

    def test_robots_blocks_private_areas_and_lists_blog_sitemap(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for rule in (
            'Disallow: /admin/',
            'Disallow: /manage/',
            'Disallow: /ar/dashboard/',
            'Disallow: /client_dashboard/',
            'Disallow: /*/reels/',
        ):
            self.assertIn(rule, body)
        self.assertIn('Sitemap: https://blog.skillifly.cloud/sitemap.xml', body)

    def test_custom_domain_robots_and_sitemap_are_self_contained(self):
        CustomDomain.objects.create(user=self.user, domain='mapme.design', is_active=True)

        robots = self.client.get('/robots.txt', HTTP_HOST='mapme.design')
        self.assertEqual(robots.status_code, 200)
        body = robots.content.decode()
        self.assertIn('Disallow: /reels/', body)
        self.assertIn('Disallow: /admin/', body)
        self.assertNotIn('blog.skillifly.cloud', body)

        sitemap = self.client.get('/sitemap.xml', HTTP_HOST='mapme.design')
        self.assertEqual(sitemap.status_code, 200)
        xml = sitemap.content.decode()
        self.assertIn('http://mapme.design/</loc>', xml)
        self.assertNotIn('/signup/', xml)

class SkilliflyAIServiceTests(TestCase):
    """Tests for the grounded AI copy-writing service (core/ai.py)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="ai_editor",
            email="ai@example.com",
            password="securepassword1",
        )
        PersonalInfo.objects.create(
            user=self.user,
            full_name="AI Editor",
            title="Commercial Video Editor",
            email="ai@example.com",
            phone="",
            bio="",
        )

    def _add_project(self):
        from core.models import Project
        return Project.objects.create(
            user=self.user,
            title="Nike Spot 2026",
            url="https://youtu.be/abc123",
            video_type="long",
            details="Brand commercial cut in Premiere Pro.",
        )

    def test_write_bio_falls_back_to_template_without_llm(self):
        from core.ai import write_bio
        with patch.dict("os.environ", {"GROQ_API_KEY": "your_groq_api_key", "GEMINI_API_KEY": "your_gemini_api_key"}, clear=False):
            bio = write_bio(self.user, language="en", years=5, apps="Premiere Pro", specialty="Commercials", extra="")
        self.assertIn("Commercials Video Editor", bio)
        self.assertIn("5+ years", bio)

    def test_write_bio_uses_llm_when_available_and_grounded(self):
        from core.ai import write_bio
        self._add_project()
        with patch.dict("os.environ",
                        {"GROQ_API_KEY": "gsk_FakeValidKey12345678901234567890",
                         "GEMINI_API_KEY": "your_gemini_api_key"}, clear=False):
            with patch("core.ai.GenerationService._call_groq", return_value="An AI-grounding bio."):
                bio = write_bio(self.user, language="en", years=5, apps="Premiere Pro", specialty="Commercials", extra="")
        self.assertEqual(bio, "An AI-grounding bio.")

    def test_write_project_details_fallback(self):
        from core.models import Project
        from core.ai import write_project_details
        project = self._add_project()
        with patch.dict("os.environ",
                        {"GROQ_API_KEY": "your_groq_api_key",
                         "GEMINI_API_KEY": "your_gemini_api_key"}, clear=False):
            text = write_project_details(self.user, project, language="en")
        self.assertIn("Nike Spot 2026", text)

    def test_portfolio_payload_is_grounded_in_real_data(self):
        from core.ai import portfolio_payload
        from core.models import Skill
        self._add_project()
        Skill.objects.create(user=self.user, name="DaVinci Resolve")
        payload = portfolio_payload(self.user)
        self.assertEqual(payload["reels"], 0)
        self.assertEqual(payload["long_videos"], 1)
        self.assertEqual(payload["skills"], ["DaVinci Resolve"])
        self.assertEqual(payload["projects"][0]["title"], "Nike Spot 2026")


class ThemeBackgroundColorTests(TestCase):
    """Background colour: every Video Editor theme accepts one, and the derived
    palette keeps the page readable on both dark and light picks."""

    def setUp(self):
        from core.models import Category, Theme
        self.category = Category.objects.create(name="Video Editor")
        self.developer_category = Category.objects.create(name="Developer")
        self.minimal = Theme.objects.create(name="Minimal", category=self.category)
        self.animated = Theme.objects.create(name="Animated Dark", category=self.category)
        self.cyan = Theme.objects.create(name="Cyan", category=self.category)
        self.editorial = Theme.objects.create(name="Editorial Studio", category=self.category)
        self.classic = Theme.objects.create(name="Classic", category=self.developer_category)
        self.developer = Theme.objects.create(name="Minimal", category=self.developer_category)
        self.user = User.objects.create_user(
            username='bgeditor', email='bg@example.com', password='pass12345',
        )
        self.profile = Profile.objects.create(user=self.user, theme=self.minimal)
        self.client.login(username='bgeditor', password='pass12345')

    def _switch_theme(self, theme):
        self.profile.theme = theme
        self.profile.save()

    def test_every_video_editor_theme_is_supported(self):
        from core.models import Theme
        from core.theme_colors import background_color_supported
        for theme in Theme.objects.filter(category=self.category):
            with self.subTest(theme=theme.name):
                self.assertTrue(background_color_supported('video_editor', theme.name))

    def test_other_categories_are_not_supported(self):
        from core.theme_colors import background_color_supported
        self.assertTrue(background_color_supported('video_editor', self.minimal.name))
        self.assertTrue(background_color_supported('developer', self.classic.name))
        # Only Classic ships the override block inside the Developer category, so
        # its siblings have to stay locked.
        self.assertFalse(background_color_supported('developer', self.developer.name))
        self.assertFalse(background_color_supported('student', 'Classic Scholar'))
        self.assertFalse(background_color_supported('video_editor', 'Aperture'))
        self.assertFalse(background_color_supported('developer', 'Aperture'))

    def test_page_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('customize_theme_background')).status_code, 302)
        self.assertEqual(self.client.get(reverse('arabic_customize_theme_background')).status_code, 302)

    def test_editor_renders_for_every_video_editor_theme(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS
        for category, theme_slug in sorted(THEME_BACKGROUND_SPECS):
            theme = type(self.minimal)(
                name=theme_slug.replace('_', ' ').title(),
                category=self.category if category == 'video_editor' else self.developer_category,
            )
            theme.save()
            with self.subTest(theme=theme.name):
                self._switch_theme(theme)
                response = self.client.get(reverse('customize_theme_background'))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'id="bgc-swatches"')
                self.assertContains(response, 'id="bgc-preview"')
                self.assertContains(response, reverse('customize_theme_background_save'))

    def test_arabic_page_renders_editor(self):
        response = self.client.get(reverse('arabic_customize_theme_background'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'id="bgc-swatches"')

    def test_page_explains_itself_for_unsupported_theme(self):
        self._switch_theme(self.developer)
        response = self.client.get(reverse('customize_theme_background'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="bgc-swatches"')
        self.assertContains(response, reverse('themes'))

    def test_customize_page_marks_the_card_locked_when_unsupported(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS
        self._switch_theme(self.developer)
        response = self.client.get(reverse('customize_theme'))
        # The card names how many themes can do this, straight out of the
        # registry, so the copy can never drift from the gate.
        self.assertContains(response, 'themes that support it')
        self.assertContains(response, str(len(THEME_BACKGROUND_SPECS)))
        self.assertContains(response, reverse('customize_theme_background'))

    def test_customize_page_card_is_active_for_video_editor_themes(self):
        for theme in (self.minimal, self.animated, self.cyan, self.editorial):
            with self.subTest(theme=theme.name):
                self._switch_theme(theme)
                response = self.client.get(reverse('customize_theme'))
                self.assertContains(response, 'Change colours')
                self.assertNotContains(response, 'Video Editor themes')

    def test_customize_page_card_is_active_for_developer_classic(self):
        self._switch_theme(self.classic)
        response = self.client.get(reverse('customize_theme'))
        self.assertContains(response, 'Change colours')
        self.assertContains(response, 'Pick a colour')
        self.assertNotContains(response, 'themes that support it')

    def test_arabic_customize_page_renders_the_card(self):
        response = self.client.get(reverse('arabic_customize_theme'))
        self.assertContains(response, 'تغيير الألوان')
        self.assertContains(response, reverse('arabic_customize_theme_background'))

    def test_editor_offers_each_theme_own_default_first(self):
        from core.theme_colors import presets_for
        response = self.client.get(reverse('customize_theme_background'))
        self.assertContains(response, 'data-hex="%s"' % presets_for('video_editor', 'Minimal')[0]['value'])
        self._switch_theme(self.editorial)
        response = self.client.get(reverse('customize_theme_background'))
        self.assertContains(response, 'data-hex="#F5F0E8"')

    def test_editor_previews_the_theme_own_accent(self):
        self._switch_theme(self.animated)
        response = self.client.get(reverse('customize_theme_background'))
        self.assertContains(response, '--sf-accent: #00C9FF')

    def test_save_persists_a_valid_colour(self):
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'background': '#2b1055'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertFalse(response.json()['reset'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {'background': '#2B1055'})

    def test_save_works_for_every_video_editor_theme(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS
        for category, theme_slug in sorted(THEME_BACKGROUND_SPECS):
            theme = type(self.minimal)(
                name=theme_slug.replace('_', ' ').title(),
                category=self.category if category == 'video_editor' else self.developer_category,
            )
            theme.save()
            with self.subTest(theme=theme.name):
                self._switch_theme(theme)
                self.profile.theme_settings = {}
                self.profile.save()
                response = self.client.post(
                    reverse('customize_theme_background_save'),
                    data={'background': '#123456'},
                )
                self.assertTrue(response.json()['success'], theme.name)
                self.profile.refresh_from_db()
                self.assertEqual(self.profile.theme_settings, {'background': '#123456'})

    def test_save_accepts_shorthand_hex(self):
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'background': '#fff'},
        )
        self.assertTrue(response.json()['success'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {'background': '#FFFFFF'})

    def test_save_rejects_garbage_and_translucent_values(self):
        for value in ('', 'red', '#12345', '#0A0E27AA', 'javascript:alert(1)'):
            response = self.client.post(
                reverse('customize_theme_background_save'),
                data={'background': value},
            )
            self.assertEqual(response.status_code, 400, value)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_save_is_refused_for_unsupported_theme(self):
        self._switch_theme(self.developer)
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'background': '#2B1055'},
        )
        self.assertEqual(response.status_code, 400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_save_requires_login(self):
        self.client.logout()
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'background': '#2B1055'},
        )
        self.assertEqual(response.status_code, 302)

    def test_picking_the_theme_own_background_is_treated_as_a_reset(self):
        """Storing the shipped background would flatten layered backgrounds
        (the editorial gradient, the neo-brutalist dot grid) for no gain."""
        self.profile.theme_settings = {'background': '#2B1055'}
        self.profile.save()
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'background': '#0a0e27'},
        )
        self.assertTrue(response.json()['success'])
        self.assertTrue(response.json()['reset'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_reset_returns_this_theme_own_default(self):
        self.profile.theme_settings = {'background': '#2B1055'}
        self.profile.save()
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'reset': '1'},
        )
        self.assertTrue(response.json()['reset'])
        self.assertEqual(response.json()['background'], '#0A0E27')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

        self._switch_theme(self.editorial)
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'reset': '1'},
        )
        self.assertEqual(response.json()['background'], '#F5F0E8')

    def test_portfolio_emits_nothing_when_untouched(self):
        from core.theme_colors import resolve_background_palette
        self.assertFalse(resolve_background_palette(self.profile)['custom'])

    def test_portfolio_receives_the_derived_palette(self):
        from core.theme_colors import resolve_background_palette
        self.profile.theme_settings = {'background': '#F4F2ED'}
        self.profile.save()
        resolved = resolve_background_palette(self.profile)
        self.assertTrue(resolved['custom'])
        self.assertEqual(resolved['background'], '#F4F2ED')
        self.assertFalse(resolved['palette']['dark'])

    def test_saved_colour_is_ignored_once_the_theme_changes(self):
        from core.theme_colors import resolve_background_palette
        self.profile.theme_settings = {'background': '#2B1055'}
        self.profile.save()
        self._switch_theme(self.developer)
        self.assertFalse(resolve_background_palette(self.profile)['custom'])

    def test_saved_colour_survives_a_switch_between_video_editor_themes(self):
        """One colour is stored per profile, so switching themes within the
        category must not silently drop the user's pick."""
        from core.theme_colors import resolve_background_palette
        self.profile.theme_settings = {'background': '#2B1055'}
        self.profile.save()
        self._switch_theme(self.animated)
        resolved = resolve_background_palette(self.profile)
        self.assertTrue(resolved['custom'])
        self.assertEqual(resolved['background'], '#2B1055')
        self.assertEqual(resolved['family'], 'glass')

    def test_resolve_reports_the_family_that_matches_each_theme(self):
        from core.theme_colors import resolve_background_palette
        expected = {
            self.minimal: 'minimal',
            self.editorial: 'paper',
            self.cyan: 'brutal',
            self.animated: 'glass',
        }
        for theme, family in expected.items():
            with self.subTest(theme=theme.name):
                self._switch_theme(theme)
                self.assertEqual(resolve_background_palette(self.profile)['family'], family)


class ThemeBackgroundCssTests(TestCase):
    """The override block every enabled theme's public template must ship."""

    INCLUDE = 'portfolios/common/theme_background_css.html'

    def _render_include(self, custom, background='#2B1055', family='surface',
                        accent_custom=False, accent='#FF006E', tokens=None,
                        channels=None):
        from django.template.loader import render_to_string
        from core.theme_colors import (
            SLOT_PRIMARY, accent_channel_vars, derive_accent_palette,
            derive_palette,
        )
        accent_palette = derive_accent_palette(accent, background, adjust=True)
        return render_to_string(self.INCLUDE, {
            'theme_background': {
                'custom': custom,
                'accent_custom': accent_custom,
                'family': family,
                'background': background,
                'accent': accent,
                'accent_tokens': tokens if tokens is not None else {
                    SLOT_PRIMARY: ('--accent',),
                },
                'accent_channel_vars': (
                    accent_channel_vars('video_editor', 'creative', accent_palette)
                    if channels is None else channels
                ),
                'palette': derive_palette(background),
                'accent_palette': accent_palette,
            },
        })

    def test_every_enabled_theme_template_includes_the_override(self):
        """The feature gate in core.theme_colors promises these templates honour
        a saved colour. This is the guard on that promise."""
        from django.template import TemplateDoesNotExist
        from django.template.loader import get_template
        from core.theme_colors import THEME_BACKGROUND_SPECS

        for (category, theme_slug) in sorted(THEME_BACKGROUND_SPECS):
            base = 'portfolios/{0}/{0}_{1}'.format(category, theme_slug)
            checked = 0
            for suffix in ('.html', '_long.html', '_reels.html', '_detail.html', '_category.html'):
                name = base + suffix
                try:
                    source = get_template(name).template.source
                except TemplateDoesNotExist:
                    continue
                checked += 1
                with self.subTest(template=name):
                    self.assertIn(self.INCLUDE, source)
            # Every enabled theme must resolve to at least one real template,
            # otherwise the gate would promise colour on a page that cannot
            # render it (a Developer fallback, for instance).
            self.assertGreater(checked, 0, base)

    def test_override_is_silent_when_nothing_is_saved(self):
        self.assertEqual(self._render_include(False).strip(), '')

    def test_override_emits_the_derived_tokens(self):
        html = self._render_include(True, '#2B1055')
        self.assertIn('--sf-bg: #2B1055;', html)
        self.assertIn('--sf-text: #FFFFFF;', html)
        self.assertIn('background: var(--sf-bg) !important;', html)

    def test_override_flips_text_for_a_light_background(self):
        html = self._render_include(True, '#F4F2ED')
        self.assertIn('--sf-text: #0A0E27;', html)
        self.assertNotIn('--sf-text: #FFFFFF;', html)

    def test_every_token_is_a_css_literal(self):
        """A Python tuple leaking into a declaration (as the hero midpoint once
        did) is invalid CSS that browsers silently drop — assert on shape."""
        html = self._render_include(True, '#0A0E27', family='minimal')
        declarations = re.findall(r'(--sf-[\w-]+):\s*([^;]+);', html)
        self.assertTrue(declarations)
        for token, value in declarations:
            with self.subTest(token=token, value=value):
                self.assertFalse(value.strip().startswith('('), value)
                self.assertTrue(
                    re.fullmatch(r'#[0-9A-Fa-f]{6}|rgba\(\d{1,3}, \d{1,3}, \d{1,3}, [\d.]+\)',
                                 value.strip()),
                    '%s: %s' % (token, value),
                )

    def test_surface_family_bridges_the_common_token_names(self):
        html = self._render_include(True, '#101820', family='surface')
        for declaration in ('--bg:', '--surface:', '--glass:', '--border:', '--text:', '--text-dim:'):
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, html)

    def test_minimal_family_bridges_its_own_token_names(self):
        html = self._render_include(True, '#101820', family='minimal')
        self.assertIn('--bg-dark: var(--sf-ink);', html)
        self.assertIn('--bg-card: var(--sf-surface);', html)
        self.assertIn('--text-primary: var(--sf-text);', html)
        self.assertIn('.hero h1', html)

    def test_paper_family_bridges_the_editorial_token_names(self):
        html = self._render_include(True, '#F5F0E8', family='paper')
        self.assertIn('--paper: var(--sf-bg);', html)
        self.assertIn('--ink: var(--sf-hard-ink);', html)
        self.assertIn('--line: var(--sf-border);', html)

    def test_brutal_family_travels_the_accent_with_the_hard_ink(self):
        """Cyan/Yellow/Monochrome use black for their accent as well as their
        borders, so a dark pick would otherwise leave their headings invisible."""
        html = self._render_include(True, '#00E5FF', family='brutal')
        self.assertIn('--accent: var(--sf-hard-ink);', html)
        self.assertIn('--border: var(--sf-hard-ink);', html)
        self.assertIn('--shadow-color: var(--sf-hard-ink);', html)
        self.assertIn('--shadow-lg: 12px 12px 0px var(--sf-hard-ink);', html)
        self.assertIn('color: var(--sf-hard-ink) !important;', html)

    def test_other_families_keep_their_own_accent(self):
        """A theme's accent is its brand — a background-only override must not
        repaint it, or the portfolio stops looking like the theme the user picked."""
        for family in ('surface', 'minimal', 'paper'):
                with self.subTest(family=family):
                    html = self._render_include(True, '#00E5FF', family=family)
                    self.assertNotIn('--sf-accent', html)
                    self.assertNotIn('--accent:', html)

    def test_glass_family_repoints_the_chrome_written_as_literals(self):
        """Animated/Animated Dark hardcode their navbar, hero type and creator
        chips as dark-mode literals. Bridging tokens alone leaves white hero
        text and a dark navbar floating on a light page, so every one of those
        literals has to be re-pointed — this is the regression guard for that.
        """
        for background in ('#101820', '#F5F0E8'):
            html = self._render_include(True, background, family='glass')
            with self.subTest(background=background):
                for declaration in (
                    '.navbar {',
                    'background: var(--sf-nav) !important;',
                    '.nav-links a,',
                    '.hero-title { color: var(--sf-text) !important; }',
                    '.hero-bio {',
                    'color: var(--sf-text-muted) !important;',
                    '.hero-avatar { border-color: var(--sf-hard-ink) !important; }',
                    '.hero::before {',
                    'var(--sf-hero-veil)',
                    '.creators-marquee-container {',
                    '.creator-bubble {',
                    '.creator-label-name { color: var(--sf-text) !important; }',
                    '.review-card:hover { background: var(--sf-surface-2) !important; }',
                    '.top-nav {',
                    '.action-btn {',
                    '.reel-desc { color: var(--sf-text) !important; }',
                    '.reels-container { background: var(--sf-bg) !important; }',
                    '.thumbnail-wrapper { background: var(--sf-surface-2) !important; }',
                    'var(--sf-shadow)',
                ):
                    self.assertIn(declaration, html)

    def test_glass_family_never_leaves_a_bare_white_or_hero_rule(self):
        """The two rules that actually made the page unreadable on a light pick."""
        html = self._render_include(True, '#F5F0E8', family='glass')
        self.assertNotIn('color: #fff', html)
        self.assertNotIn('color: #f2f4f7', html)
        self.assertNotIn('color: #e5e7eb', html)

    def test_glass_branch_covers_creatives_translucent_white_chrome(self):
        """Creative is a dark theme, so a light pick leaves a forest of
        near-white glass chips and near-white labels behind. Each one is a
        literal in the theme's own CSS and has to be re-pointed individually.
        """
        for background in ('#F5F0E8', '#101820'):
            html = self._render_include(True, background, family='glass')
            with self.subTest(background=background):
                for declaration in (
                    '.drive-fs-btn,',
                    '.drive-progress-wrap,',
                    '.nav-sep,',
                    '.swipe-hint-arrow span,',
                    '.progress-dots .dot {',
                    '.drive-btn:hover,',
                    '.drive-fs-btn:hover { background: var(--sf-surface-2) !important; }',
                    '.drive-time { color: var(--sf-text-muted) !important; }',
                    '.swipe-hint-label { color: var(--sf-text-faint) !important; }',
                    '.tap-ring {',
                    '.close-btn { background: var(--sf-overlay) !important; }',
                    '.project-thumb-placeholder,',
                    '.related-thumb-placeholder { background: var(--sf-surface-2) !important; }',
                    '.review-stars svg.empty { fill: var(--sf-border-strong) !important; }',
                    '.drive-progress-thumb { background: var(--sf-text) !important; }',
                    '.shimmer-ring { border-color: var(--sf-border-strong) !important; }',
                    '.slide-counter { color: var(--sf-text-muted) !important; }',
                    '.video-wrapper { border-color: var(--sf-border) !important; }',
                    '.hero::after {',
                    'linear-gradient(var(--sf-grid) 1px, transparent 1px)',
                ):
                    self.assertIn(declaration, html)

    def test_glass_branch_never_repaints_a_photo_scrim(self):
        """.play-overlay is a gradient scrim over a video still, dimming the
        image under white text. Flattening it to a solid fill would be a
        regression on the Animated long pages, so it must stay untouched."""
        html = self._render_include(True, '#F5F0E8', family='glass')
        self.assertNotIn('.play-overlay {', html)
        self.assertNotIn('background: var(--sf-overlay) !important;\n  }', html.split('.play-overlay')[0][-40:])

    def test_glass_branch_cannot_reach_the_brand_accent_dot(self):
        """`.dot` on its own would also match Creative White's `.nav-brand .dot`,
        greying out a deliberately accent-coloured brand marker."""
        html = self._render_include(True, '#F5F0E8', family='glass')
        self.assertIn('.progress-dots .dot {', html)
        for declaration in re.findall(r'(?:^|\n)\s*(\.dot[^\n{]*)\{', html):
            with self.subTest(selector=declaration.strip()):
                self.assertNotEqual(declaration.strip(), '.dot')

    def test_scrim_class_is_opt_in_and_present_in_the_template(self):
        """`header` is deliberately not used as a selector: the Animated long
        pages author a header with no background, and a blanket override would
        add a bar to them. The one element that needs it opts in."""
        from django.template.loader import get_template
        source = get_template(
            'portfolios/video_editor/video_editor_creative_long.html').template.source
        self.assertIn('<header class="sf-scrim">', source)
        for name in ('video_editor_animated_long.html',
                     'video_editor_animated_dark_long.html'):
            with self.subTest(template=name):
                other = get_template('portfolios/video_editor/' + name).template.source
                self.assertNotIn('sf-scrim', other)

    def test_creative_is_registered_as_glass(self):
        from core.theme_colors import FAMILY_GLASS, THEME_BACKGROUND_SPECS
        spec = THEME_BACKGROUND_SPECS[('video_editor', 'creative')]
        self.assertEqual(spec['family'], FAMILY_GLASS)
        self.assertEqual(spec['default'], '#04040A')

    def _creative_sources(self):
        from django.template import TemplateDoesNotExist
        from django.template.loader import get_template
        sources = {}
        for suffix in ('.html', '_long.html', '_reels.html', '_detail.html'):
            name = 'portfolios/video_editor/video_editor_creative' + suffix
            try:
                sources[name] = get_template(name).template.source
            except TemplateDoesNotExist:
                continue
        self.assertGreaterEqual(len(sources), 4, sources.keys())
        return sources

    def test_no_creative_template_hardcodes_its_own_brand_colours(self):
        """The regression this whole mechanism exists to prevent.

        Creative fades its brand colour with rgba(255, 61, 107, .08) in roughly
        forty places. A custom property cannot reach a literal, so a literal
        accent means recolouring the page relabels every heading and button
        while every hover wash, card glow and pill fill stays rose. Each of the
        three brand colours may only be spelled in the :root declarations, which
        are the shipped defaults the override restates.
        """
        from core.theme_colors import THEME_BACKGROUND_SPECS
        spec = THEME_BACKGROUND_SPECS[('video_editor', 'creative')]
        literals = [spec['accent'], spec['gradient'][1], spec['gradient'][2]]
        declaration = re.compile(
            r'^\s*--(?:accent|accent2|gold|accent-rgb|accent2-rgb|gold-rgb):')
        for name, source in sorted(self._creative_sources().items()):
            self.assertTrue(
                any(declaration.match(line)
                    for line in source.splitlines()),
                '%s declares no brand-colour tokens at all' % name,
            )
            # Inline scripts are excluded on purpose: canvas cannot resolve
            # var(), so the avatar placeholders read the tokens back off :root
            # and keep the shipped hex as a last-resort fallback.
            css = re.sub(r'<script\b.*?</script>', '', source, flags=re.S)
            body = '\n'.join(line for line in css.splitlines()
                             if not declaration.match(line))
            for literal in literals:
                with self.subTest(template=name, literal=literal):
                    self.assertNotIn(
                        literal.lower(), body.lower(),
                        '%s must read --accent/--accent2/--gold, not %s'
                        % (name, literal),
                    )

    def test_creative_templates_define_the_channels_the_registry_overrides(self):
        """The bridge restates these properties on :root. If a creative
        template uses rgba(var(--accent-rgb), ...) without defining the channel
        itself, the page still renders as shipped but every one of those fades
        silently resolves to nothing."""
        from core.theme_colors import accent_channels
        for name, source in sorted(self._creative_sources().items()):
            for _slot, properties in accent_channels(
                'video_editor', 'creative'
            ).items():
                for prop in properties:
                    # Not every sub-page uses every tone, so require the channel
                    # only where the token it belongs to is also declared.
                    with self.subTest(template=name, token=prop):
                        uses = re.search(
                            r'var\(\s*%s\s*,' % re.escape(prop), source)
                        if not uses:
                            continue
                        self.assertIn(
                            '%s:' % prop, source,
                            '%s uses var(%s, ...) but never defines it' % (name, prop),
                        )

    def test_creative_labels_on_accent_fills_read_the_on_accent_ink(self):
        """White text on a filled accent is unreadable the moment the accent is
        pale. --sf-accent-ink is only defined when the accent was customised, so
        the templates carry it as a var() with #fff as the shipped fallback.

        Every #fff the creative stylesheets still declare is on something that is
        not an accent fill (the cursor dot, a marquee label on the page
        background); this asserts none of them are inside an accent rule.
        """
        for name, source in sorted(self._creative_sources().items()):
            head = source[:source.index('</head>')]
            for line in head.splitlines():
                if not re.search(r'color:\s*#fff\b', line):
                    continue
                with self.subTest(template=name, line=line.strip()):
                    self.fail(
                        '%s declares a bare #fff label (%s); a filled accent '
                        'needs var(--sf-accent-ink, #fff)'
                        % (name, line.strip())
                    )

    def test_glass_branch_covers_creative_whites_luminance_literals(self):
        """Creative White is a light theme, so it fails in the opposite
        direction: a dark pick leaves a cream navbar bar, an invisible hero
        outline and an unreadable amber badge. Each needs its own override -
        reusing the Animated fixes alone would not catch any of them.
        """
        for background in ('#101820', '#F5F0E8'):
            html = self._render_include(True, background, family='glass')
            with self.subTest(background=background):
                self.assertIn('.navbar {', html)
                self.assertIn('background: var(--sf-nav) !important;', html)
                self.assertIn('.hero-title .outline-text {', html)
                self.assertIn('-webkit-text-stroke-color: var(--sf-text-muted) !important;', html)
                self.assertIn('.badge-long { color: var(--sf-hard-ink) !important; }', html)

    def test_outline_text_stroke_follows_the_background(self):
        """The stroke is the only thing visible on an outline-text line, so it
        has to be re-derived from the background rather than left navy."""
        from core.theme_colors import contrast_ratio, derive_palette, parse_hex_color
        for background in ('#101820', '#F5F0E8', '#FFFFFF', '#FFE600'):
            with self.subTest(background=background):
                palette = derive_palette(background)
                bg = parse_hex_color(palette['background'])
                stroke = parse_hex_color(palette['text_muted'])
                # Outline text is large display type, so AA Large (3:1) is the
                # bar — not the 4.5:1 body-text rule.
                self.assertGreaterEqual(contrast_ratio(stroke, bg), 3.0, background)

    def test_creative_white_is_registered_as_glass(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS, FAMILY_GLASS
        spec = THEME_BACKGROUND_SPECS[('video_editor', 'creative_white')]
        self.assertEqual(spec['family'], FAMILY_GLASS)
        self.assertEqual(spec['default'], '#F8F7F4')

    def test_hero_veil_disappears_on_a_light_pick(self):

        """A dark ellipse over dark-on-light type is the ugliest failure mode,
        so on a light background the veil is dropped outright, not recoloured."""
        from core.theme_colors import derive_palette
        self.assertEqual(derive_palette('#F5F0E8')['hero_veil'], 'transparent')
        self.assertNotEqual(derive_palette('#0A0A0A')['hero_veil'], 'transparent')
        self.assertEqual(
            self._render_include(True, '#F5F0E8', family='glass').count('--sf-hero-veil: transparent;'),
            1,
        )

    def test_shadow_follows_the_polarity(self):
        """A black smear under light cards is worse than no shadow at all."""
        from core.theme_colors import derive_palette
        self.assertEqual(derive_palette('#F5F0E8')['shadow'], 'rgba(15, 23, 42, 0.12)')
        self.assertEqual(derive_palette('#0A0A0A')['shadow'], 'rgba(0, 0, 0, 0.5)')


    def test_unknown_family_still_repaints_the_body(self):
        html = self._render_include(True, '#101820', family='something_new')
        self.assertIn('--sf-bg: #101820;', html)
        self.assertIn('background: var(--sf-bg) !important;', html)


class ThemeProColorOverrideTests(TestCase):
    """The Pro video-editor theme under a saved background and/or accent.

    Pro is the theme most likely to look broken by a recolour, because almost
    none of its colour is expressed as a token: it paints its section bands, its
    heading gradients, its footer scrim and every one of its brand-colour fades
    as a bare literal. A recolour therefore has to reach ~30 declarations that
    no single `--accent` override can touch, and each one has to carry the
    theme's own value as its ``var()`` fallback so an untouched Pro renders
    exactly as shipped.
    """

    TEMPLATE = 'portfolios/video_editor/video_editor_pro.html'

    def setUp(self):
        from django.template.loader import get_template
        self.source = get_template(self.TEMPLATE).template.source
        self.head = self.source[:self.source.index('</head>')]
        self.styles = self.head[self.head.index('<style>'):]
        self.body = self.source[self.source.index('</head>'):]

    def _declarations(self):
        """Yield (line, is_root_declaration, is_var_fallback) for each CSS line
        that actually paints something.

        Three kinds of line are exempt because they *are* the shipped defaults:
        a ``:root`` custom-property declaration (the override restates these),
        and any line whose only literals sit inside a ``var()`` fallback (the
        value the theme renders with until a colour is saved).
        """
        root_decl = re.compile(r'^\s*--[\w-]+\s*:')
        for line in self.styles.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(('/', '*', '}')):
                continue
            # Literals a var() carries as its fallback are inert by definition.
            outside_fallback = re.sub(r'var\([^()]*(?:\([^()]*\)[^()]*)*\)', '', line)
            yield stripped, bool(root_decl.match(line)), outside_fallback

    # ── the accent ──────────────────────────────────────────────────────────

    def test_pro_is_registered_as_surface_with_accent_channels(self):
        from core.theme_colors import (
            FAMILY_SURFACE, SLOT_PRIMARY, THEME_BACKGROUND_SPECS, accent_channels,
        )
        spec = THEME_BACKGROUND_SPECS[('video_editor', 'pro')]
        self.assertEqual(spec['family'], FAMILY_SURFACE)
        self.assertEqual(spec['default'], '#000000')
        # Without channels, recolouring the accent relabels the type while every
        # hover wash, glow and hairline stays cyan.
        self.assertEqual(
            accent_channels('video_editor', 'pro'),
            {SLOT_PRIMARY: ('--accent-rgb',)},
        )

    def test_pro_template_has_no_hardcoded_brand_colour(self):
        """Every cyan fade has to be spelled as channels.

        Pro fades its own brand colour in the hero bloom, both card hovers, the
        icon tile, three chip hovers, the review avatar rings and the footer
        hairline. A custom property cannot reach ``rgba(0, 217, 255, ...)``, so
        each of those has to write ``rgba(var(--accent-rgb), ...)`` instead.
        """
        from core.theme_colors import parse_hex_color
        channels = ', '.join(str(c) for c in parse_hex_color('#00D9FF'))
        faded = 'rgba(%s' % channels
        root_decl = re.compile(r'^\s*--[\w-]+\s*:')
        for line in self.styles.splitlines():
            if faded in line.replace('var(--accent-rgb', ''):
                with self.subTest(line=line.strip()):
                    self.fail(
                        'Pro fades its brand colour as a literal: %s'
                        % line.strip()
                    )
        # The hex itself may only be spelled as the shipped :root default, or in
        # the Skillifly wordmark — which is the platform's own gradient and is
        # deliberately not recoloured.
        for hexform in ('#00d9ff', '#00D9FF'):
            for line in self.styles.splitlines():
                if hexform not in line:
                    continue
                with self.subTest(line=line.strip()):
                    self.assertTrue(
                        root_decl.match(line)
                        or 'linear-gradient(to right,' in line,
                        'Pro spells its brand colour as a literal: %s'
                        % line.strip(),
                    )

    def test_pro_declares_the_channel_it_reads(self):
        """The bridge restates --accent-rgb on :root. A template that uses
        ``var(--accent-rgb)`` without defining it renders as shipped today and
        then silently loses every fade the moment a colour is saved."""
        self.assertIsNotNone(
            re.search(r'^\s*--accent-rgb:\s*0,\s*217,\s*255\s*;',
                      self.styles, re.MULTILINE),
            'Pro reads var(--accent-rgb) but never defines it',
        )
        self.assertGreaterEqual(
            len(re.findall(r'var\(\s*--accent-rgb\s*,', self.styles)), 10,
            'Pro should reach its brand colour through channels in every place '
            'it used to hardcode it',
        )

    # ── the background ──────────────────────────────────────────────────────

    def test_pro_section_bands_are_not_a_literal_black(self):
        """The three bands that separate Pro's sections were ``#000`` /
        ``#050505``. A light background therefore renders a black slab between
        the creators marquee and the reviews grid, and a black gradient under
        the contact block."""
        for selector in ('.creators-section', '.reviews-section', '.contact-section'):
            with self.subTest(selector=selector):
                block = self._rule(selector)
                self.assertIn('var(--sf-', block)
        self.assertIn('background: var(--sf-bg, #000);', self.styles)
        self.assertIn(
            'linear-gradient(to bottom, var(--bg), var(--sf-surface-deep, #050505))',
            self.styles,
        )

    def test_pro_heading_gradients_are_not_a_literal_white(self):
        """``background-clip: text`` leaves only the fill visible, so the white
        stop of .contact-title and .reviews-title is the whole heading. Left as
        a literal it is invisible on any light background."""
        for selector in ('.contact-title', '.reviews-title'):
            with self.subTest(selector=selector):
                block = self._rule(selector)
                self.assertIn('var(--sf-hero-mid, #fff) 0%', block)
                self.assertNotIn('linear-gradient(135deg, #fff', block)

    def test_pro_footer_scrim_follows_the_background(self):
        footer = self._rule('footer')
        self.assertIn('var(--sf-overlay, rgba(0, 0, 0, 0.9))', footer)
        self.assertIn('var(--sf-border, rgba(255, 255, 255, 0.05))', footer)

    def test_pro_filled_accent_button_label_follows_the_accent(self):
        """.contact-cta fills the page with the accent and labelled it ``#000``.
        A pale accent — which the legibility net will happily produce on a dark
        background — puts black type on near-white."""
        cta = self._rule('.contact-cta')
        self.assertIn('color: var(--sf-accent-ink, #000);', cta)
# Hover flips the fill to the page's contrast extreme, so the label has
        # to flip with it rather than keep the accent's ink.
        hover = self._rule('.contact-cta:hover')
        self.assertIn('background: var(--sf-hero-mid, #fff);', hover)
        # NOT --sf-text: that sits on the same side of the fill as the fill, so
        # a light pick would put near-black type on a near-black hover state.
        self.assertIn('color: var(--sf-surface, #000);', hover)

    def test_pro_contact_cta_hover_label_clears_aa_on_either_polarity(self):
        """The hover state inverts the fill, so its label has to invert too.
        Deriving one from the other is the only way this stays correct as
        backgrounds change — asserting the two tokens are on opposite sides of
        the page is the guard on that."""
        from core.theme_colors import (
            contrast_ratio, derive_palette, is_dark, parse_hex_color,
        )
        for background in ('#000000', '#101820', '#F4F2ED', '#FFFFFF'):
            with self.subTest(background=background):
                palette = derive_palette(background)
                fill = parse_hex_color(palette['hero_mid'])
                label = parse_hex_color(palette['surface'])
                # The fill is the bright extreme on a dark page and the dark
                # extreme on a light one; the label is the other one.
                self.assertEqual(is_dark(fill), not is_dark(label))
                self.assertGreaterEqual(
                    contrast_ratio(fill, label), ACCENT_INK_MIN_CONTRAST,
                )

    def test_pro_empty_stars_and_badge_text_are_not_white_literals(self):
        self.assertIn('fill: var(--sf-border-strong, rgba(255, 255, 255, 0.12));',
                      self.styles)
        self.assertIn('color: var(--sf-text-muted, rgba(255, 255, 255, 0.5));',
                      self.styles)
        self.assertIn('color: var(--sf-text-faint, rgba(255, 255, 255, 0.4));',
                      self.styles)

    def test_pro_has_no_inline_colour_literals_outside_the_stylesheet(self):
        """An inline style wins over the override block's rules of equal
        specificity, and no ``var()`` can be substituted into one after the
        fact. The copyright line shipped as ``style="color: rgba(255,255,255,.4)"``."""
        for style in re.findall(r'style="([^"]*)"', self.body):
            with self.subTest(style=style):
                self.assertNotRegex(style, r'rgba\(|\bcolor:\s*#')

    def test_pro_canvas_avatars_read_the_saved_colours(self):
        """Canvas cannot resolve var(). The fallback avatars used to be painted
        with literal '#111111' and '#00d9ff', so they stayed on the shipped
        palette while the page around them recoloured."""
        script = self.source[self.source.rindex('<script>'):]
        for token in ('--sf-surface', '--accent', '--sf-text'):
            with self.subTest(token=token):
                self.assertIn("sfToken('%s'" % token, script)
        self.assertNotIn("ctx.strokeStyle = '#00d9ff'", script)
        self.assertNotIn("ctx.fillStyle = '#111111'", script)

    def test_pro_card_sheen_and_band_tokens_are_emitted(self):
        """--sf-sheen and --sf-surface-deep have no shipped equivalent, so the
        stylesheet is the only place they can be defined."""
        from django.template.loader import render_to_string
        from core.theme_colors import derive_palette
        html = render_to_string(
            'portfolios/common/theme_background_css.html',
            {'theme_background': {
                'custom': True, 'accent_custom': False, 'family': 'surface',
                'accent_tokens': {}, 'accent_channel_vars': [],
                'palette': derive_palette('#2B1055'),
            }},
        )
        self.assertIn('--sf-sheen: rgba(255, 255, 255, 0.03);', html)
        self.assertRegex(html, r'--sf-surface-deep:\s*#[0-9A-F]{6};')

    def test_recessed_band_and_sheen_follow_the_polarity(self):
        """The band has to read as a band and the sheen as a sheen on either
        polarity — a black band under a white page, or no band at all, is the
        same failure."""
        from core.theme_colors import derive_palette, parse_hex_color, relative_luminance

        # Every pick but pure black gets a shade that is visibly not the page.
        for background in ('#101820', '#2B1055', '#F4F2ED', '#FFFFFF', '#0A0E27'):
            with self.subTest(background=background):
                palette = derive_palette(background)
                self.assertRegex(palette['surface_deep'], r'^#[0-9A-F]{6}$')
                self.assertNotEqual(palette['surface_deep'], palette['background'])
                # Recessed means recessed on both polarities: Pro's contact band
                # darkens as it leaves the hero, and that reads correctly as a
                # deeper cream just as it does as a deeper black.
                self.assertLess(
                    relative_luminance(parse_hex_color(palette['surface_deep'])),
                    relative_luminance(parse_hex_color(background)),
                )

        # Pure black is the one exception the theme itself sets: Pro paints its
        # creators and reviews sections #000 on a #000 page, so "no band" is the
        # faithful answer and inventing one would change the shipped design.
        self.assertEqual(derive_palette('#000000')['surface_deep'], '#000000')

        # The sheen lifts a card, so it is white on a dark page and ink on a
        # light one — a white sheen over a light card simply is not there.
        self.assertEqual(derive_palette('#000000')['sheen'], 'rgba(255, 255, 255, 0.03)')
        self.assertEqual(derive_palette('#F4F2ED')['sheen'], 'rgba(0, 0, 0, 0.03)')

    def test_untouched_pro_renders_exactly_as_shipped(self):
        """Every rewrite above swapped a literal for ``var(--token, literal)``.
        That is only safe if the fallback is byte-for-byte the value that was
        there before, so this pins each pair together."""
        for fallback in (
            'var(--sf-sheen, rgba(255, 255, 255, 0.03))',
            'var(--sf-surface-deep, #050505)',
            'var(--sf-hero-mid, #fff)',
            'var(--sf-overlay, rgba(0, 0, 0, 0.9))',
            'var(--sf-border, rgba(255, 255, 255, 0.05))',
            'var(--sf-border-strong, rgba(255, 255, 255, 0.12))',
            'var(--sf-text-muted, rgba(255, 255, 255, 0.5))',
            'var(--sf-text-faint, rgba(255, 255, 255, 0.4))',
            'var(--sf-surface, rgba(255, 255, 255, 0.02))',
            'var(--sf-accent-ink, #000)',
            'var(--accent-rgb, 0, 217, 255)',
        ):
            with self.subTest(fallback=fallback):
                self.assertIn(fallback, self.styles)

    def _rule(self, selector):
        """The body of the first rule whose selector list ends with ``selector``."""
        match = re.search(
            r'(?m)^\s*%s\s*\{([^}]*)\}' % re.escape(selector), self.styles)
        self.assertIsNotNone(match, 'no rule for %s' % selector)
        return match.group(1)


class ThemeBackgroundPageRenderTests(TestCase):
    """End-to-end: a real portfolio request for every enabled theme ships the
    override, in <head>, after the theme's own token block."""

    # Each family's tokens the override has to bridge for the theme to repaint.
    BRIDGED = {
        'surface': ['--bg:', '--surface:', '--text:', '--border:'],
        'glass': ['--bg:', '--surface:', '--text:', '--border:'],
        'minimal': ['--bg-dark:', '--bg-card:', '--text-primary:'],
        'paper': ['--paper:', '--ink:', '--line:'],
        'brutal': ['--bg:', '--border:', '--shadow-color:'],
        'classic': ['--sfc-bg:', '--sfc-surface:', '--sfc-text:', '--sfc-border:'],
    }

    # The token block that anchors each family's ordering check, and which of
    # those blocks appear in more than one branch.
    ANCHOR = {
        'surface': '--surface-hover: var(--sf-surface-2);',
        'glass': '--surface-hover: var(--sf-surface-2);',
        'minimal': '--bg-dark: var(--sf-ink);',
        'paper': '--paper: var(--sf-bg);',
        'brutal': '--shadow-color: var(--sf-hard-ink);',
        'classic': '--sfc-surface-2: var(--sf-surface-2);',
    }

    def setUp(self):
        from core.models import Category
        from portfolios.views import get_or_create_mock_user
        self.category = Category.objects.create(name="Video Editor")
        self.developer_category = Category.objects.create(name="Developer")
        # The mock user is exempt from the subscription gate, so a real
        # portfolio request renders without inventing a paid subscription.
        self.user = get_or_create_mock_user()
        self.profile = Profile.objects.get(user=self.user)
        self.profile.is_public = True
        self.profile.theme_settings = {'background': '#101820'}
        self.profile.save()

    def _theme(self, slug, category='video_editor'):
        from core.models import Theme
        name = slug.replace('_', ' ').title()
        parent = self.developer_category if category == 'developer' else self.category
        theme, _ = Theme.objects.get_or_create(name=name, category=parent)
        return theme

    def test_every_enabled_theme_renders_the_override_on_its_portfolio(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS
        for category, slug in sorted(THEME_BACKGROUND_SPECS):
            spec = THEME_BACKGROUND_SPECS[(category, slug)]
            with self.subTest(theme='%s/%s' % (category, slug)):
                self.profile.theme = self._theme(slug, category)
                self.profile.save()

                response = self.client.get('/%s/' % self.user.username)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode('utf-8')

                self.assertIn('--sf-bg: #101820;', html)
                head_end = html.lower().find('</head>')
                self.assertLess(html.find('--sf-bg:'), head_end,
                                'override must live in <head>')
                self.assertLess(
                    html.find('--sf-bg:'),
                    html.find(self.ANCHOR[spec['family']]),
                    'override must come after the theme token it replaces',
                )
                for token in self.BRIDGED[spec['family']]:
                    self.assertIn(token, html)

    def test_untouched_profile_emits_no_override_at_all(self):
        self.profile.theme = self._theme('creative')
        self.profile.theme_settings = {}
        self.profile.save()
        html = self.client.get('/%s/' % self.user.username).content.decode('utf-8')
        self.assertNotIn('--sf-bg:', html)
        self.assertNotIn('--sf-surface:', html)

    def test_sub_pages_carry_the_override_too(self):
        """The reels/long/detail pages are separate templates with their own
        :root, and some hardcode a black body for video viewing."""
        from core.theme_colors import THEME_BACKGROUND_SPECS
        username = self.user.username
        for category, slug in sorted(THEME_BACKGROUND_SPECS):
            self.profile.theme = self._theme(slug, category)
            self.profile.save()
            for path in ('reels/', 'long-videos/'):
                if not self._has_sub_page(slug, path):
                    # Classic is a single-page résumé theme; there is nothing to
                    # carry the override to.
                    continue
                with self.subTest(theme='%s/%s' % (category, slug), path=path):
                    html = self.client.get('/%s/%s' % (username, path)).content.decode('utf-8')
                    self.assertEqual(html.count('--sf-bg: #101820;'), 1, path)
                    self.assertIn('background: var(--sf-bg) !important;', html)

    @staticmethod
    def _has_sub_page(slug, path):
        from django.template import TemplateDoesNotExist
        from django.template.loader import get_template
        suffix = 'reels' if path == 'reels/' else 'long'
        name = 'portfolios/video_editor/video_editor_%s_%s.html' % (slug, suffix)
        try:
            get_template(name)
        except TemplateDoesNotExist:
            return False
        return True

    def test_a_developer_theme_never_leaks_the_override(self):
        """Minimal is a Developer theme that has not been given the override, so
        a colour saved while the user was on Classic must not leak into it."""
        from core.models import Theme
        sibling, _ = Theme.objects.get_or_create(name="Minimal", category=self.developer_category)
        self.profile.theme = sibling
        self.profile.save()
        html = self.client.get('/%s/' % self.user.username).content.decode('utf-8')
        self.assertNotIn('--sf-bg:', html)


class ThemePaletteDerivationTests(TestCase):
    """core.theme_colors.derive_palette: contrast and readability guarantees."""

    def test_dark_pick_yields_light_text(self):
        from core.theme_colors import derive_palette
        palette = derive_palette('#0A0E27')
        self.assertTrue(palette['dark'])
        self.assertEqual(palette['text'], '#FFFFFF')

    def test_light_pick_yields_dark_text(self):
        from core.theme_colors import derive_palette
        palette = derive_palette('#FFFFFF')
        self.assertFalse(palette['dark'])
        self.assertEqual(palette['text'], '#0A0E27')

    def test_body_text_always_clears_wcag_aa(self):
        from core.theme_colors import contrast_ratio, derive_palette, parse_hex_color
        for value in ('#0A0E27', '#000000', '#2B1055', '#F4F2ED', '#FFFFFF', '#7F7F7F',
                      '#00E5FF', '#FFE600', '#F5F0E8', '#F8FAFC', '#00B8D4'):
            palette = derive_palette(value)
            ratio = contrast_ratio(parse_hex_color(palette['background']),
                                  parse_hex_color(palette['text']))
            self.assertGreaterEqual(ratio, 4.5, value)

    def test_reported_contrast_matches_the_measured_ratio(self):
        from core.theme_colors import contrast_ratio, derive_palette, parse_hex_color
        for value in ('#0A0E27', '#F4F2ED', '#00E5FF', '#FFE600'):
            palette = derive_palette(value)
            measured = contrast_ratio(parse_hex_color(palette['background']),
                                      parse_hex_color(palette['text']))
            self.assertAlmostEqual(palette['contrast'], round(measured, 1), places=1)

    def test_ink_stays_dark_for_the_light_accent_gradient(self):
        from core.theme_colors import derive_palette, is_dark, parse_hex_color
        for value in ('#0A0E27', '#F4F2ED', '#FFFFFF', '#0B2B26'):
            ink = parse_hex_color(derive_palette(value)['ink'])
            self.assertTrue(is_dark(ink), value)

    def test_hard_ink_flips_with_the_background(self):
        from core.theme_colors import derive_palette, is_dark, parse_hex_color
        self.assertTrue(is_dark(parse_hex_color(derive_palette('#00E5FF')['hard_ink'])))
        self.assertFalse(is_dark(parse_hex_color(derive_palette('#0A0A0A')['hard_ink'])))

    def test_hard_ink_is_visible_against_the_background(self):
        from core.theme_colors import contrast_ratio, derive_palette, parse_hex_color
        for value in ('#00E5FF', '#FFE600', '#FFFFFF', '#0A0A0A', '#101820', '#F5F0E8'):
            palette = derive_palette(value)
            ratio = contrast_ratio(parse_hex_color(palette['background']),
                                  parse_hex_color(palette['hard_ink']))
            self.assertGreater(ratio, 7.0, value)

    def test_cards_are_never_identical_to_the_background(self):
        from core.theme_colors import derive_palette
        for value in ('#0A0E27', '#000000', '#FFFFFF', '#F4F2ED'):
            palette = derive_palette(value)
            self.assertNotEqual(palette['background'], palette['surface'], value)
            self.assertNotEqual(palette['surface'], palette['surface_2'], value)

    def test_garbage_falls_back_to_the_theme_default(self):
        from core.theme_colors import derive_palette, DEFAULT_BACKGROUND
        self.assertEqual(derive_palette('nope')['background'], DEFAULT_BACKGROUND)
        self.assertEqual(derive_palette(None)['background'], DEFAULT_BACKGROUND)

    def test_palette_values_are_all_css_safe(self):
        from core.theme_colors import derive_palette
        palette = derive_palette('#101820')
        for key, value in palette.items():
            if key == 'dark':
                self.assertIsInstance(value, bool)
                continue
            if key == 'contrast':
                self.assertIsInstance(value, float)
                continue
            with self.subTest(token=key):
                self.assertIsInstance(value, str)
                self.assertTrue(
                    re.fullmatch(r'#[0-9A-F]{6}|rgba\(\d{1,3}, \d{1,3}, \d{1,3}, [\d.]+\)', value),
                    '%s produced %r' % (key, value),
                )


class ThemeAccentColorTests(TestCase):
    """Accent colour: the brand tone behind headings, links and buttons."""

    def setUp(self):
        from core.models import Category, Theme
        self.category = Category.objects.create(name="Video Editor")
        self.developer_category = Category.objects.create(name="Developer")
        self.categories = Theme.objects.create(name="Categories", category=self.category)
        self.cyan = Theme.objects.create(name="Cyan", category=self.category)
        self.minimal = Theme.objects.create(name="Minimal", category=self.category)
        self.developer = Theme.objects.create(name="Minimal", category=self.developer_category)
        self.user = User.objects.create_user(
            username='accentuser', email='accent@example.com', password='pass12345',
        )
        self.profile = Profile.objects.create(user=self.user, theme=self.categories)
        self.client.login(username='accentuser', password='pass12345')

    def _switch_theme(self, theme):
        self.profile.theme = theme
        self.profile.save()

    def test_every_recolourable_theme_offers_an_accent(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS, accent_color_supported
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            if not spec.get('accent_tokens'):
                continue
            with self.subTest(theme='%s/%s' % (category, slug)):
                self.assertTrue(accent_color_supported(category, slug))

    def test_the_neon_brutalist_family_has_no_accent_to_recolour(self):
        """Their accent *is* the hard ink, which already travels with the
        background — offering a picker would store a colour nothing renders."""
        from core.theme_colors import accent_color_supported, accent_tokens
        for slug in ('Cyan', 'Yellow', 'Monochrome'):
            with self.subTest(theme=slug):
                self.assertFalse(accent_color_supported('video_editor', slug))
                self.assertEqual(accent_tokens('video_editor', slug), {})

    def test_other_categories_have_no_accent_control(self):
        from core.theme_colors import accent_color_supported
        self.assertFalse(accent_color_supported('developer', 'Minimal'))
        self.assertFalse(accent_color_supported('student', 'Classic Scholar'))

    def test_editor_renders_the_accent_control(self):
        response = self.client.get(reverse('customize_theme_background'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="bgc-accent-swatches"')
        self.assertContains(response, 'id="bgc-accent-hex"')
        # The theme's own emerald leads the grid.
        self.assertContains(response, 'data-hex="#10B981"')

    def test_editor_hides_the_control_for_a_theme_without_an_accent(self):
        self._switch_theme(self.cyan)
        response = self.client.get(reverse('customize_theme_background'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="bgc-accent-swatches"')

    def test_arabic_editor_renders_the_accent_control(self):
        response = self.client.get(reverse('arabic_customize_theme_background'))
        self.assertContains(response, 'id="bgc-accent-swatches"')
        self.assertContains(response, 'لون الهوية')

    def test_save_persists_an_accent(self):
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'accent': '#ff006e'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(response.json()['accent'], '#FF006E')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {'accent': '#FF006E'})

    def test_saving_an_accent_leaves_the_background_alone(self):
        """The editor posts one control at a time, so the other colour has to
        survive a save of its sibling."""
        self.profile.theme_settings = {'background': '#2B1055'}
        self.profile.save()
        self.client.post(
            reverse('customize_theme_background_save'),
            data={'accent': '#7C3AED'},
        )
        self.profile.refresh_from_db()
        self.assertEqual(
            self.profile.theme_settings, {'background': '#2B1055', 'accent': '#7C3AED'},
        )

    def test_saving_a_background_leaves_the_accent_alone(self):
        self.profile.theme_settings = {'accent': '#7C3AED'}
        self.profile.save()
        self.client.post(
            reverse('customize_theme_background_save'),
            data={'background': '#0B2B26'},
        )
        self.profile.refresh_from_db()
        self.assertEqual(
            self.profile.theme_settings, {'background': '#0B2B26', 'accent': '#7C3AED'},
        )

    def test_both_colours_save_together(self):
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'background': '#0B2B26', 'accent': '#F59E0B'},
        )
        self.assertTrue(response.json()['success'])
        self.profile.refresh_from_db()
        self.assertEqual(
            self.profile.theme_settings, {'background': '#0B2B26', 'accent': '#F59E0B'},
        )

    def test_picking_the_theme_own_accent_is_treated_as_a_reset(self):
        self.profile.theme_settings = {'accent': '#7C3AED'}
        self.profile.save()
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'accent': '#10b981'},
        )
        self.assertTrue(response.json()['success'])
        self.assertTrue(response.json()['reset'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_save_rejects_a_garbage_accent(self):
        for value in ('', 'red', '#12345', '#0A0E27AA', 'javascript:alert(1)'):
            response = self.client.post(
                reverse('customize_theme_background_save'),
                data={'accent': value},
            )
            self.assertEqual(response.status_code, 400, value)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_save_is_refused_for_an_unsupported_theme(self):
        self._switch_theme(self.developer)
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'accent': '#7C3AED'},
        )
        self.assertEqual(response.status_code, 400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_accent_save_is_refused_for_a_theme_without_one(self):
        """Storing an accent the page will not render would leave the editor
        claiming a customisation the visitor never sees."""
        self._switch_theme(self.cyan)
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'accent': '#7C3AED'},
        )
        self.assertEqual(response.status_code, 400)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_reset_clears_both_colours(self):
        self.profile.theme_settings = {'background': '#2B1055', 'accent': '#7C3AED'}
        self.profile.save()
        response = self.client.post(
            reverse('customize_theme_background_save'),
            data={'reset': '1'},
        )
        self.assertTrue(response.json()['reset'])
        self.assertEqual(response.json()['background'], '#070E0A')
        self.assertEqual(response.json()['accent'], '#10B981')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_a_saved_accent_survives_a_switch_between_video_editor_themes(self):
        self.profile.theme_settings = {'accent': '#7C3AED'}
        self.profile.save()
        self._switch_theme(self.minimal)
        from core.theme_colors import resolve_background_palette
        resolved = resolve_background_palette(self.profile)
        self.assertTrue(resolved['accent_custom'])
        self.assertEqual(resolved['accent'], '#7C3AED')

    def test_a_saved_accent_is_ignored_once_the_theme_leaves_the_category(self):
        self.profile.theme_settings = {'accent': '#7C3AED'}
        self.profile.save()
        self._switch_theme(self.developer)
        from core.theme_colors import resolve_background_palette
        self.assertFalse(resolve_background_palette(self.profile)['accent_custom'])

    def test_portfolio_emits_no_accent_css_when_only_the_background_is_set(self):
        self.profile.theme_settings = {'background': '#101820'}
        self.profile.save()
        from core.theme_colors import resolve_background_palette
        resolved = resolve_background_palette(self.profile)
        self.assertTrue(resolved['custom'])
        self.assertFalse(resolved['accent_custom'])

    def test_an_untouched_theme_never_has_its_accent_adjusted(self):
        """The safety net is for user picks. Several themes use a low-contrast
        accent decoratively — Animated's cyan is a gradient stop on a near-white
        page, not body type — so repainting the shipped pairing would change a
        theme that is working as designed."""
        from core.models import Theme
        from core.theme_colors import THEME_BACKGROUND_SPECS, resolve_background_palette
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            if not spec.get('accent_tokens'):
                continue
            with self.subTest(theme='%s/%s' % (category, slug)):
                self._switch_theme(Theme.objects.create(
                    name=slug.replace('_', ' ').title(),
                    category=self.category if category == 'video_editor' else self.developer_category,
                ))
                self.profile.theme_settings = {}
                self.profile.save()
                palette = resolve_background_palette(self.profile)['accent_palette']
                self.assertEqual(palette['accent'], spec['accent'])
                self.assertFalse(palette['adjusted'])


class ThemeAccentPageRenderTests(TestCase):
    """End-to-end: a real portfolio request carries the accent override into
    <head>, after the theme's own token block."""

    def setUp(self):
        from core.models import Category
        from portfolios.views import get_or_create_mock_user
        self.category = Category.objects.create(name="Video Editor")
        self.developer_category = Category.objects.create(name="Developer")
        # The mock user is exempt from the subscription gate, so a real
        # portfolio request renders without inventing a paid subscription.
        self.user = get_or_create_mock_user()
        self.profile = Profile.objects.get(user=self.user)
        self.profile.is_public = True
        self.profile.save()

    def _theme(self, slug, category='video_editor'):
        from core.models import Theme
        name = slug.replace('_', ' ').title()
        parent = self.developer_category if category == 'developer' else self.category
        theme, _ = Theme.objects.get_or_create(name=name, category=parent)
        return theme

    def _render(self, slug, settings, category='video_editor'):
        self.profile.theme = self._theme(slug, category)
        self.profile.theme_settings = settings
        self.profile.save()
        response = self.client.get('/%s/' % self.user.username)
        self.assertEqual(response.status_code, 200, slug)
        return response.content.decode('utf-8')

    def test_the_whole_categories_accent_reaches_the_portfolio(self):
        html = self._render('categories', {'accent': '#FF006E'})
        self.assertIn('--sf-accent:', html)
        self.assertIn('--accent: var(--sf-accent-primary);', html)
        # The Categories theme's own glow and wash tokens travel with it.
        self.assertIn('--accent-glow: var(--sf-accent-partner);', html)
        self.assertIn('--accent-light: var(--sf-accent-soft);', html)
        self.assertIn('--grad: linear-gradient(135deg, var(--sf-accent)', html)

    def test_minimal_and_editorial_use_their_own_accent_token_names(self):
        """The five spellings of "the brand colour" are data, not code — this is
        the guard that the registry keeps pointing at real properties."""
        self.assertIn(
            '--primary: var(--sf-accent-primary);',
            self._render('minimal', {'accent': '#FF006E'}),
        )
        self.assertIn(
            '--ember: var(--sf-accent-primary);',
            self._render('editorial_studio', {'accent': '#FF006E'}),
        )

    def test_every_recolourable_theme_bridges_its_own_primary_token(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            tokens = spec.get('accent_tokens') or {}
            if not tokens:
                continue
            with self.subTest(theme='%s/%s' % (category, slug)):
                html = self._render(slug, {'accent': '#FF006E'}, category)
                for prop in tokens.get('primary', ()):
                    self.assertIn('%s: var(--sf-accent-primary);' % prop, html)

    def test_the_override_stays_in_head_and_after_the_theme_token(self):
        html = self._render('categories', {'accent': '#FF006E'})
        self.assertLess(html.find('--sf-accent:'), html.lower().find('</head>'))
        self.assertLess(html.find('--sf-accent:'), html.find('--accent: var(--sf-accent-primary);'))

    def test_an_untouched_profile_emits_no_accent_block(self):
        html = self._render('categories', {})
        self.assertNotIn('--sf-accent:', html)
        self.assertNotIn('--accent: var(--sf-accent-primary);', html)

    def test_sub_pages_carry_the_accent_override_too(self):
        """The reels/long pages are separate templates with their own :root, so
        a recoloured accent has to travel to them as well. Each page spells
        the brand colour differently, which is what the registry encodes."""
        from core.theme_colors import SLOT_PRIMARY, THEME_BACKGROUND_SPECS
        username = self.user.username
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            tokens = spec.get('accent_tokens') or {}
            if not tokens:
                continue
            self.profile.theme = self._theme(slug, category)
            self.profile.theme_settings = {'accent': '#FF006E'}
            self.profile.save()
            for path in ('reels/', 'long-videos/'):
                if not self._has_sub_page(slug, path):
                    # Classic is a single-page résumé theme.
                    continue
                with self.subTest(theme='%s/%s' % (category, slug), path=path):
                    html = self.client.get('/%s/%s' % (username, path)).content.decode('utf-8')
                    self.assertEqual(html.count('--sf-accent:'), 1, path)
                    for prop in tokens[SLOT_PRIMARY]:
                        self.assertIn('%s: var(--sf-accent-primary);' % prop, html, path)

    @staticmethod
    def _has_sub_page(slug, path):
        from django.template import TemplateDoesNotExist
        from django.template.loader import get_template
        suffix = 'reels' if path == 'reels/' else 'long'
        try:
            get_template('portfolios/video_editor/video_editor_%s_%s.html' % (slug, suffix))
        except TemplateDoesNotExist:
            return False
        return True

    def test_a_brutal_theme_never_emits_an_accent_block(self):
        """No accent control is offered for them, so a stored colour must not
        leak in either — their accent is the hard ink and always follows the
        background."""
        html = self._render('cyan', {'accent': '#7C3AED'})
        self.assertNotIn('--sf-accent:', html)
        self.assertNotIn('--accent: var(--sf-accent-primary);', html)


class ThemeAccentPaletteDerivationTests(TestCase):
    """core.theme_colors.derive_accent_palette: legibility guarantees."""

    BACKGROUNDS = ('#070E0A', '#0A0E27', '#000000', '#F8FAFC', '#F5F0E8', '#F4F2ED', '#FFFFFF')
    ACCENTS = ('#10B981', '#FF006E', '#00D9FF', '#7C3AED', '#F59E0B', '#F5A623', '#0A0E27', '#FFFFFF')

    def test_accent_always_clears_aa_large_against_the_background(self):
        from core.theme_colors import ACCENT_MIN_CONTRAST, contrast_ratio, derive_accent_palette, parse_hex_color
        for bg in self.BACKGROUNDS:
            for accent in self.ACCENTS:
                with self.subTest(background=bg, accent=accent):
                    palette = derive_accent_palette(accent, bg)
                    ratio = contrast_ratio(parse_hex_color(palette['accent']),
                                           parse_hex_color(bg))
                    self.assertGreaterEqual(ratio, ACCENT_MIN_CONTRAST, '%s on %s' % (accent, bg))

    def test_text_on_an_accent_fill_always_clears_full_aa(self):
        from core.theme_colors import contrast_ratio, derive_accent_palette, parse_hex_color
        for bg in self.BACKGROUNDS:
            for accent in self.ACCENTS:
                with self.subTest(background=bg, accent=accent):
                    palette = derive_accent_palette(accent, bg)
                    ratio = contrast_ratio(parse_hex_color(palette['accent']),
                                           parse_hex_color(palette['ink']))
                    self.assertGreaterEqual(ratio, 4.5, '%s ink on %s' % (accent, bg))

    def test_a_readable_accent_is_passed_through_untouched(self):
        from core.theme_colors import derive_accent_palette
        palette = derive_accent_palette('#10B981', '#070E0A')
        self.assertEqual(palette['accent'], '#10B981')
        self.assertFalse(palette['adjusted'])

    def test_an_unreadable_accent_is_adjusted_and_flags_itself(self):
        from core.theme_colors import derive_accent_palette
        palette = derive_accent_palette('#0A0E27', '#070E0A')
        self.assertNotEqual(palette['accent'], '#0A0E27')
        self.assertTrue(palette['adjusted'])

    def test_reported_contrast_matches_the_measured_ratio(self):
        from core.theme_colors import contrast_ratio, derive_accent_palette, parse_hex_color
        for accent in self.ACCENTS:
            palette = derive_accent_palette(accent, '#070E0A')
            measured = contrast_ratio(parse_hex_color(palette['accent']),
                                      parse_hex_color('#070E0A'))
            self.assertAlmostEqual(palette['contrast'], round(measured, 1), places=1)

    def test_the_accent_is_never_indistinguishable_from_the_background(self):
        from core.theme_colors import derive_accent_palette
        for bg in self.BACKGROUNDS:
            with self.subTest(background=bg):
                palette = derive_accent_palette(bg, bg)
                self.assertNotEqual(palette['accent'], bg)

    def test_garbage_falls_back_without_raising(self):
        from core.theme_colors import derive_accent_palette
        self.assertTrue(derive_accent_palette('nope', None)['accent'].startswith('#'))
        self.assertTrue(derive_accent_palette(None, 'nope')['accent'].startswith('#'))

    def test_palette_values_are_all_css_safe(self):
        from core.theme_colors import derive_accent_palette
        palette = derive_accent_palette('#10B981', '#070E0A')
        for key, value in palette.items():
            if key in ('adjusted', 'dark'):
                self.assertIsInstance(value, bool)
                continue
            if key in ('contrast', 'ink_contrast'):
                self.assertIsInstance(value, float)
                continue
            if key.endswith('_rgb'):
                # Bare channels, so the theme can write rgba(var(--accent-rgb), .4).
                # These are the one value in the palette that is not a complete
                # CSS colour on its own — they are only ever valid *inside* an
                # rgba() call, which is exactly what they are for.
                with self.subTest(token=key):
                    self.assertRegex(value, r'^\d{1,3}, \d{1,3}, \d{1,3}$')
                    for channel in value.split(', '):
                        self.assertLessEqual(int(channel), 255)
                continue
            with self.subTest(token=key):
                self.assertIsInstance(value, str)
                self.assertTrue(
                    re.fullmatch(r'#[0-9A-F]{6}|rgba\(\d{1,3}, \d{1,3}, \d{1,3}, [\d.]+\)', value),
                    '%s produced %r' % (key, value),
                )

    def test_every_rgb_token_describes_its_own_tone(self):
        """A channel token that drifts from the hex beside it is the exact
        failure the tokens exist to prevent: the page recolours its labels and
        keeps its washes in the old brand colour."""
        from core.theme_colors import (
            derive_accent_palette, to_rgb_channels,
        )
        palette = derive_accent_palette('#10B981', '#070E0A')
        for slot in ('primary', 'partner', 'trio', 'glow', 'ink'):
            with self.subTest(slot=slot):
                self.assertEqual(
                    palette['%s_rgb' % slot], to_rgb_channels(palette[slot]),
                )

    def test_the_third_tone_is_a_rotation_of_the_accent_not_a_second_pick(self):
        """Creative spends its third colour on ambient orbs and the "long form"
        badge. Leaving the shipped gold there after a recolour strands a foreign
        hue next to the new brand colour, so the third stop is derived."""
        import colorsys

        from core.theme_colors import (
            TRIO_HUE_SHIFT, derive_accent_palette, parse_hex_color,
        )
        palette = derive_accent_palette('#10B981', '#070E0A')
        trio = parse_hex_color(palette['trio'])
        accent = parse_hex_color(palette['accent'])
        self.assertNotEqual(tuple(trio), tuple(accent))

        def hue(rgb):
            return colorsys.rgb_to_hls(*(c / 255.0 for c in rgb))[0]

        rotated = (hue(accent) + TRIO_HUE_SHIFT) % 1.0
        self.assertAlmostEqual(hue(trio), rotated, delta=0.02)

    def test_a_hueless_accent_still_gets_a_coloured_third_stop(self):
        """Rotating grey is still grey, so the fallback keeps the third stop a
        colour rather than a third shade of the same nothing."""
        from core.theme_colors import derive_accent_palette
        palette = derive_accent_palette('#808080', '#FFFFFF', adjust=False)
        self.assertEqual(palette['trio'], '#FFD700')
        self.assertEqual(palette['trio_rgb'], '255, 215, 0')

    def test_the_shipped_pairing_is_left_exactly_as_the_theme_designed_it(self):
        """Not every theme's own accent clears AA Large on its own background —
        Animated's cyan is a gradient stop on a near-white page, not body type.
        What matters is that the derivation never "helpfully" repaints that,
        so an untouched theme is byte-identical to its shipped look."""
        from core.theme_colors import (
            THEME_BACKGROUND_SPECS, default_accent, default_background,
            derive_accent_palette,
        )
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            if not spec.get('accent_tokens'):
                continue
            with self.subTest(theme=slug):
                palette = derive_accent_palette(
                    default_accent(category, slug), default_background(category, slug),
                    adjust=False,
                )
                self.assertEqual(palette['accent'], spec['accent'], slug)
                self.assertFalse(palette['adjusted'], slug)

    def test_the_safety_net_still_runs_once_the_background_is_customised(self):
        """Off-shipped means the net applies — recolouring the background is
        exactly when a theme's decorative accent can end up unreadable."""
        from core.theme_colors import derive_accent_palette
        # Animated's cyan on a near-white page, but the page is now the user's.
        palette = derive_accent_palette('#00C9FF', '#FFFFFF', adjust=True)
        self.assertNotEqual(palette['accent'], '#00C9FF')
        self.assertTrue(palette['adjusted'])


class ThemeAccentRegistryTests(TestCase):
    """accent_tokens is what the stylesheet and the editor both read."""

    # The slots core/theme_colors derives a tone for. Anything outside this set
    # would emit a var() the stylesheet never defines.
    KNOWN_SLOTS = frozenset({
        SLOT_PRIMARY, SLOT_PARTNER, SLOT_SOFT, SLOT_GLOW, SLOT_TRIO, SLOT_INK,
    })

    def test_every_slot_name_is_one_the_stylesheet_emits(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS, derive_accent_palette
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            tokens = spec.get('accent_tokens') or {}
            label = '%s/%s' % (category, slug)
            with self.subTest(theme=label):
                for slot in tokens:
                    self.assertIn(slot, self.KNOWN_SLOTS, label)
                    for prop in tokens[slot]:
                        self.assertTrue(prop.startswith('--'), '%s: %s' % (label, prop))
                if not tokens:
                    continue
                # Every token must name a tone the derivation actually produces.
                palette = derive_accent_palette(spec['accent'], spec['default'])
                for slot in tokens:
                    self.assertIn(
                        'accent-%s' % slot if slot != SLOT_PRIMARY else 'accent',
                        {'accent', 'accent-partner', 'accent-glow', 'accent-soft',
                         'accent-trio', 'accent-ink'},
                        '%s: %s' % (label, slot),
                    )
                self.assertTrue(palette['accent'].startswith('#'))

    def test_a_channel_map_only_names_slots_the_theme_also_declares(self):
        """accent_channels is the companion to accent_tokens, not a replacement:
        a channel for a tone the token map does not carry would restyle one
        element and leave its label in the old colour."""
        from core.theme_colors import THEME_BACKGROUND_SPECS
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            channels = spec.get('accent_channels') or {}
            tokens = spec.get('accent_tokens') or {}
            label = '%s/%s' % (category, slug)
            with self.subTest(theme=label):
                self.assertTrue(set(channels) <= set(tokens), label)
                for slot, props in channels.items():
                    for prop in props:
                        self.assertTrue(prop.startswith('--'), '%s: %s' % (label, prop))
                        self.assertTrue(
                            prop.endswith('-rgb'), '%s: %s' % (label, prop),
                        )

    def test_channel_vars_are_resolved_for_every_declared_channel(self):
        """The stylesheet loops the resolved list, not the raw map, so a slot
        with no matching <slot>_rgb key would silently emit no rule."""
        from core.theme_colors import accent_channel_vars, derive_accent_palette
        palette = derive_accent_palette('#10B981', '#070E0A')
        resolved = accent_channel_vars('video_editor', 'creative', palette)
        pairs = {item['property']: item['channels'] for item in resolved}
        self.assertEqual(pairs['--accent-rgb'], palette['primary_rgb'])
        self.assertEqual(pairs['--accent2-rgb'], palette['partner_rgb'])
        self.assertEqual(pairs['--gold-rgb'], palette['trio_rgb'])
# A theme with no channels resolves to nothing rather than to junk.
        # Minimal fades its brand colour through tokens, so it declares none.
        self.assertEqual(accent_channel_vars('video_editor', 'minimal', palette), [])
        # Pro does declare one, because it fades its cyan as a literal.
        self.assertEqual(
            [item['property'] for item in
             accent_channel_vars('video_editor', 'pro', palette)],
            ['--accent-rgb'],
        )

    def test_the_primary_slot_is_present_for_every_recolourable_theme(self):
        from core.theme_colors import SLOT_PRIMARY, THEME_BACKGROUND_SPECS
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            tokens = spec.get('accent_tokens') or {}
            if not tokens:
                continue
            with self.subTest(theme=slug):
                self.assertIn(SLOT_PRIMARY, tokens)
                self.assertTrue(tokens[SLOT_PRIMARY])

    def test_preset_grid_leads_with_the_theme_accent_and_has_no_duplicates(self):
        from core.theme_colors import THEME_BACKGROUND_SPECS, accent_presets_for, default_accent
        for (category, slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            if not spec.get('accent_tokens'):
                continue
            with self.subTest(theme=slug):
                presets = accent_presets_for(category, slug)
                values = [preset['value'] for preset in presets]
                self.assertEqual(values[0], default_accent(category, slug))
                self.assertEqual(len(values), len(set(values)))
                for preset in presets:
                    self.assertTrue(preset['label'])
                    self.assertTrue(preset['label_ar'])

    def test_presets_fall_back_to_the_shared_grid_for_unsupported_themes(self):
        from core.theme_colors import accent_presets_for
        presets = accent_presets_for('developer', 'Minimal')
        self.assertTrue(presets)

    def test_normalize_drops_an_accent_equal_to_the_theme_default(self):
        from core.theme_colors import normalize_theme_settings
        self.assertEqual(
            normalize_theme_settings({'accent': '#10B981'}, 'video_editor', 'Categories'),
            {},
        )
        self.assertEqual(
            normalize_theme_settings({'accent': '#FF006E'}, 'video_editor', 'Categories'),
            {'accent': '#FF006E'},
        )

    def test_normalize_refuses_an_accent_on_a_theme_without_one(self):
        from core.theme_colors import normalize_theme_settings
        self.assertEqual(
            normalize_theme_settings({'accent': '#7C3AED'}, 'video_editor', 'Cyan'),
            {},
        )

    def test_normalize_accepts_a_bare_string_as_a_background(self):
        """Older callers and cached payloads pass the colour on its own."""
        from core.theme_colors import normalize_theme_settings
        self.assertEqual(
            normalize_theme_settings('#2B1055', 'video_editor', 'Minimal'),
            {'background': '#2B1055'},
        )

    def test_normalize_keeps_both_colours(self):
        from core.theme_colors import normalize_theme_settings
        self.assertEqual(
            normalize_theme_settings(
                {'background': '#0B2B26', 'accent': '#7C3AED'},
                'video_editor', 'Categories',
            ),
            {'background': '#0B2B26', 'accent': '#7C3AED'},
        )

    def test_default_accent_falls_back_for_unknown_pairs(self):
        from core.theme_colors import DEFAULT_BACKGROUND, default_accent
        self.assertEqual(default_accent('developer', 'Minimal'), DEFAULT_BACKGROUND)
        self.assertEqual(default_accent('video_editor', 'Categories'), '#10B981')


class ThemeBackgroundRegistryTests(TestCase):
    """THEME_BACKGROUND_SPECS is the single source of truth for the feature."""

    def test_specs_are_well_formed(self):
        from core.theme_colors import (
            CATEGORY_LABELS, FAMILY_BRUTAL, FAMILY_CLASSIC, FAMILY_GLASS,
            FAMILY_MINIMAL, FAMILY_PAPER, FAMILY_SURFACE, THEME_BACKGROUND_SPECS,
            normalize_hex_color,
        )
        families = {FAMILY_SURFACE, FAMILY_GLASS, FAMILY_MINIMAL, FAMILY_PAPER,
                    FAMILY_BRUTAL, FAMILY_CLASSIC}
        for (category, theme_slug), spec in sorted(THEME_BACKGROUND_SPECS.items()):
            label = '%s/%s' % (category, theme_slug)
            with self.subTest(theme=label):
                self.assertIn(category, CATEGORY_LABELS, label)
                self.assertIn(spec['family'], families, label)
                self.assertEqual(spec['default'], normalize_hex_color(spec['default']), label)
                self.assertEqual(spec['accent'], normalize_hex_color(spec['accent']), label)
                self.assertEqual(len(spec['gradient']), 3, label)
                self.assertIn('accent_tokens', spec, label)

    def test_registry_covers_both_polarities(self):
        """A registry that only knew dark themes would hide the whole light
        half of the problem the derivation has to solve."""
        from core.theme_colors import THEME_BACKGROUND_SPECS, is_dark, parse_hex_color
        dark = [k for k, s in THEME_BACKGROUND_SPECS.items() if is_dark(parse_hex_color(s['default']))]
        light = [k for k, s in THEME_BACKGROUND_SPECS.items() if not is_dark(parse_hex_color(s['default']))]
        self.assertGreaterEqual(len(dark), 6)
        self.assertGreaterEqual(len(light), 5)

    def test_gate_is_derived_from_the_registry(self):
        from core.theme_colors import BACKGROUND_ENABLED_THEMES, THEME_BACKGROUND_SPECS
        self.assertEqual(set(BACKGROUND_ENABLED_THEMES), set(THEME_BACKGROUND_SPECS))

    def test_theme_families_match_how_each_theme_spells_its_background(self):
        from core.theme_colors import theme_family
        self.assertEqual(theme_family('video_editor', 'Minimal'), 'minimal')
        self.assertEqual(theme_family('video_editor', 'Editorial Studio'), 'paper')
        self.assertEqual(theme_family('video_editor', 'Cyan'), 'brutal')
        self.assertEqual(theme_family('video_editor', 'Yellow'), 'brutal')
        self.assertEqual(theme_family('video_editor', 'Monochrome'), 'brutal')
        self.assertEqual(theme_family('developer', 'Classic'), 'classic')
        for slug in ('Pro', 'Cinematic', 'Categories', 'Categories White'):
            with self.subTest(theme=slug):
                self.assertEqual(theme_family('video_editor', slug), 'surface')
        for slug in ('Animated', 'Animated Dark', 'Creative', 'Creative White'):
            with self.subTest(theme=slug):
                self.assertEqual(theme_family('video_editor', slug), 'glass')

    def test_default_background_falls_back_for_unknown_pairs(self):
        from core.theme_colors import DEFAULT_BACKGROUND, default_background
        self.assertEqual(default_background('developer', 'Minimal'), DEFAULT_BACKGROUND)
        self.assertEqual(default_background('video_editor', 'Minimal'), '#0A0E27')
        self.assertEqual(default_background('developer', 'Classic'), '#F9FAFB')

    def test_presets_lead_with_the_theme_default_and_have_no_duplicates(self):
        from core.theme_colors import default_background, presets_for
        for theme_slug in ('Minimal', 'Pro', 'Creative', 'Animated', 'Editorial Studio',
                           'Cyan', 'Yellow', 'Monochrome'):
            with self.subTest(theme=theme_slug):
                presets = presets_for('video_editor', theme_slug)
                values = [preset['value'] for preset in presets]
                self.assertEqual(values[0], default_background('video_editor', theme_slug))
                self.assertEqual(len(values), len(set(values)))
                for preset in presets:
                    self.assertTrue(preset['label'])
                    self.assertTrue(preset['label_ar'])

    def test_presets_drop_the_default_when_it_is_already_neutral(self):
        from core.theme_colors import presets_for
        # Pro ships pure black, which is already the neutral 'Ink' swatch.
        values = [preset['value'] for preset in presets_for('video_editor', 'Pro')]
        self.assertEqual(values[0], '#000000')
        self.assertEqual(values.count('#000000'), 1)

    def test_presets_fall_back_to_the_shared_grid_for_unsupported_themes(self):
        """The locked panel still renders a sample grid, so an unsupported theme
falls back to the neutral list rather than an empty one."""
        from core.theme_colors import DEFAULT_BACKGROUND, presets_for
        presets = presets_for('developer', 'Minimal')
        self.assertTrue(presets)
        self.assertEqual(presets[0]['value'], DEFAULT_BACKGROUND)


class DeveloperClassicColourTests(TestCase):
    """Developer Classic is the first theme outside the Video Editor category
    that "Change colours" is enabled for.

    It is also the one theme in the registry whose hero is a block *filled with
    the accent* rather than a page that uses the accent as type. Repointing the
    accent tokens alone therefore produced exactly the failure this class
    guards: a white ``h1`` and a white ``#F9FAFB``-toned sub-heading on top of a
    hero the user had just made pale. The fix is that everything printed on the
    hero answers to the accent's own ``ink`` tone, which flips with the accent's
    polarity rather than the page's — see the ``classic`` branch of
    portfolios/common/theme_background_css.html.
    """

    CATEGORY = 'developer'
    THEME = 'classic'
    TEMPLATE = 'portfolios/developer/developer_classic.html'
    INCLUDE = 'portfolios/common/theme_background_css.html'

    def setUp(self):
        from django.contrib.auth import get_user_model
        from core.models import Category, Profile, Theme
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='devclassic', email='dc@example.com', password='pass12345',
        )
        self.theme = Theme.objects.create(
            name='Classic', category=Category.objects.create(name='Developer'),
        )
        self.profile = Profile.objects.create(user=self.user, theme=self.theme)
        self.client.login(username='devclassic', password='pass12345')

    # ── helpers ───────────────────────────────────────────────────────────────

    def _save(self, **data):
        return self.client.post(reverse('customize_theme_background_save'), data=data)

    def _render_override(self, custom=False, background='#F9FAFB',
                         accent_custom=False, accent='#1E3A8A'):
        """The stylesheet the portfolio actually ships, with only the flags a
        real save would have produced."""
        from django.template.loader import render_to_string
        from core.theme_colors import (
            SLOT_PARTNER, SLOT_PRIMARY, SLOT_SOFT,
            accent_channel_vars, derive_accent_palette, derive_palette,
        )
        accent_palette = derive_accent_palette(accent, background, adjust=True)
        return render_to_string(self.INCLUDE, {
            'theme_background': {
                'custom': custom,
                'accent_custom': accent_custom,
                'family': 'classic',
                'background': background,
                'accent': accent,
                'accent_tokens': {
                    SLOT_PRIMARY: ('--sfc-accent',),
                    SLOT_PARTNER: ('--sfc-accent-strong',),
                    SLOT_SOFT: ('--sfc-accent-wash',),
                },
                'accent_channel_vars': [
                    {'property': '--sfc-accent-rgb',
                     'channels': accent_palette['primary_rgb']},
                ],
                'palette': derive_palette(background),
                'accent_palette': accent_palette,
            },
        })

    # ── the gate ──────────────────────────────────────────────────────────────

    def test_the_theme_is_recolourable_and_the_editor_unlocks(self):
        from core.theme_colors import background_color_supported, background_state
        self.assertTrue(background_color_supported(self.CATEGORY, self.THEME))
        self.assertEqual(background_state(self.profile)['preview_variant'], 'developer')
        response = self.client.get(reverse('customize_theme_background'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="bgc-swatches"')
        self.assertContains(response, 'id="bgc-accent-swatches"')
        self.assertContains(response, 'data-family="classic"')
        # The live preview has to describe this theme, not the reel mock-up.
        self.assertContains(response, 'data-variant="developer"')
        self.assertContains(response, 'Code that ships')
        self.assertNotContains(response, 'Watch reel')

    def test_arabic_editor_unlocks_with_the_rtl_copy(self):
        response = self.client.get(reverse('arabic_customize_theme_background'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'data-variant="developer"')
        self.assertContains(response, 'id="bgc-accent-swatches"')

    def test_a_locked_sibling_lists_exactly_the_themes_that_work(self):
        """The locked panel is the only place that enumerates the recolourable
        set, so it is the one that has to stay in step with the registry."""
        from core.models import Category, Profile, Theme
        from core.theme_colors import supported_theme_summary
        sibling = Theme.objects.create(
            name='Minimal', category=Category.objects.get(name='Developer'),
        )
        self.profile.theme = sibling
        self.profile.save()
        for url in (reverse('customize_theme_background'),
                    reverse('arabic_customize_theme_background')):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'id="bgc-swatches"')
                self.assertContains(response, 'Classic')
                self.assertContains(response, 'Monochrome')  # video editor's
        # And the helper the copy is built from agrees with the registry.
        self.assertIn('Developer (Classic)', supported_theme_summary())

    def test_editor_leads_with_this_theme_own_default(self):
        response = self.client.get(reverse('customize_theme_background'))
        self.assertContains(response, 'id="bgc-color" value="#F9FAFB"')
        self.assertContains(response, 'id="bgc-accent-color" value="#1E3A8A"')
        self.assertContains(response, 'data-hex="#F9FAFB"')
        self.assertContains(response, 'data-hex="#1E3A8A"')

    # ── saving ────────────────────────────────────────────────────────────────

    def test_background_save_and_reset_round_trip(self):
        response = self._save(background='#123456')
        self.assertTrue(response.json()['success'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {'background': '#123456'})

        response = self._save(reset='1')
        self.assertEqual(response.json()['background'], '#F9FAFB')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_accent_save_and_reset_round_trip(self):
        response = self._save(accent='#10B981')
        self.assertTrue(response.json()['success'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {'accent': '#10B981'})

        response = self._save(reset='1')
        self.assertEqual(response.json()['accent'], '#1E3A8A')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.theme_settings, {})

    def test_saving_one_colour_leaves_the_other_alone(self):
        self._save(background='#0A0A0A')
        self._save(accent='#10B981')
        self.profile.refresh_from_db()
        self.assertEqual(
            self.profile.theme_settings, {'background': '#0A0A0A', 'accent': '#10B981'},
        )

    # ── the hero, which is the part the family has to solve for itself ───────

    def test_accent_pick_re_derives_the_hero_type(self):
        source = self._render_override(accent_custom=True, accent='#F5A623')
        self.assertIn('--sfc-hero-ink: var(--sf-accent-ink)', source)
        self.assertIn('--sfc-hero-sub: color-mix(', source)
        self.assertIn('--sfc-hero-bio: color-mix(', source)
        # The "Get In Touch" pill is inverted against the hero, so its label is
        # the accent itself rather than a fixed blue-900.
        self.assertIn('--sfc-cta-ink: var(--sf-accent)', source)

    def test_hero_type_is_readable_on_the_accent_for_every_polarity(self):
        """The whole point of the derived ladder: whatever the user picks, the
        type on the hero and the label on the inverted pill clear WCAG AA."""
        from core.theme_colors import (
            ACCENT_INK_MIN_CONTRAST, contrast_ratio, derive_accent_palette,
            parse_hex_color,
        )
        for pick in ('#F5A623', '#10B981', '#1E3A8A', '#0A0A0A', '#FFFFFF'):
            for background in ('#F9FAFB', '#0A0A0A', '#F4F2ED'):
                with self.subTest(accent=pick, background=background):
                    palette = derive_accent_palette(pick, background, adjust=True)
                    on_accent = contrast_ratio(
                        parse_hex_color(palette['accent']),
                        parse_hex_color(palette['ink']),
                    )
                    self.assertGreaterEqual(on_accent, ACCENT_INK_MIN_CONTRAST)
                    on_page = contrast_ratio(
                        parse_hex_color(palette['accent']),
                        parse_hex_color(background),
                    )
                    self.assertGreaterEqual(on_page, 3.0)

    def test_untouched_theme_keeps_its_own_hero_ladder(self):
        """Nothing about the shipped page may depend on an override that was
        never saved — the derived tints are a recolour-only concern."""
        source = self._render_override()
        self.assertNotIn('--sfc-hero-ink', source)
        self.assertNotIn('--sfc-accent-line', source)

    # ── the background bridge ─────────────────────────────────────────────────

    def test_background_pick_repoints_every_theme_token(self):
        source = self._render_override(custom=True, background='#0A0A0A')
        for token in ('--sfc-bg', '--sfc-surface', '--sfc-surface-2',
                      '--sfc-surface-3', '--sfc-text', '--sfc-text-strong',
                      '--sfc-text-soft', '--sfc-text-muted', '--sfc-text-faint',
                      '--sfc-border', '--sfc-border-soft'):
            self.assertIn(token + ': var(--sf-', source)
        # A stranded shipped literal is exactly the "the recolour looks broken"
        # failure, so none of them may survive into the override.
        for literal in ('#F9FAFB', '#E5E7EB', '#1F2937', '#9CA3AF'):
            self.assertNotIn(literal, source)

    def test_untouched_theme_emits_no_override_at_all(self):
        self.assertEqual(self._render_override().strip(), '')

    # ── the theme's own half of the contract ──────────────────────────────────

    def test_template_keeps_every_colour_in_a_token(self):
        """No colour literal outside ``:root``, and no Tailwind palette utility
        anywhere in the markup.

        Tailwind's CDN injects its stylesheet at runtime, i.e. *after* this
        file's own ``<style>``, so a ``text-blue-800`` left on an element would
        win the specificity tie and never follow the override. This is the
        invariant that makes Classic recolourable at all.
        """
        from django.template.loader import get_template
        source = get_template(self.TEMPLATE).template.source
        head, body = source.split('</style>', 1)

        for utility in ('text-gray-', 'bg-gray-', 'border-gray-', 'text-blue-',
                        'bg-blue-', 'border-blue-', 'text-white', 'bg-white',
                        'from-gray-', 'via-blue-', 'to-white', 'text-black'):
            self.assertNotIn(utility, body, utility)

        # Everything after the token block is styling, and styling that names a
        # colour would be a colour the override cannot reach.
        after_tokens = head.split('--sfc-cta-hover: #EFF6FF;', 1)[-1]
        self.assertNotIn('#', after_tokens)

    def test_theme_declares_every_token_it_reads(self):
        """Both directions. A token read but never declared renders as nothing;
        a token declared but never read is a colour the registry offers and the
        page ignores — the drift this whole family guard exists to catch."""
        import re
        from django.template.loader import get_template
        source = get_template(self.TEMPLATE).template.source
        head, _body = source.split('</style>', 1)
        declared = set(re.findall(r'(--sfc-[a-z0-9-]+)\s*:', head))
        read = set(re.findall(r'var\((--sfc-[a-z0-9-]+)', source))
        self.assertEqual(read - declared, set())
        self.assertEqual(declared - read, set())

    def test_theme_background_reaches_the_template(self):
        from core.theme_colors import resolve_background_palette
        self.profile.theme_settings = {'background': '#0A0A0A', 'accent': '#10B981'}
        self.profile.save()
        resolved = resolve_background_palette(self.profile)
        self.assertTrue(resolved['custom'])
        self.assertTrue(resolved['accent_custom'])
        self.assertEqual(resolved['family'], 'classic')
        self.assertIn('--sfc-accent', resolved['accent_tokens']['primary'])


class MonochromeColourTests(TestCase):
    """Monochrome is the theme the "Change colours" control looked broken on.

    It is a neo-brutalist theme, so it paints its page out of a near-black ink
    and a near-white paper: 3px borders, offset shadows, an inverted hover that
    slides a full-strength fill under a card, and a dot-grid printed over the
    whole page. Every one of those is written as a black- or white-alpha
    literal in the shipped CSS, which no ``--bg`` override can reach. Repointing
    ``--border`` alone therefore produced the failure this class guards: black
    borders on a black page, invisible dot-grid, and a hover state that was
    white type on a white fill.
    """

    CATEGORY = 'video_editor'
    THEME = 'monochrome'
    TEMPLATES = (
        'portfolios/video_editor/video_editor_monochrome.html',
        'portfolios/video_editor/video_editor_monochrome_long.html',
        'portfolios/video_editor/video_editor_monochrome_reels.html',
        'portfolios/video_editor/video_editor_monochrome_detail.html',
        'portfolios/video_editor/video_editor_monochrome_category.html',
    )
    STYLESHEET = 'static/css/monochrome.css'
    # The main page keeps all of its CSS in static/css/monochrome.css; the four
    # sub-pages each carry an inline <style> block because they are a different
    # layout from the same stylesheet.
    SUBPAGES = (
        'portfolios/video_editor/video_editor_monochrome_long.html',
        'portfolios/video_editor/video_editor_monochrome_reels.html',
        'portfolios/video_editor/video_editor_monochrome_detail.html',
        'portfolios/video_editor/video_editor_monochrome_category.html',
    )

    # ── the derived palette ──────────────────────────────────────────────────

    def test_texture_and_fill_tokens_flip_with_the_background(self):
        """Everything the brutal family states as a bare alpha literal has to
        carry the background's polarity, or the texture disappears on a dark
        pick and the inverted hover becomes white-on-white."""
        from core.theme_colors import derive_palette

        light = derive_palette('#F5F5F5')
        dark = derive_palette('#101010')

        for token in ('texture', 'hairline', 'star_empty', 'text_shadow',
                      'fill_ink', 'fill_ink_soft', 'fill_wash', 'fill_empty'):
            with self.subTest(token=token, background='light'):
                self.assertIn(token, light)
            with self.subTest(token=token, background='dark'):
                self.assertIn(token, dark)

        # Light page -> black ink; dark page -> white ink.
        self.assertTrue(light['texture'].startswith('rgba(0, 0, 0,'), light['texture'])
        self.assertTrue(dark['texture'].startswith('rgba(255, 255, 255,'), dark['texture'])
        self.assertTrue(light['hairline'].startswith('rgba(0, 0, 0,'), light['hairline'])
        self.assertTrue(dark['hairline'].startswith('rgba(255, 255, 255,'), dark['hairline'])
        # Text sitting on an inverted --text fill: white on a light page's black
        # fill, black on a dark page's white fill.
        self.assertTrue(light['fill_ink'].startswith('rgba(255, 255, 255,'), light['fill_ink'])
        self.assertTrue(dark['fill_ink'].startswith('rgba(0, 0, 0,'), dark['fill_ink'])
        self.assertTrue(light['fill_empty'].startswith('rgba(255, 255, 255,'), light['fill_empty'])
        self.assertTrue(dark['fill_empty'].startswith('rgba(0, 0, 0,'), dark['fill_empty'])

    def test_a_light_recolour_keeps_the_shipped_texture_exactly(self):
        """Monochrome ships a 15%-black dot grid. Deriving it from the theme's
        own ink instead of pure black would quietly restyle every light pick,
        so the light weights are pinned to the shipped values."""
        from core.theme_colors import derive_palette
        palette = derive_palette('#FAFAFA')
        self.assertEqual(palette['texture'], 'rgba(0, 0, 0, 0.15)')
        self.assertEqual(palette['hairline'], 'rgba(0, 0, 0, 0.08)')
        self.assertEqual(palette['star_empty'], 'rgba(0, 0, 0, 0.12)')
        self.assertEqual(palette['fill_ink'], 'rgba(255, 255, 255, 0.85)')

    # ── the shared bridge ────────────────────────────────────────────────────

    def _bridge(self, background):
        from django.template.loader import render_to_string
        from core.theme_colors import derive_palette
        return render_to_string('portfolios/common/theme_background_css.html', {
            'theme_background': {
                'custom': True,
                'accent_custom': False,
                'family': 'brutal',
                'background': background,
                'accent': '#000000',
                'accent_tokens': {},
                'accent_channel_vars': [],
                'palette': derive_palette(background),
                'accent_palette': {},
            },
        })

    def test_bridge_repoints_the_texture_and_fill_tokens(self):
        html = self._bridge('#101010')
        for declaration in (
            '--texture: var(--sf-texture);',
            '--hairline: var(--sf-hairline);',
            '--star-empty: var(--sf-star-empty);',
            '--text-shadow-tint: var(--sf-text-shadow);',
            '--fill-ink: var(--sf-fill-ink);',
            '--fill-ink-soft: var(--sf-fill-ink-soft);',
            '--fill-wash: var(--sf-fill-wash);',
            '--fill-empty: var(--sf-fill-empty);',
        ):
            with self.subTest(declaration=declaration):
                self.assertIn(declaration, html)

    def test_bridge_uses_background_color_not_the_shorthand(self):
        """The dot-grid is a ``background-image`` on body. The ``background``
        shorthand resets background-image to none, so using it here silently
        deleted the texture these three themes are built around."""
        html = self._bridge('#101010')
        body_rule = re.search(r'html,\s*body\s*\{([^}]*)\}', html)
        self.assertIsNotNone(body_rule, 'brutal family no longer paints html/body')
        self.assertIn('background-color: var(--sf-bg) !important;', body_rule.group(1))
        for declaration in re.findall(r'background\s*:', body_rule.group(1)):
            self.fail('the background shorthand wipes the dot-grid: %s' % declaration)

    def test_bridge_paints_black_texture_on_a_light_pick(self):
        """End to end through the derivation, not just the token name."""
        html = self._bridge('#F7F5F2')
        self.assertIn('--sf-texture: rgba(0, 0, 0, 0.15);', html)
        self.assertIn('--sf-fill-ink: rgba(255, 255, 255, 0.85);', html)

    # ── the theme's own CSS ──────────────────────────────────────────────────

    def _stylesheet(self):
        from django.contrib.staticfiles import finders
        path = finders.find('css/monochrome.css')
        self.assertIsNotNone(path, 'css/monochrome.css is not on disk')
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()

    def _split_root(self, css):
        """Split CSS into its leading ``:root`` block and everything after it.

        Brace-matched rather than a literal ``\\n}`` so indentation inside a
        template's inline ``<style>`` does not change where the block ends.
        """
        start = css.index(':root')
        depth = 0
        for index in range(css.index('{', start), len(css)):
            if css[index] == '{':
                depth += 1
            elif css[index] == '}':
                depth -= 1
                if depth == 0:
                    return css[:index + 1], css[index + 1:]
        self.fail('the :root block is never closed')

    # Anything that looks like a colour: #abc, #aabbcc, rgb() or rgba().
    LITERAL = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)')

    def _rules(self, css):
        """Return {selector: declarations} for every rule in a stylesheet.

        Comments are stripped first — a section banner immediately above a rule
        would otherwise be parsed as part of its selector — and repeated
        selectors (a base rule plus its media-query override) are merged rather
        than overwritten.
        """
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)
        rules = {}
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
            selector = ' '.join(match.group(1).split())
            if selector.startswith('@'):
                continue
            rules.setdefault(selector, '')
            rules[selector] += match.group(2)
        return rules

    def test_stylesheet_declares_every_token_it_uses(self):
        """A stylesheet that reads ``var(--x)`` it never defines renders as
        shipped and then silently loses that colour the moment one is saved."""
        css = self._stylesheet()
        declared = set(re.findall(r'(--[\w-]+)\s*:', css))
        used = set(re.findall(r'var\((--[\w-]+)', css))
        self.assertTrue(used)
        self.assertEqual(used - declared, set())

    def test_stylesheet_keeps_no_polarity_locked_literal(self):
        """The shipped values live in ``:root`` and nowhere else.

        A literal anywhere below the token block is a colour a saved background
        cannot reach — the dot-grid, the custom cursor, the floating outlines,
        the empty stars and the inverted hover all used to be exactly that.
        """
        css = self._stylesheet()
        body = self._split_root(css)[1]
        rules = self._rules(body)
        self.assertGreater(len(rules), 20, 'the guard is scanning nothing')
        for selector, declarations in rules.items():
            with self.subTest(selector=selector):
                self.assertNotRegex(
                    declarations, self.LITERAL,
                    'a saved background cannot reach a bare literal in %s: %s'
                    % (selector, ' '.join(declarations.split())))

    def test_media_surfaces_stay_literal_black(self):
        """The letterbox behind a video belongs to the footage. Pinning it to
        ``--media-black`` is what keeps it from drifting with the palette."""
        css = self._stylesheet()
        self.assertRegex(css, r'--media-black:\s*#000000\s*;')
        self.assertRegex(css, r'--media-scrim:\s*rgba\(\s*0,\s*0,\s*0,\s*0\.2\s*\)\s*;')

    # ── the sub-pages ─────────────────────────────────────────────────────────

    def _template_source(self, name):
        from django.template.loader import get_template
        return get_template(name).template.source

    def _inline_style(self, name):
        source = self._template_source(name)
        styles = re.findall(r'<style>(.*?)</style>', source, re.DOTALL)
        self.assertTrue(styles, name)
        return '\n'.join(styles)

    def test_every_monochrome_page_declares_the_overridable_tokens(self):
        """Each sub-page carries its own ``:root`` because
        theme_background_css.html lands last and only wins if the name matches.
        A missing name is not a fall back to the stylesheet — it resolves to
        nothing and the declaration is dropped."""
        required = (
            '--texture', '--hairline', '--star-empty', '--text-shadow-tint',
            '--fill-ink', '--fill-ink-soft', '--fill-wash', '--fill-empty',
        )
        for name in self.SUBPAGES:
            root = self._split_root(self._inline_style(name))[0]
            for token in required:
                with self.subTest(template=name, token=token):
                    self.assertRegex(root, r'%s\s*:' % re.escape(token))

    def test_sub_pages_keep_no_polarity_locked_literal(self):
        """The reels page shipped roughly fifty hardcoded #000/#fff
        declarations — black buttons, a black-bordered nav and a white contact
        slide that no background could move. The other three sub-pages had the
        same problem on their play and back buttons.

        The one deliberate exception is the loading shimmer, which sits over the
        video stage and is meant to read as a dark placeholder.
        """
        allowed_literals = ('.loading-shimmer',)
        for name in self.SUBPAGES:
            body = self._split_root(self._inline_style(name))[1]
            for selector, declarations in self._rules(body).items():
                if selector in allowed_literals:
                    continue
                with self.subTest(template=name, selector=selector):
                    self.assertNotRegex(
                        declarations, self.LITERAL,
                        'a saved background cannot reach a bare literal in %s'
                        % selector)

    def test_reels_page_letterbox_is_the_only_black_left(self):
        """The stage follows the palette; the letterbox around the footage does
        not. That split is the whole fix — an all-black page left the user with
        no visible sign their colour had saved."""
        rules = self._rules(self._split_root(self._inline_style(
            'portfolios/video_editor/video_editor_monochrome_reels.html'))[1])
        self.assertIn('background-color: var(--bg);', rules['body'])
        self.assertIn('background-color: var(--bg);', rules['.reel-slide'])
        self.assertIn('background-color: var(--media-black);', rules['.video-wrapper'])
        for selector in ('.action-btn', '.request-btn', '.top-nav', '.back-home',
                         '#contactSlide', '.contact-content'):
            with self.subTest(selector=selector):
                self.assertIn('var(--', rules[selector])

    def test_sub_page_play_buttons_and_back_buttons_use_tokens(self):
        """The play and back buttons were `#fff` on `#000` with a `#000` offset
        shadow: a black button with a black shadow on a dark page."""
        targets = {
            'portfolios/video_editor/video_editor_monochrome_long.html':
                ('.play-btn', '.thumbnail-wrapper'),
            'portfolios/video_editor/video_editor_monochrome_category.html':
                ('.play-btn',),
            'portfolios/video_editor/video_editor_monochrome_detail.html':
                ('.btn-back',),
        }
        for name, selectors in targets.items():
            rules = self._rules(self._inline_style(name))
            for selector in selectors:
                self.assertIn(selector, rules, '%s in %s' % (selector, name))
                with self.subTest(template=name, selector=selector):
                    self.assertIn('var(--', rules[selector])

    def test_detail_page_keeps_its_media_surfaces_black(self):
        """The player and the related thumbnails are letterboxes; they must not
        start following the palette."""
        rules = self._rules(self._inline_style(
            'portfolios/video_editor/video_editor_monochrome_detail.html'))
        for selector in ('.video-player', '.related-thumb'):
            with self.subTest(selector=selector):
                self.assertIn('background: var(--media-black);', rules[selector])

    def test_cursor_ring_hover_is_a_class_not_an_inline_colour(self):
        """The main page wrote the ring's hover colour as inline JS, which
        pinned it to black on every background."""
        source = self._template_source(self.TEMPLATES[0])
        self.assertNotIn('ring.style.borderColor', source)
        self.assertNotIn('ring.style.backgroundColor', source)
        self.assertIn("ring.classList.add('is-hover')", source)
        self.assertIn('.cursor-ring.is-hover', self._stylesheet())

    def test_creator_avatars_read_the_live_tokens(self):
        """The avatar canvas is painted from JS, so it cannot inherit a custom
        property and has to read it."""
        source = self._template_source(self.TEMPLATES[0])
        self.assertIn("getPropertyValue('--text')", source)
        self.assertIn("getPropertyValue('--bg')", source)
        self.assertNotIn("ctx.fillStyle = '#000000'", source)
        self.assertNotIn("ctx.fillStyle = '#ffffff'", source)

    # ── the editor ────────────────────────────────────────────────────────────

    EDITORS = (
        'dashboard/customize_background.html',
        'dashboard/arabic_customize_background.html',
    )

    def test_editor_preview_declares_the_theme_family(self):
        """The preview is restated per family in CSS, so it needs to know which
        family it is looking at."""
        for name in self.EDITORS:
            from django.template.loader import get_template
            source = get_template(name).template.source
            with self.subTest(template=name):
                self.assertIn('data-family="{{ background_state.family }}"', source)

    def test_editor_preview_shows_the_brutal_idiom_not_the_accent_gradient(self):
        """Monochrome's accent is its hard ink, and the editor does not offer an
        accent control for it — so the generic preview's cyan-to-pink call to
        action is a colour the published page can never have. The user picks a
        background, sees a gradient, saves, and gets something else entirely."""
        for name in self.EDITORS:
            from django.template.loader import get_template
            source = get_template(name).template.source
            with self.subTest(template=name):
                self.assertIn('.bgc-preview[data-family="brutal"] .bgc-mini-cta-final', source)
                self.assertIn('.bgc-preview[data-family="brutal"] .bgc-mini-btn', source)
                self.assertIn('background: var(--sf-hard-ink);', source)
                self.assertIn('.bgc-preview[data-family="brutal"]::before', source)

    def test_editor_hides_the_accent_readout_when_there_is_no_accent(self):
        """Grading an accent the reader cannot change is noise, and the token
        chips below it advertise a control the panel does not render."""
        for name in self.EDITORS:
            from django.template.loader import get_template
            source = get_template(name).template.source
            self.assertIn('{% if accent_supported %}', source)
            with self.subTest(template=name):
                # the readout and the four accent chips sit inside the gate
                gated = re.findall(r'{% if accent_supported %}(.*?){% endif %}', source, re.DOTALL)
                self.assertTrue(
                    any('bgc-accent-a11y' in block for block in gated),
                    'the accent contrast readout is not gated on accent_supported')
                self.assertTrue(
                    any('data-sa="trio"' in block for block in gated),
                    'the accent token chips are not gated on accent_supported')

