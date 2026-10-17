"""Seed the Space video-editor theme (idempotent).

Run from the project directory:

    D:\\skillifly_dev\\venv\\Scripts\\python.exe scratch_add_space_theme.py

Creates the Video Editor category if missing, then the Theme row whose name
resolves to templates/portfolios/video_editor/video_editor_space*.html.
If a legacy "Bozo" row exists it is renamed in place so that profiles and any
other foreign keys keep pointing at it. Attaches media/themes/space.jpg as the
gallery preview when that file exists.
"""
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'skillifly.settings')
django.setup()

from django.conf import settings  # noqa: E402

from core.models import Category, Theme  # noqa: E402

category, _ = Category.objects.get_or_create(name='Video Editor')

legacy = Theme.objects.filter(name='Bozo').first()
if legacy is not None:
    legacy.name = 'Space'
    legacy.category = category
    legacy.save(update_fields=['name', 'category'])
    theme, created = legacy, False
else:
    theme, created = Theme.objects.get_or_create(name='Space', category=category)

preview_rel = 'themes/space.jpg'
preview_abs = os.path.join(settings.MEDIA_ROOT, preview_rel)
if os.path.exists(preview_abs) and theme.preview_image.name != preview_rel:
    theme.preview_image = preview_rel
    theme.save(update_fields=['preview_image'])

print('Space theme', 'created' if created else 'already present', '(id=%s)' % theme.id,
      '| preview:', theme.preview_image.name or 'none')
