import re

from django.db import migrations, models

SEEDED = {"videasy", "vidsrc", "vidfast", "111movies", "cinesrc", "vidcore"}  # 0012: set up by hand


def mark_scout_providers(apps, schema_editor):
    """
    Providers the scout created before this field existed. Every provider outside the hand-made
    starting set (0012) came from the scout; on a site that never ran an import, only the ones
    named in an import ("xpass: NEW, ...") or still carrying its "added by provider scout" status.
    (An import's JobRun keeps only its last 6 lines, so names can be missing from it.)
    """
    Provider = apps.get_model("users", "Provider")
    JobRun = apps.get_model("users", "JobRun")
    imports = list(JobRun.objects.filter(name="import_providers").values_list("summary", flat=True))
    keys = set()
    for summary in imports:
        keys |= set(re.findall(r"^([a-z0-9-]+): NEW,", summary or "", re.M))
    for p in Provider.objects.exclude(key__in=SEEDED):
        if imports or p.key in keys or p.status_detail.startswith("added by provider scout"):
            p.added_by_scout = True
            p.save(update_fields=["added_by_scout"])


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0027_title_trailer_clip_for"),
    ]

    operations = [
        migrations.AddField(
            model_name="provider",
            name="added_by_scout",
            field=models.BooleanField(default=False, help_text="Added by the provider scout: it stays enabled only while the scout's nightly check plays every test film on it. Untick to manage it yourself."),
        ),
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
        migrations.RunPython(mark_scout_providers, migrations.RunPython.noop),
    ]
