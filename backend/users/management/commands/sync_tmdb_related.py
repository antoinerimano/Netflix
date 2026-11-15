"""
manage.py sync_tmdb_related: TMDB's recommendations / similar titles and alternative titles
(users/tmdb_related.py, roadmap 8.8). One TMDB call per title, free, no AI.

Titles never synced or synced more than --days ago, most popular first, up to --limit a run
(nightly cron: the catalog in ~10 nights, then each title again every 60 days). A failed call
leaves the title for the next run; a title TMDB doesn't know (404) is marked synced with nothing.
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from users import tmdb_related
from users.jobs import tracked
from users.models import Title, TitleAltName

API = "https://api.themoviedb.org/3"


class Command(BaseCommand):
    help = "TMDB recommendations / similar titles ('More like this') and alternative titles (search)."

    def add_arguments(self, p):
        p.add_argument("--limit", type=int, default=5000, help="titles a run, most popular first")
        p.add_argument("--days", type=int, default=60, help="sync again after this many days")
        p.add_argument("--workers", type=int, default=6, help="parallel TMDB requests")

    @tracked("sync_tmdb_related")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        self.api_key = os.environ.get("TMDB_API_KEY") or getattr(settings, "TMDB_API_KEY", None)
        if not self.api_key:
            raise CommandError("Set TMDB_API_KEY.")
        self.local = threading.local()

        stale = timezone.now() - timedelta(days=o["days"])
        titles = list(
            Title.objects.exclude(tmdb_id__isnull=True)
            .filter(Q(related_synced_at__isnull=True) | Q(related_synced_at__lt=stale))
            .order_by("-popularity", "id")
            .only("id", "type", "tmdb_id", "title", "original_title")[: o["limit"]]
        )
        self.stdout.write(f"{len(titles)} titles to sync")
        done = related = names = failed = 0
        with ThreadPoolExecutor(max_workers=max(1, o["workers"])) as pool:
            futures = {
                pool.submit(self._get, f"/{t.type}/{t.tmdb_id}",
                            append_to_response="recommendations,similar,alternative_titles"): t
                for t in titles
            }
            for future in as_completed(futures):
                title = futures[future]
                data = future.result()
                if data is None:  # failed: the next run tries again
                    failed += 1
                    continue
                try:
                    r, n = self.save(title, data)
                except Exception as exc:  # one title's bad data never stops the run: tried again next time
                    failed += 1
                    self.stderr.write(f"  {title.id} {title.title}: {type(exc).__name__}: {exc}")
                    continue
                related += r
                names += n
                done += 1
                if done % 500 == 0:
                    self.stdout.write(f"  {done}/{len(titles)} titles")
        self.stdout.write(f"{done} titles synced: {related} related titles, {names} other names, {failed} failed.")

    @staticmethod
    def save(title, data):
        """Replaces the title's TMDB related titles and other names. Returns (related, names)."""
        from reco.models import TitleSimilar  # reco depends on users

        tmdb_ids = tmdb_related.related_tmdb_ids(data)
        by_tmdb = dict(
            Title.objects.filter(type=title.type, tmdb_id__in=tmdb_ids).exclude(id=title.id)
            .values_list("tmdb_id", "id")
        )
        ids = [by_tmdb[t] for t in tmdb_ids if t in by_tmdb]  # only titles in the catalog, TMDB's order
        alts = tmdb_related.alt_names(data, title.title, title.original_title)
        with transaction.atomic():
            TitleSimilar.objects.filter(title_id=title.id, model_name=tmdb_related.MODEL_NAME).delete()
            TitleSimilar.objects.bulk_create([
                TitleSimilar(title_id=title.id, similar_id=sid, score=score, model_name=tmdb_related.MODEL_NAME)
                for sid, score in zip(ids, tmdb_related.scores(len(ids)))
            ])
            TitleAltName.objects.filter(title_id=title.id).delete()
            # ignore_conflicts: MySQL compares names without accents / letter variants, so two names
            # different in Python can be the same for the unique key (an Arabic title did)
            TitleAltName.objects.bulk_create([
                TitleAltName(title_id=title.id, name=name, name_norm=norm, country=country)
                for name, norm, country in alts
            ], ignore_conflicts=True)
            Title.objects.filter(id=title.id).update(related_synced_at=timezone.now())
        return len(ids), len(alts)

    def _get(self, path, **params):
        """TMDB JSON, {} for a title TMDB doesn't know (404), None when it kept failing."""
        session = getattr(self.local, "session", None) or requests.Session()
        self.local.session = session
        for attempt in range(5):
            try:
                r = session.get(f"{API}{path}", params={"api_key": self.api_key, **params}, timeout=20)
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 429:  # rate limited
                time.sleep(float(r.headers.get("Retry-After", 2)))
                continue
            if r.status_code == 404:
                return {}
            if r.ok:
                return r.json()
            time.sleep(1 + attempt)
        return None
