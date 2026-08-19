from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0056_school_videos_from_projects'),
    ]

    operations = [
        migrations.AlterField(
            model_name='schoolstudent',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='school_students', to='core.customuser', help_text="Link to the student's portfolio account; their public Project records become their school videos"),
        ),
        migrations.AddConstraint(
            model_name='schoolstudent',
            constraint=models.UniqueConstraint(fields=('school', 'user'), name='uniq_school_student_user'),
        ),
    ]
