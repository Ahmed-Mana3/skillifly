from django.db import models
from django.contrib.auth import get_user_model
from django.utils.text import slugify as django_slugify
from ckeditor_uploader.fields import RichTextUploadingField

User = get_user_model()


def _slugify(text):
    """
    Generate a URL-safe slug from any text including Arabic.
    Uses python-slugify when available so Arabic words are
    transliterated; falls back to Django's built-in slugify.
    """
    try:
        from slugify import slugify as ps_slugify
        return ps_slugify(text)
    except ImportError:
        return django_slugify(text)


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        verbose_name_plural = "categories"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _slugify(self.name)
            if not self.slug:
                import uuid
                self.slug = str(uuid.uuid4())[:8]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Tag(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _slugify(self.name)
            if not self.slug:
                import uuid
                self.slug = str(uuid.uuid4())[:8]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Post(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('published', 'Published'),
    )
    LANGUAGE_CHOICES = (
        ('en', 'English'),
        ('ar', 'العربية'),
    )

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True, blank=True, allow_unicode=True)
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blog_posts')
    content = RichTextUploadingField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default='en')
    featured_image = models.ImageField(upload_to='blog_images/', blank=True, null=True)
    featured_image_alt = models.CharField(max_length=200, blank=True, help_text='Alt text for featured image (important for SEO)')
    meta_description = models.CharField(max_length=160, blank=True, help_text='Max 160 characters for best SEO results')
    canonical_url = models.URLField(blank=True, help_text='Override the canonical URL if this content exists elsewhere')

    categories = models.ManyToManyField(Category, related_name='posts', blank=True)
    tags = models.ManyToManyField(Tag, related_name='posts', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def is_rtl(self):
        """True when the post language is right-to-left."""
        return self.language == 'ar'

    @property
    def reading_time(self):
        """Estimated reading time in minutes."""
        from django.utils.html import strip_tags
        word_count = len(strip_tags(self.content).split())
        minutes = max(1, round(word_count / 200))
        return minutes

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('blog:post_detail', args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
