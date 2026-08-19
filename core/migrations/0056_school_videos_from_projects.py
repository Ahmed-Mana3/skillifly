# Manually written: school videos now come from Project records.

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0055_remove_schoolvideo_duration_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='schoolstudent',
            name='user',
            field=models.ForeignKey(blank=True, help_text="Link to the student's portfolio account; their public Project records become their school videos", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='school_students', to='core.customuser'),
        ),
        migrations.RemoveField(
            model_name='schoolvideocomment',
            name='video',
        ),
        migrations.RemoveField(
            model_name='schoolvideorating',
            name='video',
        ),
        migrations.AddField(
            model_name='schoolvideocomment',
            name='project',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, related_name='school_video_comments', to='core.project'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='schoolvideorating',
            name='project',
            field=models.ForeignKey(default=1, on_delete=django.db.models.deletion.CASCADE, related_name='school_video_ratings', to='core.project'),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name='schoolvideocomment',
            name='stars',
            field=models.PositiveIntegerField(default=5, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)]),
        ),
        migrations.AlterField(
            model_name='schoolvideorating',
            name='value',
            field=models.PositiveIntegerField(validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)]),
        ),
        migrations.DeleteModel(
            name='SchoolVideo',
        ),
    ]
