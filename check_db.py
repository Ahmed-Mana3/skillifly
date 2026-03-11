import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skillifly.settings')
django.setup()

from core.models import Category, Theme

with open('db_results.txt', 'w', encoding='utf-8') as f:
    f.write("CATEGORIES:\n")
    for c in Category.objects.all():
        f.write(f"ID: {c.id} | Name: '{c.name}'\n")

    f.write("\nTHEMES:\n")
    for t in Theme.objects.all():
        f.write(f"Name: '{t.name}' | Category: '{t.category.name}'\n")
