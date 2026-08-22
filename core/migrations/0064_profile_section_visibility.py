from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0063_alter_profile_section_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='section_visibility',
            field=models.JSONField(blank=True, default=dict, help_text='Map of section key -> bool controlling portfolio section visibility'),
        ),
    ]
