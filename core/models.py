from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import date
from django.utils.text import slugify
import uuid

# 1. Custom User Model
class CustomUser(AbstractUser):
    email = models.EmailField(max_length=254, unique=True)

    def __str__(self):
        return self.username

# 1b. User Account Type (kept separate from CustomUser so auth data stays clean)
class UserAccount(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ('editor', 'Editor'),
        ('client', 'Client'),
    ]
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='user_account')
    account_type = models.CharField(
        max_length=10,
        choices=ACCOUNT_TYPE_CHOICES,
        default='editor',
        help_text="editor = builds a portfolio, client = hires editors",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Account"
        verbose_name_plural = "User Accounts"

    def __str__(self):
        return f"{self.user.username} ({self.account_type})"

class EmailOTP(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='email_otp')
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        from django.utils import timezone
        import datetime
        return timezone.now() > self.created_at + datetime.timedelta(minutes=10)

# 2. Categories for Themes (e.g., Creative, Corporate, Minimal)
class Category(models.Model):
    name = models.CharField(max_length=200, unique=True)
    
    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name

# 3. Themes available for the Portfolio
class Theme(models.Model):
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=254)
    use_num = models.IntegerField(default=0)
    preview_image = models.ImageField(upload_to='themes/', blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.category})"

# 4. User Profile (Extends User Data)
class Profile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="profile")
    theme = models.ForeignKey(Theme, null=True, blank=True, on_delete=models.SET_NULL)
    is_deleted = models.BooleanField(default=False)
    bio = models.TextField(blank=True, null=True)
    picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True)
    visits = models.PositiveIntegerField(default=0)
    is_public = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.user.username}"


class PersonalInfo(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="personal_info")
    full_name = models.CharField(max_length=254)
    title =  models.CharField(max_length=500)
    email = models.EmailField()
    phone =  models.CharField(max_length=20)
    bio = models.TextField()
    booking_url = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"PersonalInfo: {self.full_name}"

# 5. Work Experience
class Experience(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="experiences")
    title = models.CharField(max_length=254)
    company = models.CharField(max_length=254)
    start_date = models.DateField()
    still_working = models.BooleanField(default=False)
    end_date = models.DateField(blank=True, null=True)
    duration = models.DecimalField(max_digits=3 ,decimal_places=1)
    details = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} at {self.company}"

# 6. Education
class Education(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="education")
    school = models.CharField(max_length=254)
    degree = models.CharField(max_length=254)
    field = models.CharField(max_length=254)
    grade_year = models.DateField()

    def __str__(self):
        return f"{self.degree} - {self.school}"

# 7. Skills
class Skill(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="skills")
    name = models.CharField(max_length=254)


    def __str__(self):
        return self.name

# 8. Portfolio Projects
class ProjectCategory(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="project_categories")
    name = models.CharField(max_length=254)
    thumbnail = models.ImageField(upload_to='project_categories/', blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Project Categories"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.user.username})"

class Project(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="projects")
    category = models.ForeignKey(ProjectCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='projects')
    title = models.CharField(max_length=500)
    url = models.CharField(max_length=500, blank=True, null=True)
    details = models.TextField(null=True, blank=True)
    image = models.ImageField(upload_to='projects/', blank=True, null=True)
    video_type = models.CharField(
        max_length=10, 
        choices=[('long', 'Long Video'), ('reel', 'Short/Reel')], 
        default='long'
    )
    slug = models.SlugField(max_length=550, blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.title) or "video"
            # Ensure slug is unique per user
            unique_slug = base_slug
            counter = 1
            while Project.objects.filter(user=self.user, slug=unique_slug).exists():
                unique_slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = unique_slug
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.title} ({self.get_video_type_display()})"

    @property
    def youtube_id(self):
        import re
        if not self.url: return None
        if 'youtu' in self.url:
            m = re.search(r'(?:youtu\.be\/|youtube\.com\/(?:[^\/]+\/.+\/|(?:v|e(?:mbed)?)\/|.*[?&]v=))([^"&?\/\s]{11})', self.url)
            return m.group(1) if m else None
        return None

    @property
    def vimeo_id(self):
        import re
        if not self.url: return None
        if 'vimeo' in self.url:
            m = re.search(r'vimeo\.com\/(?:video\/)?([0-9]+)', self.url)
            return m.group(1) if m else None
        return None
# 9. Social/External Links
class Link(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="links")
    platform = models.CharField(max_length=254)
    url = models.CharField(max_length=500)

    def __str__(self):
        return f"{self.platform}: {self.user.username}"

class Subscription(models.Model):
    duration = models.IntegerField()
    days = models.IntegerField()
    name = models.CharField(max_length=254)

    def __str__(self):
        return f"{self.name}: {self.duration}"

class UserPayment(models.Model):
    user = models.ForeignKey(CustomUser, null=True, on_delete=models.SET_NULL)
    subscription = models.ForeignKey(Subscription, blank=True, null=True, on_delete=models.SET_NULL)
    amount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, default='pending')
    fawaterk_intent_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    discount_code_used = models.CharField(max_length=50, null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        user_name = self.user.username if self.user else "Unknown User"
        sub_duration = self.subscription.duration if self.subscription else "No Subscription"
        return f"{user_name} - {sub_duration} - {self.status}"

    @property
    def is_active(self):
        from django.utils import timezone
        from datetime import timedelta
        if self.status == 'paid' and self.subscription:
            expiration_date = self.date + timedelta(days=self.subscription.days)
            return expiration_date > timezone.now()
        return False
        
class DiscountCode(models.Model):
    code = models.CharField(max_length=50, unique=True)
    discount_percentage = models.PositiveIntegerField(default=0, help_text="Percentage discount (0-100)")
    owner = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="owned_coupons", help_text="The user who owns/generated this coupon")
    usage_count = models.PositiveIntegerField(default=0, help_text="Number of times this coupon has been used successfully")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.code = self.code.upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} ({self.discount_percentage}%) - Owner: {self.owner.username}"



class ManualPayment(models.Model):
    """Tracks InstaPay / Vodafone Cash receipt submissions verified by Gemini AI."""
    STATUS_CHOICES = [
        ('pending',  'Pending Verification'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
        ('needs_review', 'Needs Manual Review'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('vodafone', 'Vodafone Cash'),
        ('instapay', 'InstaPay'),
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='manual_payments')
    plan_type = models.CharField(max_length=20)                   # 'monthly' | 'pro_monthly' | 'pro_annual'
    amount_expected = models.DecimalField(max_digits=8, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='vodafone')
    sender_identifier = models.CharField(max_length=100)          # phone number or instapay handle
    receipt_image = models.ImageField(upload_to='receipts/')
    status = models.CharField(max_length=20, default='pending', choices=STATUS_CHOICES)
    rejection_reason = models.TextField(blank=True, null=True)
    discount_code_used = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} | {self.payment_method} | {self.status}"


class PdfExportJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="pdf_exports")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    source_hash = models.CharField(max_length=64, db_index=True)
    pdf_file = models.FileField(upload_to="exports/pdfs/", blank=True, null=True)
    error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class SiteSettings(models.Model):
    banner_discount_percentage = models.PositiveIntegerField(default=25, help_text="Discount percentage to show in the dashboard banner.")
    banner_coupon_code = models.CharField(max_length=50, default="SKILLIFLY2026", help_text="Coupon code to show in the banner.")
    banner_is_active = models.BooleanField(default=True, help_text="Whether the payment banner is enabled globally.")

    class Meta:
        verbose_name = "Site Settings"
        verbose_name_plural = "Site Settings"

    def __str__(self):
        return "Global Site Settings"


class Review(models.Model):
    """Website/platform reviews shown on the Skillifly landing page."""
    reviewer = models.ForeignKey(CustomUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="website_reviews", help_text="The authenticated user who submitted this review (null = admin/manual)")
    user_name = models.CharField(max_length=254)
    user_title = models.CharField(max_length=254, blank=True, null=True, help_text="e.g. Video Editor, Frontend Developer")
    user_image = models.ImageField(upload_to='reviews/', blank=True, null=True)
    content = models.TextField()
    rating = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 to 5 stars",
    )
    is_featured = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text="Order of appearance on landing page")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-created_at']

    def __str__(self):
        return f"Review by {self.user_name}"

    @property
    def image_url(self):
        if self.user_image and hasattr(self.user_image, 'url'):
            return self.user_image.url
        if self.reviewer_id:
            profile = getattr(self.reviewer, 'profile', None)
            if profile is not None and profile.picture and hasattr(profile.picture, 'url'):
                return profile.picture.url
        return None

    @property
    def image_name(self):
        if self.user_image:
            return self.user_image.name
        if self.reviewer_id:
            profile = getattr(self.reviewer, 'profile', None)
            if profile is not None and profile.picture:
                return profile.picture.name
        preview = getattr(self, 'preview_image', None)
        if preview:
            return preview
        return None

    @property
    def initials(self):
        if not self.user_name:
            return "SF"
        parts = self.user_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return self.user_name[:2].upper()

class ClientReview(models.Model):
    """Reviews clients leave on an editor's portfolio."""
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="reviews", help_text="The portfolio owner this review is about")
    reviewer = models.ForeignKey(CustomUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews_given", help_text="The client who wrote this review")
    user_name = models.CharField(max_length=254)
    user_title = models.CharField(max_length=254, blank=True, null=True, help_text="e.g. Video Editor, Frontend Developer")
    user_image = models.ImageField(upload_to='reviews/', blank=True, null=True)
    content = models.TextField()
    rating = models.PositiveIntegerField(
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="1 to 5 stars",
    )
    is_featured = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text="Order of appearance on the portfolio")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-created_at']

    def __str__(self):
        return f"Review by {self.user_name}"

    @property
    def image_url(self):
        if self.user_image and self.user_image.storage.exists(self.user_image.name):
            return self.user_image.url
        if self.reviewer_id:
            profile = getattr(self.reviewer, 'profile', None)
            if profile is not None and profile.picture and profile.picture.storage.exists(profile.picture.name):
                return profile.picture.url
        return None

    @property
    def image_name(self):
        if self.user_image and self.user_image.storage.exists(self.user_image.name):
            return self.user_image.name
        if self.reviewer_id:
            profile = getattr(self.reviewer, 'profile', None)
            if profile is not None and profile.picture and profile.picture.storage.exists(profile.picture.name):
                return profile.picture.name
        preview = getattr(self, 'preview_image', None)
        if preview:
            return preview
        return None

    @property
    def initials(self):
        if not self.user_name:
            return "SF"
        parts = self.user_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        return self.user_name[:2].upper()

# 11. Showcase / Live Examples
class Showcase(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="showcase")
    title = models.CharField(max_length=200, blank=True, help_text="Optional custom title for the showcase")
    description = models.TextField(blank=True, help_text="Short description of the user or their work")
    preview_image = models.ImageField(upload_to='showcase/', blank=True, null=True, help_text="Custom preview image (defaults to profile pic if empty)")
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-created_at']


# 12. SEO Settings
class SEOSettings(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="seo_settings")
    meta_title = models.CharField(max_length=255, blank=True, null=True, help_text="Custom browser title tag")
    meta_description = models.TextField(blank=True, null=True, help_text="Custom meta description for search engines")
    meta_keywords = models.CharField(max_length=500, blank=True, null=True, help_text="Comma-separated keywords")
    
    # social sharing
    og_title = models.CharField(max_length=255, blank=True, null=True, help_text="Title for social media sharing")
    og_description = models.TextField(blank=True, null=True, help_text="Description for social media sharing")
    og_image = models.ImageField(upload_to='seo_images/', blank=True, null=True, help_text="Custom image for social media sharing")

    def __str__(self):
        return f"SEO Settings: {self.user.username}"

class CustomDomain(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="custom_domain")
    domain = models.CharField(max_length=255, blank=True, default='', help_text="The custom domain name (e.g., example.com)")
    is_active = models.BooleanField(default=False)
    dns_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Only enforce uniqueness on non-empty domains so multiple users
        # can have an empty domain (no domain set yet).
        constraints = [
            models.UniqueConstraint(
                fields=['domain'],
                condition=models.Q(domain__gt=''),
                name='unique_nonempty_domain',
            )
        ]

    def __str__(self):
        return f"{self.domain} ({self.user.username})"

class AnalyticsVisit(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="analytics_visits")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    country = models.CharField(max_length=100, default="Unknown")
    city = models.CharField(max_length=100, default="Unknown")
    user_agent = models.TextField(null=True, blank=True)
    referer = models.TextField(null=True, blank=True)
    session_id = models.CharField(max_length=255, db_index=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Visit to {self.user.username} from {self.country}"

class AnalyticsEvent(models.Model):
    visit = models.ForeignKey(AnalyticsVisit, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=50) # e.g., 'project_click'
    project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} on {self.visit.user.username}'s portfolio"

class Creator(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="creators")
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to='creators/', blank=True, null=True)
    url = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"{self.name} (for {self.user.username})"

class AffiliateProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="affiliate_profile")
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_earned = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Affiliate: {self.user.username} (Balance: {self.balance} EGP)"

