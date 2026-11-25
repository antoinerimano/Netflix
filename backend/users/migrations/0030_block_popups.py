# "Block pop-ups" (ROADMAP 9.1): the profile's switch (on by default) and whether each provider's
# player plays in a sandboxed iframe (the provider scout's check).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0029_provider_scout_check"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="block_popups",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="provider",
            name="sandbox_ok",
            field=models.CharField(
                choices=[("yes", "Yes"), ("no", "No"), ("unknown", "Unknown")], default="unknown",
                help_text="Plays with pop-ups blocked (sandboxed iframe). Set by the provider scout.", max_length=10,
            ),
        ),
    ]
