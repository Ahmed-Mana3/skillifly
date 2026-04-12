from django.contrib import admin
from core.models import CustomUser, Category, Theme, Profile, PersonalInfo, Experience, Education, Skill, Project, Link, Subscription, UserPayment, DiscountCode

# Register your models here.
admin.site.register(CustomUser)
admin.site.register(Category)
admin.site.register(Theme)
admin.site.register(Profile)
admin.site.register(PersonalInfo)
admin.site.register(Experience)
admin.site.register(Education)
admin.site.register(Skill)
admin.site.register(Project)
admin.site.register(Link)
admin.site.register(Subscription)
admin.site.register(UserPayment)
admin.site.register(DiscountCode)
