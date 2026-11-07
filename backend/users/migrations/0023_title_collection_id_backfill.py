"""Title.collection_id from belongs_to_collection for the titles already there (save() keeps it after)."""
from django.db import migrations


def backfill(apps, schema_editor):
    Title = apps.get_model("users", "Title")
    batch = []
    for t in Title.objects.exclude(belongs_to_collection=None).only("id", "belongs_to_collection").iterator(chunk_size=2000):
        bc = t.belongs_to_collection
        try:
            cid = int(bc.get("id")) if isinstance(bc, dict) and bc.get("id") else None
        except (TypeError, ValueError):
            cid = None
        if cid:
            t.collection_id = cid
            batch.append(t)
        if len(batch) >= 2000:
            Title.objects.bulk_update(batch, ["collection_id"])
            batch = []
    if batch:
        Title.objects.bulk_update(batch, ["collection_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0022_title_collection_id"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
