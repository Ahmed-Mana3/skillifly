import django.db.models.deletion

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0078_profile_section_names'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentTrackingEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_id', models.CharField(db_index=True, max_length=255)),
                ('event_type', models.CharField(choices=[('page_view', 'Page View'), ('click', 'Click')], default='page_view', max_length=20)),
                ('page', models.CharField(db_index=True, max_length=60)),
                ('action', models.CharField(blank=True, default='', max_length=100)),
                ('plan_type', models.CharField(blank=True, default='', max_length=20)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('user_agent', models.TextField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payment_tracking_events', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Payment tracking event',
                'verbose_name_plural': 'Payment tracking events',
                'ordering': ['-created_at'],
            },
        ),
    ]