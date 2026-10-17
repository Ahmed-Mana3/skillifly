from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0084_theme_display_order'),
    ]

    operations = [
        migrations.CreateModel(
            name='HeardAboutResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=20)),
                ('detail', models.CharField(blank=True, default='', help_text="Free text, used for 'Other' and 'A friend'.", max_length=200)),
                ('xp_awarded', models.PositiveSmallIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='heard_about_response', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'How-they-heard answer',
                'verbose_name_plural': 'How-they-heard answers',
                'ordering': ['-created_at'],
            },
        ),
    ]
