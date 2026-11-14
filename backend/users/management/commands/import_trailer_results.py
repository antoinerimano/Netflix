"""
Save the preview clips trailer-worker/ made (its results.json) on their titles:

    docker compose exec -T backend python manage.py import_trailer_results - < results.json

Only "ok" results are used, and only when they are the clip of the title's current trailer
(TMDB may have changed it since the export: the next export asks for the new one). Running it
again with the same file changes nothing.

--clear-rejected: titles whose trailer the worker turned down (its YouTube name isn't the
title's) lose their old trailers/{tmdb_id}.mp4 clip too: it was most likely the wrong video.
"""
import json
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from users.models import Title
from users.trailers import preview_path, youtube_key


class Command(BaseCommand):
    help = "Save trailer-worker/ results (results.json, or - for stdin) on the titles."

    def add_arguments(self, parser):
        parser.add_argument("file", help="results.json, or - to read it from stdin")
        parser.add_argument("--dry-run", action="store_true", help="Count only, change nothing.")
        parser.add_argument("--clear-rejected", action="store_true",
                            help="Also remove the old clip of titles whose trailer was rejected.")

    def handle(self, *args, **opts):
        try:
            raw = sys.stdin.read() if opts["file"] == "-" else open(opts["file"], encoding="utf-8").read()
            data = json.loads(raw)
        except (OSError, ValueError) as e:
            raise CommandError(f"Can't read the results: {e}")
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, dict):
            raise CommandError('Not a trailer-worker results file (no "results" object).')

        cdn = (getattr(settings, "BUNNY_CDN_BASE", "") or "").rstrip("/")
        stats = {"saved": 0, "unchanged": 0, "stale": 0, "unknown": 0, "cleared": 0, "skipped": 0}

        with transaction.atomic():
            for r in results.values():
                status = r.get("status")
                kind = "tv" if r.get("type") == "tv" else "movie"
                try:
                    tmdb_id = int(r.get("tmdb_id"))
                except (TypeError, ValueError):
                    stats["skipped"] += 1
                    continue
                if status not in ("ok", "rejected"):
                    stats["skipped"] += 1  # errors: the worker tries again later
                    continue

                title = Title.objects.filter(type=kind, tmdb_id=tmdb_id).only(
                    "id", "trailer_url", "trailer_clip_url").first()
                if not title:
                    stats["unknown"] += 1
                    continue
                key = youtube_key(title.trailer_url)
                if not key or key != r.get("youtube_key"):
                    stats["stale"] += 1  # the trailer changed since the export
                    continue

                if status == "rejected":
                    legacy = "/trailers/" in (title.trailer_clip_url or "")
                    if opts["clear_rejected"] and legacy:
                        stats["cleared"] += 1
                        if not opts["dry_run"]:
                            Title.objects.filter(pk=title.pk).update(trailer_clip_url="")
                    else:
                        stats["skipped"] += 1
                    continue

                # the worker's own URL isn't trusted: rebuilt from the CDN address and the path
                path = preview_path(kind, tmdb_id, key)
                url = f"{cdn}/{path}" if cdn else (r.get("url") or "")
                if not url.startswith("https://") or not url.endswith("/" + path):
                    stats["skipped"] += 1
                    continue
                if title.trailer_clip_url == url:
                    stats["unchanged"] += 1
                    continue
                stats["saved"] += 1
                if not opts["dry_run"]:
                    Title.objects.filter(pk=title.pk).update(trailer_clip_url=url)

            if opts["dry_run"]:
                transaction.set_rollback(True)

        prefix = "(dry run) " if opts["dry_run"] else ""
        self.stdout.write(prefix + ", ".join(f"{k}: {v}" for k, v in stats.items()))
