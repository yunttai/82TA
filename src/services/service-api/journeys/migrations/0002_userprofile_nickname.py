from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("journeys", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="nickname",
            field=models.CharField(default="82TA 사용자", max_length=20),
        ),
    ]
