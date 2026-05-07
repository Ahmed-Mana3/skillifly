from django.db import migrations


def ensure_cinematic_theme(apps, schema_editor):
    Category = apps.get_model("core", "Category")
    Theme = apps.get_model("core", "Theme")

    category, _ = Category.objects.get_or_create(name="Video Editor")
    Theme.objects.get_or_create(category=category, name="Cinematic")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0035_creator_delete_collaborator"),
    ]

    operations = [
        migrations.RunPython(ensure_cinematic_theme, migrations.RunPython.noop),
    ]

