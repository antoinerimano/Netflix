# users/management/commands/backfill_ratings.py
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from users.maturity import rating_from_tmdb
from users.models import Title

APPEND = {"movie": "release_dates", "tv": "content_ratings"}


class Command(BaseCommand):
    help = (
        "Fetch age ratings (certification + maturity) from TMDB for titles that don't have one yet. "
        "Safe to stop and re-run: it continues where it stopped."
    )

    def add_arguments(self, parser):
        parser.add_argument("--workers", type=int, default=8, help="Parallel TMDB requests.")
        parser.add_argument("--limit", type=int, default=0, help="Max titles (0 = all).")
        parser.add_argument("--all", action="store_true", help="Refresh titles already rated too.")
        parser.add_argument("--batch", type=int, default=400)

    def handle(self, *args, **opts):
        api_key = os.environ.get("TMDB_API_KEY") or getattr(settings, "TMDB_API_KEY", None)
        if not api_key:
            raise CommandError("Set TMDB_API_KEY.")

        qs = Title.objects.exclude(tmdb_id__isnull=True).order_by("id")
        if not opts["all"]:
            qs = qs.filter(rating_synced_at__isnull=True)
        total = qs.count()
        if opts["limit"]:
            total = min(total, opts["limit"])
        self.stdout.write(f"{total} titles to rate")

        local = threading.local()

        def fetch(title):
            session = getattr(local, "session", None) or requests.Session()
            local.session = session
            url = f"https://api.themoviedb.org/3/{title.type}/{title.tmdb_id}"
            params = {"api_key": api_key, "append_to_response": APPEND[title.type]}
            for attempt in range(5):
                try:
                    r = session.get(url, params=params, timeout=20)
                except requests.RequestException:
                    time.sleep(2 * (attempt + 1))
                    continue
                if r.status_code == 429:  # rate limited
                    time.sleep(float(r.headers.get("Retry-After", 2)))
                    continue
                if r.status_code == 404:
                    return title, ("", None)
                if r.ok:
                    return title, rating_from_tmdb(title.type, r.json())
                time.sleep(1)
            return title, None  # give up for now, retried on the next run

        done = rated = failed = 0
        started = time.time()
        last_id = 0
        with ThreadPoolExecutor(max_workers=opts["workers"]) as pool:
            while done < total:
                batch = list(
                    qs.filter(id__gt=last_id).only("id", "type", "tmdb_id")[: min(opts["batch"], total - done)]
                )
                if not batch:
                    break
                last_id = batch[-1].id
                now = timezone.now()
                to_save = []
                for title, result in pool.map(fetch, batch):
                    done += 1
                    if result is None:
                        failed += 1
                        continue
                    title.certification, title.maturity = result
                    title.rating_synced_at = now
                    rated += title.maturity is not None
                    to_save.append(title)
                Title.objects.bulk_update(to_save, ["certification", "maturity", "rating_synced_at"])
                rate = done / max(time.time() - started, 1)
                self.stdout.write(
                    f"{done}/{total} done, {rated} rated, {failed} failed, "
                    f"{rate:.0f}/s, ~{(total - done) / max(rate, 0.1) / 60:.0f} min left"
                )

        self.stdout.write(f"Done: {done} checked, {rated} have a rating, {failed} failed (re-run to retry).")
