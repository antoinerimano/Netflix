# "Block pop-ups" (ROADMAP 9.1): was the player sandboxed when this play was reported?
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reco", "0022_ai_usage"),
    ]

    operations = [
        migrations.AddField(
            model_name="playbackoutcome",
            name="sandboxed",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
