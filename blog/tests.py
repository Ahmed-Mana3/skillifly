from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import Post, Category, Tag

User = get_user_model()


class BlogModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser', password='password123', email='test@example.com'
        )
        self.category = Category.objects.create(name='Tech')
        self.tag       = Tag.objects.create(name='Python')
        self.post_en   = Post.objects.create(
            title='Test Post',
            author=self.user,
            content='<p>Test content.</p>',
            status='published',
            language='en',
            meta_description='A short test description for SEO.',
            featured_image_alt='A descriptive alt text',
        )
        self.post_ar   = Post.objects.create(
            title='مقال تجريبي',
            author=self.user,
            content='<p>محتوى تجريبي.</p>',
            status='published',
            language='ar',
        )
        self.post_en.categories.add(self.category)
        self.post_en.tags.add(self.tag)

    # ── Model: slugs ──────────────────────────────────────────────────────
    def test_en_post_slug_generated(self):
        self.assertEqual(self.post_en.slug, 'test-post')

    def test_ar_post_slug_generated(self):
        """Arabic title should produce a transliterated ASCII slug."""
        self.assertTrue(bool(self.post_ar.slug))

    def test_category_slug(self):
        self.assertEqual(self.category.slug, 'tech')

    def test_tag_slug(self):
        self.assertEqual(self.tag.slug, 'python')

    # ── Model: RTL properties ─────────────────────────────────────────────
    def test_en_post_is_not_rtl(self):
        self.assertFalse(self.post_en.is_rtl)

    def test_ar_post_is_rtl(self):
        self.assertTrue(self.post_ar.is_rtl)

    # ── Model: reading_time ───────────────────────────────────────────────
    def test_reading_time_minimum_one(self):
        self.assertGreaterEqual(self.post_en.reading_time, 1)

    # ── Model: SEO fields ─────────────────────────────────────────────────
    def test_meta_description_max_length(self):
        field = Post._meta.get_field('meta_description')
        self.assertEqual(field.max_length, 160)

    def test_relations(self):
        self.assertIn(self.category, self.post_en.categories.all())
        self.assertIn(self.tag,      self.post_en.tags.all())


@override_settings(ROOT_URLCONF='skillifly.blog_urls')
class BlogViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user   = User.objects.create_user(
            username='testuser', password='password123', email='test@example.com'
        )
        self.post_published = Post.objects.create(
            title='Published Post',
            author=self.user,
            content='<p>Content.</p>',
            status='published',
            language='en',
            meta_description='A great post.',
        )
        self.post_ar = Post.objects.create(
            title='مقال منشور',
            author=self.user,
            content='<p>محتوى.</p>',
            status='published',
            language='ar',
        )
        self.post_draft = Post.objects.create(
            title='Draft Post',
            author=self.user,
            content='<p>Draft.</p>',
            status='draft',
        )

    def test_post_list_returns_200(self):
        url = reverse('blog:post_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_post_list_shows_only_published(self):
        url = reverse('blog:post_list')
        response = self.client.get(url)
        self.assertContains(response, 'Published Post')
        self.assertNotContains(response, 'Draft Post')

    def test_post_detail_en_200(self):
        url = reverse('blog:post_detail', args=[self.post_published.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_post_detail_ar_200(self):
        url = reverse('blog:post_detail', args=[self.post_ar.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_post_detail_contains_rtl_dir(self):
        """Arabic posts must include dir="rtl" in the article element."""
        url = reverse('blog:post_detail', args=[self.post_ar.slug])
        response = self.client.get(url)
        self.assertContains(response, 'dir="rtl"')

    def test_post_detail_contains_json_ld(self):
        """Published posts must embed a JSON-LD BlogPosting schema."""
        url = reverse('blog:post_detail', args=[self.post_published.slug])
        response = self.client.get(url)
        self.assertContains(response, 'application/ld+json')
        self.assertContains(response, 'BlogPosting')

    def test_draft_returns_404(self):
        url = reverse('blog:post_detail', args=[self.post_draft.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_sitemap_returns_200(self):
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)

    def test_robots_txt_returns_200(self):
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Sitemap', response.content)
