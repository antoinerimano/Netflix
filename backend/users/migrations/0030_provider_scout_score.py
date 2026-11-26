from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0029_provider_scout_check"),
    ]

    operations = [
        migrations.AddField(
            model_name="provider",
            name="scout_score",
            field=models.FloatField(
                blank=True, null=True,
                help_text="Share of the test titles the scout's last nightly check played (0-1). Ranks sources "
                          "that have no success rate yet, and the automatic switch tries the best ones first.",
            ),
        ),
    ]
