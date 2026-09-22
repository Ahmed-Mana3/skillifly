from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0071_agentmessage_user_rating"),
    ]

    operations = [
        migrations.DeleteModel(
            name="PdfExportJob",
        ),
    ]