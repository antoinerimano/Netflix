"""
Remove the old trailers/{tmdb_id}.mp4 preview clips from the titles (no preview rather than a wrong one):

    docker compose exec -T backend python manage.py clear_legacy_clips --dry-run
    docker compose exec -T backend python manage.py clear_legacy_clips

The old server script (tools/add_trailer_to_cdn.py, removed in f460f06) named a clip after the
TMDB id only, and TMDB numbers movies and shows separately: a movie and a show with the same id
(Breaking Bad, show 1396, and movie 1396) shared one file, the second one made overwrote the
first. It also took the first YouTube "Trailer" TMDB listed (fan uploads, later seasons). So any
of these clips may be another title's. Cleared, the titles show their picture until trailer-worker/
makes them a checked clip: export_trailer_jobs lists them again (they still have a trailer_url).

The files stay on the CDN, nothing is deleted there. --shared-only: only the ids a movie and a show
share (the clips that are surely wrong for one of the two).
"""
from django.core.management.base import BaseCommand
from django.db.models import Count

from users.models import Title


class Command(BaseCommand):
    help = "Remove the old trailers/{tmdb_id}.mp4 preview clips (they may be another title's)."

    def add_arguments(self, p):
        p.add_argument("--dry-run", action="store_true", help="count and list, change nothing")
        p.add_argument("--shared-only", action="store_true",
                       help="only the TMDB ids a movie and a show share")

    def handle(self, *args, **o):
        legacy = Title.objects.filter(trailer_clip_url__contains="/trailers/")
        shared_ids = set(
            Title.objects.exclude(tmdb_id=None).values("tmdb_id")
            .annotate(kinds=Count("type", distinct=True)).filter(kinds__gt=1)
            .values_list("tmdb_id", flat=True)
        )
        shared = legacy.filter(tmdb_id__in=shared_ids)
        target = shared if o["shared_only"] else legacy

        self.stdout.write(f"Old-format clips: {legacy.count()}, {shared.count()} of them on a TMDB id "
                          f"a movie and a show share.")
        for kind, tmdb_id, name in shared.order_by("tmdb_id", "type").values_list("type", "tmdb_id", "title")[:20]:
            self.stdout.write(f"  shared id {tmdb_id}: {kind} {name!r}")
        if o["dry_run"]:
            self.stdout.write(f"(dry run) would clear {target.count()} clip(s).")
            return
        n = target.update(trailer_clip_url="")
        self.stdout.write(f"Cleared {n} clip(s). Next: export_trailer_jobs, trailer-worker/, "
                          f"import_trailer_results, and the home pages rebuild within 2 hours.")
