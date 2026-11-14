"""
The titles that need a preview clip, as JSON for trailer-worker/ (run on another machine, the
web server only answers this and import_trailer_results):

    docker compose exec -T backend python manage.py export_trailer_jobs > jobs.json

A title needs one when it has a YouTube trailer and its trailer_clip_url isn't the clip of that
trailer yet: never made, made from an older trailer, or an old trailers/{tmdb_id}.mp4 clip
(those could belong to the show / movie with the same TMDB id, see users/trailers.py).
"""
import json

from django.core.management.base import BaseCommand

from users.models import Title
from users.trailers import preview_path, youtube_key


class Command(BaseCommand):
    help = "Print the titles that need a trailer preview clip (JSON, for trailer-worker/)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="At most this many (most popular first).")
        parser.add_argument("--type", choices=["movie", "tv"], help="Only movies or only shows.")

    def handle(self, *args, **opts):
        qs = (
            Title.objects.exclude(trailer_url="").exclude(tmdb_id=None)
            .order_by("-popularity", "id")  # popular titles get their preview first
            .values_list("type", "tmdb_id", "title", "original_title", "release_year",
                         "first_air_date", "trailer_url", "trailer_clip_url")
        )
        if opts.get("type"):
            qs = qs.filter(type=opts["type"])

        jobs = []
        for kind, tmdb_id, name, original, year, first_air, trailer, clip in qs.iterator(chunk_size=2000):
            key = youtube_key(trailer)
            if not key:
                continue
            path = preview_path(kind, tmdb_id, key)
            if (clip or "").endswith("/" + path):
                continue  # already the clip of this trailer
            jobs.append({
                "type": "tv" if kind == "tv" else "movie",
                "tmdb_id": tmdb_id,
                "title": name,
                "original_title": original or "",
                "year": year or (int(first_air[:4]) if (first_air or "")[:4].isdigit() else None),
                "trailer_url": trailer,
                "youtube_key": key,
                "path": path,
            })
            if opts["limit"] and len(jobs) >= opts["limit"]:
                break

        self.stdout.write(json.dumps({"version": 1, "jobs": jobs}, ensure_ascii=False))
        self.stderr.write(f"{len(jobs)} title(s) need a preview clip")
