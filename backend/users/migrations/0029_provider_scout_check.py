from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0028_profile_appearance"),
    ]

    operations = [
        migrations.AddField(
            model_name="provider",
            name="disabled_by_scout",
            field=models.BooleanField(default=False, help_text="Turned off by the scout (a test film didn't play); back on when they all play again."),
        ),
        migrations.AddField(
            model_name="provider",
            name="scout_check",
            field=models.CharField(blank=True, default="", help_text="The scout's last nightly playback check.", max_length=300),
        ),
    ]
