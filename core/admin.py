from django.contrib import admin
from .models import CustomUser, Category, Theme, Profile, Experience, Education, Skill, Project, Link

# Register your models here.
admin.site.register(CustomUser)
admin.site.register(Category)
admin.site.register(Theme)
admin.site.register(Profile)
admin.site.register(Experience)
admin.site.register(Education)
admin.site.register(Skill)
admin.site.register(Project)
admin.site.register(Link)
