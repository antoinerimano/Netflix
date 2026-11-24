from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0028_profile_appearance"),
    ]

    operations = [
        migrations.AddField(
            model_name="provider",
            name="scout_check",
            field=models.CharField(blank=True, default="", help_text="The scout's last nightly playback check.", max_length=300),
        ),
    ]
