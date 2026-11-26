from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0030_provider_scout_score"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="autoplay_next",
            field=models.BooleanField(default=True),
        ),
    ]
