# Anime / K-drama sections (ROADMAP 9.5): Title.section, filled once here for the titles already
# in the catalog (users/sections.py, from data we already have: no TMDB call), and the scout's
# anime result per provider.

from django.db import migrations, models

BATCH = 2000


def fill_sections(apps, schema_editor):
    from users.sections import SOURCE_FIELDS, title_section

    Title = apps.get_model("users", "Title")
    last = 0
    while True:
        rows = list(Title.objects.filter(id__gt=last).order_by("id").only("id", *SOURCE_FIELDS)[:BATCH])
        if not rows:
            return
        last = rows[-1].id
        changed = []
        for t in rows:
            section = title_section(t.type, t.genre, t.original_language, t.production_countries, t.keywords)
            if section:
                t.section = section
                changed.append(t)
        if changed:
            Title.objects.bulk_update(changed, ["section"], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0032_title_services_charts'),
    ]

    operations = [
        migrations.AddField(
            model_name='title',
            name='section',
            field=models.CharField(blank=True, db_index=True, default='', max_length=8),
        ),
        migrations.AddField(
            model_name='provider',
            name='scout_anime',
            field=models.FloatField(blank=True, help_text="Share of the anime test episodes (One Piece, late seasons too) the scout's last nightly check played (0-1, empty: not tested). For anime, the sources that missed them are tried last.", null=True),
        ),
        migrations.RunPython(fill_sections, migrations.RunPython.noop),
    ]
