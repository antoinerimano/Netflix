"""
The titles that need a preview clip, as JSON for trailer-worker/ (run on another machine, the
web server only answers this and import_trailer_results):

    docker compose exec -T backend python manage.py export_trailer_jobs > jobs.json

A title needs one when its trailer_clip_url isn't the clip for its current trailer yet: never
made, made from an older trailer, or an old trailers/{tmdb_id}.mp4 clip (those could belong to
the show / movie with the same TMDB id, see users/trailers.py). A clip the worker made from
another video because TMDB's couldn't be used counts (trailer_clip_for, clip_answers).

Titles TMDB has no trailer for are in too (youtube_key "", "search": true) when at least
--search-min-votes people rated them: the worker looks through TMDB's other videos, then
searches YouTube. Fewer votes: little known, a search finds the wrong video too often.
"""
import json

from django.core.management.base import BaseCommand

from users.models import Title
from users.trailers import clip_answers, preview_path, youtube_key

SEARCH_MIN_VOTES = 20


class Command(BaseCommand):
    help = "Print the titles that need a trailer preview clip (JSON, for trailer-worker/)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="At most this many (most popular first).")
        parser.add_argument("--type", choices=["movie", "tv"], help="Only movies or only shows.")
        parser.add_argument("--search-min-votes", type=int, default=SEARCH_MIN_VOTES,
                            help="Titles without a TMDB trailer: only with this many votes (-1: none).")

    def handle(self, *args, **opts):
        qs = (
            Title.objects.exclude(tmdb_id=None)
            .order_by("-popularity", "id")  # popular titles get their preview first
            .values_list("type", "tmdb_id", "title", "original_title", "original_language", "release_year",
                         "first_air_date", "trailer_url", "trailer_clip_url", "trailer_clip_for", "vote_count")
        )
        if opts.get("type"):
            qs = qs.filter(type=opts["type"])
        min_votes = opts["search_min_votes"]

        jobs = []
        for (kind, tmdb_id, name, original, language, year, first_air, trailer, clip, clip_for,
             votes) in qs.iterator(chunk_size=2000):
            key = youtube_key(trailer)
            if not key and (min_votes < 0 or (votes or 0) < min_votes):
                continue
            if clip_answers(clip, clip_for, kind, tmdb_id, trailer):
                continue  # already the clip for this trailer
            job = {
                "type": "tv" if kind == "tv" else "movie",
                "tmdb_id": tmdb_id,
                "title": name,
                "original_title": original or "",
                "original_language": language or "",
                "year": year or (int(first_air[:4]) if (first_air or "")[:4].isdigit() else None),
                "trailer_url": trailer if key else "",
                "youtube_key": key,
                "path": preview_path(kind, tmdb_id, key) if key else "",
            }
            if not key:
                job["search"] = True
            jobs.append(job)
            if opts["limit"] and len(jobs) >= opts["limit"]:
                break

        self.stdout.write(json.dumps({"version": 2, "jobs": jobs}, ensure_ascii=False))
        self.stderr.write(f"{len(jobs)} title(s) need a preview clip "
                          f"({sum(1 for j in jobs if j.get('search'))} without a TMDB trailer)")
