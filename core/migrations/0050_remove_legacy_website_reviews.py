# Generated manually after 0049 moved platform reviews into WebsiteReview.

from django.db import migrations


def delete_legacy_website_reviews(apps, schema_editor):
    Review = apps.get_model('core', 'Review')
    Review.objects.filter(user__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0049_websitereview'),
    ]

    operations = [
        migrations.RunPython(delete_legacy_website_reviews, migrations.RunPython.noop),
    ]
