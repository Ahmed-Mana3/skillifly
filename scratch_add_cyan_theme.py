import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skillifly.settings')
django.setup()

from core.models import Theme, Category, Profile, CustomUser

# Get or create the 'Video Editor' category
category, _ = Category.objects.get_or_create(name='Video Editor')

# Create the theme
theme, created = Theme.objects.get_or_create(name='Cyan', category=category)

if created:
    print("Theme 'Cyan' created successfully.")
else:
    print("Theme 'Cyan' already exists.")

# Assign it to a test user if present
test_user = CustomUser.objects.filter(username='testuser').first()
if test_user:
    profile = test_user.profile
    profile.theme = theme
    profile.save()
    print(f"Assigned 'Cyan' theme to test user '{test_user.username}'.")
else:
    print("Could not find test user 'testuser'. Please create one if needed.")
