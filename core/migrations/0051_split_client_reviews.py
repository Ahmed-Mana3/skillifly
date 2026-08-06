# Generated manually. Reverses the direction of 0049/0050: website reviews stay
# in the original Review table, client reviews move into a new ClientReview table
# (including the theme-preview reviews seeded for the mock user).

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def split_reviews(apps, schema_editor):
    Review = apps.get_model('core', 'Review')
    ClientReview = apps.get_model('core', 'ClientReview')
    WebsiteReview = apps.get_model('core', 'WebsiteReview')

    # 1. Restore website reviews back into the original Review table.
    for wr in WebsiteReview.objects.all():
        Review.objects.create(
            reviewer_id=wr.reviewer_id,
            user_name=wr.user_name,
            user_title=wr.user_title,
            user_image=wr.user_image.name if wr.user_image else None,
            content=wr.content,
            rating=wr.rating,
            is_featured=wr.is_featured,
            order=wr.order,
            created_at=wr.created_at,
        )

    # 2. Move client reviews into the new ClientReview table.
    records = []
    for r in Review.objects.filter(user__isnull=False):
        records.append(ClientReview(
            user_id=r.user_id,
            reviewer_id=r.reviewer_id,
            user_name=r.user_name,
            user_title=r.user_title,
            user_image=r.user_image.name if r.user_image else None,
            content=r.content,
            rating=r.rating,
            is_featured=r.is_featured,
            order=r.order,
            created_at=r.created_at,
        ))
    ClientReview.objects.bulk_create(records)

    # 3. Remove the client reviews that were moved to the new table.
    Review.objects.filter(user__isnull=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0050_remove_legacy_website_reviews'),
    ]

    operations = [
        migrations.AlterField(
            model_name='review',
            name='reviewer',
            field=models.ForeignKey(blank=True, help_text='The authenticated user who submitted this review (null = admin/manual)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='website_reviews', to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name='ClientReview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_name', models.CharField(max_length=254)),
                ('user_title', models.CharField(blank=True, help_text='e.g. Video Editor, Frontend Developer', max_length=254, null=True)),
                ('user_image', models.ImageField(blank=True, null=True, upload_to='reviews/')),
                ('content', models.TextField()),
                ('rating', models.PositiveIntegerField(default=5, help_text='1 to 5 stars')),
                ('is_featured', models.BooleanField(default=True)),
                ('order', models.PositiveIntegerField(default=0, help_text='Order of appearance on the portfolio')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewer', models.ForeignKey(blank=True, help_text='The client who wrote this review', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviews_given', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(help_text='The portfolio owner this review is about', on_delete=django.db.models.deletion.CASCADE, related_name='reviews', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['order', '-created_at'],
            },
        ),
        migrations.RunPython(split_reviews, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='review',
            name='user',
        ),
        migrations.DeleteModel(
            name='WebsiteReview',
        ),
    ]
