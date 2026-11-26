"""
Save the preview clips trailer-worker/ made (its results.json) on their titles:

    docker compose exec -T backend python manage.py import_trailer_results - < results.json

Only "ok" results are used, and only when they answer the title's current trailer (TMDB may
have changed it since the export: the next export asks for the new one). Running it again with
the same file changes nothing.

The worker may have made the clip from another video than the one asked for (asked_key, "" for
a title without a TMDB trailer): TMDB's was gone, blocked in its country or not the title's, so
it took TMDB's next trailer or searched YouTube. The clip is saved with trailer_clip_for = the
asked key ("-" for none), and the title page plays that video (users/trailers.py).

"withdrawn" (and a "rejected" that carries withdrawn): a clip the worker made from a YouTube
search and now turns down (make_previews.py --recheck-search: "NOVA" got a 1974 Chevrolet Nova).
withdrawn = the clip's path: the title loses its clip when it is still that one.

--clear-rejected: titles whose trailer the worker turned down (its YouTube name isn't the
title's) lose their old trailers/{tmdb_id}.mp4 clip too: it was most likely the wrong video.
"""
import json
import re
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from users.jobs import tracked
from users.models import Title
from users.trailers import preview_path, youtube_key

KEY_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class Command(BaseCommand):
    help = "Save trailer-worker/ results (results.json, or - for stdin) on the titles."

    def add_arguments(self, parser):
        parser.add_argument("file", help="results.json, or - to read it from stdin")
        parser.add_argument("--dry-run", action="store_true", help="Count only, change nothing.")
        parser.add_argument("--clear-rejected", action="store_true",
                            help="Also remove the old clip of titles whose trailer was rejected.")

    # JobRun: the dashboard / check-up see when the mini PC's nightly run (trailer-worker/run.sh)
    # last brought its clips back, and say so when it stops
    @tracked("import_trailer_results")
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
        stats = {"saved": 0, "other_video": 0, "unchanged": 0, "stale": 0, "unknown": 0, "cleared": 0,
                 "withdrawn": 0, "skipped": 0}

        with transaction.atomic():
            for r in results.values():
                status = r.get("status")
                kind = "tv" if r.get("type") == "tv" else "movie"
                try:
                    tmdb_id = int(r.get("tmdb_id"))
                except (TypeError, ValueError):
                    stats["skipped"] += 1
                    continue
                if status not in ("ok", "rejected", "withdrawn"):
                    stats["skipped"] += 1  # errors: the worker tries again later
                    continue

                title = Title.objects.filter(type=kind, tmdb_id=tmdb_id).only(
                    "id", "trailer_url", "trailer_clip_url", "trailer_clip_for").first()
                if not title:
                    stats["unknown"] += 1
                    continue
                gone = r.get("withdrawn") or ""
                if status != "ok" and gone.startswith("previews/") and title.trailer_clip_url.endswith("/" + gone):
                    stats["withdrawn"] += 1
                    if not opts["dry_run"]:
                        Title.objects.filter(pk=title.pk).update(trailer_clip_url="", trailer_clip_for="")
                    continue
                if status == "withdrawn":
                    stats["skipped"] += 1  # its clip was already taken off (or replaced)
                    continue
                current = youtube_key(title.trailer_url)
                asked = r.get("asked_key", r.get("youtube_key")) or ""  # results.json v1: no asked_key
                if asked != current:
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

                used = r.get("youtube_key") or ""
                if not KEY_RE.match(used):
                    stats["skipped"] += 1
                    continue
                # the worker's own URL isn't trusted: rebuilt from the CDN address and the path
                path = preview_path(kind, tmdb_id, used, r.get("rev") or "")  # rev: a clip made again
                url = f"{cdn}/{path}" if cdn else (r.get("url") or "")
                if not url.startswith("https://") or not url.endswith("/" + path):
                    stats["skipped"] += 1
                    continue
                clip_for = "" if used == current else (current or "-")
                if title.trailer_clip_url == url and title.trailer_clip_for == clip_for:
                    stats["unchanged"] += 1
                    continue
                stats["saved"] += 1
                if clip_for:
                    stats["other_video"] += 1
                if not opts["dry_run"]:
                    Title.objects.filter(pk=title.pk).update(trailer_clip_url=url, trailer_clip_for=clip_for)

            if opts["dry_run"]:
                transaction.set_rollback(True)

        prefix = "(dry run) " if opts["dry_run"] else ""
        self.stdout.write(prefix + ", ".join(f"{k}: {v}" for k, v in stats.items()))
