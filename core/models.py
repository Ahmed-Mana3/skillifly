from django.db import models
from django.contrib.auth.models import AbstractUser

class CustomUser(AbstractUser):
    email = models.EmailField(max_length=254, unique=True)

    def __str__(self):
        return self.username


class Profile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.PROTECT)
    theme = models.ForeignKey(Theme, null=True, blank=True, on_delete=models.PROTECT)
    is_deleted = models.BooleanField(default=False)
    bio = models.TextField(blank=True, null=True)
    picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    phone_number = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return self.user.username


class Theme(models.Model):
    category = models.CharField(max_length=200, unique=True)
    name = models.CharField(max_length=254, unique=True)
    use_num = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.name} - {self.category}"

class Experience(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.PROTECT)
    title = models.CharField(max_length=254)
    company = models.CharField(max_length=254)
    start_date = models.DateField()
    still_working = models.BooleanField(default=False)
    end_date = models.DateField(blank=True, null=True)
    details = models.TextField(null=True, blank=True)
    duration = models.DecimalField(max_digits=3, decimal_places=1)

    def __str__(self):
        return f"{self.user} - {self.title} - {self.company}"


class Education(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.PROTECT)
    school = models.CharField(max_length=254)
    degree = models.CharField(max_length=254)
    field = models.CharField(max_length=254)
    grade_year = models.DateField()

    def __str__(self):
        return f"{self.user} - {self.field} - {self.school}"

class Skill(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.PROTECT)
    name = models.CharField(max_length=254)

    def __str__(self):
        return f"{self.name} - {self.user}"

class Project(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.PROTECT)
    title = models.CharField(max_legnth=500)
    url = models.URLField(max_legnth=500)
    details = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} - {self.user}"


class Link(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.PROTECT)
    platform = models.CharField(max_length=254)
    url = models.URLField(max_legnth=500)

    def __str__(self):
        return f"{self.platform} - {self.user}"



