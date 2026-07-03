# Migration to fix the CustomDomain.domain unique constraint.
# The original field had unique=True (enforced at DB level for ALL values,
# including empty strings), which caused IntegrityError 500s when multiple
# users visited /dashboard/domain/ for the first time (get_or_create tried
# to INSERT domain='' more than once, violating the UNIQUE constraint).
#
# Fix: drop the global unique index and add a partial unique constraint that
# only applies to non-empty domain values.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_alter_review_options_review_order'),
    ]

    operations = [
        # 1. Remove the old column-level UNIQUE constraint and make the field
        #    blank-able with an empty-string default.
        migrations.AlterField(
            model_name='customdomain',
            name='domain',
            field=models.CharField(
                max_length=255,
                blank=True,
                default='',
                help_text='The custom domain name (e.g., example.com)',
            ),
        ),
        # 2. Add a partial unique constraint: only non-empty domains must be unique.
        migrations.AddConstraint(
            model_name='customdomain',
            constraint=models.UniqueConstraint(
                fields=['domain'],
                condition=models.Q(domain__gt=''),
                name='unique_nonempty_domain',
            ),
        ),
    ]
