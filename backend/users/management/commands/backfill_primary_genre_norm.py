from django.core.management.base import BaseCommand
from django.db import transaction
from users.models import Title

BATCH = 5000

def norm_primary(genre_val):
    """
    genre_val est souvent une string: "Drama, Action, Thriller"
    ou parfois un truc JSON/string bizarre.
    On prend le 1er genre et on normalise.
    """
    if not genre_val:
        return ""

    # si c'est déjà une liste python (rare)
    if isinstance(genre_val, (list, tuple)):
        g = str(genre_val[0]) if genre_val else ""
        return g.strip().lower()

    s = str(genre_val).strip()

    # si c'est une string du genre "['Drama','Action']" -> on la traite cheap
    if s.startswith("[") and "," in s:
        s = s.strip("[]")
        # enlève quotes
        s = s.replace("'", "").replace('"', "")

    # prend avant la virgule
    primary = s.split(",")[0].strip().lower()

    # petite normalisation optionnelle
    # ex: "sci fi" -> "science fiction"
    if primary in ("sci fi", "sci-fi", "scifi"):
        primary = "science fiction"

    return primary


class Command(BaseCommand):
    help = "Populate Title.primary_genre_norm from Title.genre (in batches)."

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=BATCH)
        parser.add_argument("--only-missing", action="store_true", help="Only update rows where primary_genre_norm is empty")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        batch = opts["batch"]
        only_missing = opts["only_missing"]
        dry = opts["dry_run"]

        qs = Title.objects.all().only("id", "genre", "primary_genre_norm").order_by("id")
        if only_missing:
            qs = qs.filter(primary_genre_norm="")

        total = qs.count()
        self.stdout.write(self.style.SUCCESS(f"[start] total={total} batch={batch} only_missing={only_missing} dry={dry}"))

        buf = []
        done = 0
        changed = 0

        for t in qs.iterator(chunk_size=batch):
            done += 1
            newv = norm_primary(t.genre)
            if t.primary_genre_norm != newv:
                t.primary_genre_norm = newv
                buf.append(t)

            if len(buf) >= batch:
                if not dry:
                    Title.objects.bulk_update(buf, ["primary_genre_norm"], batch_size=batch)
                changed += len(buf)
                self.stdout.write(f"[progress] done={done}/{total} changed={changed}")
                buf = []

        if buf:
            if not dry:
                Title.objects.bulk_update(buf, ["primary_genre_norm"], batch_size=batch)
            changed += len(buf)

        self.stdout.write(self.style.SUCCESS(f"[done] done={done} changed={changed}"))
