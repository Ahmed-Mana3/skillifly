from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_customdomain_dns_verified_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="section_order",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Ordered list of section keys for portfolio display.",
            ),
        ),
    ]
