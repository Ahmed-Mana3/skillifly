import email
from django.db.models import CharField
from unicodedata import decimal
from django.db import models
from django.contrib.auth.models import AbstractUser
from datetime import date

# 1. Custom User Model
class CustomUser(AbstractUser):
    email = models.EmailField(max_length=254, unique=True)

    def __str__(self):
        return self.username

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
    name = models.CharField(max_length=254, unique=True)
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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile: {self.user.username}"


class PersonalInfo(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name="personal_info")
    full_name = models.CharField(max_length=254)
    title =  models.CharField(max_length=500)
    email = models.EmailField()
    phone =  models.CharField(max_length=20)
    bio = models.TextField()

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
    level = models.IntegerField(default=100) 

    def __str__(self):
        return self.name

# 8. Portfolio Projects
class Project(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="projects")
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=500, blank=True, null=True)
    details = models.TextField(null=True, blank=True)
    image = models.ImageField(upload_to='projects/', blank=True, null=True)

    def __str__(self):
        return self.title

# 9. Social/External Links
class Link(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="links")
    platform = models.CharField(max_length=254)
    url = models.URLField(max_length=500)

    def __str__(self):
        return f"{self.platform}: {self.user.username}"