"""
manage.py sync_tmdb_watch_providers: which streaming services (Netflix, Prime Video, Disney+...)
have each title in their subscription, per country (users/watch_services.py, ROADMAP 9.4). One free
TMDB call per title (/{type}/{id}/watch/providers, JustWatch's data), no AI.

Titles never read or read more than --days ago, most popular first, up to --limit a run (nightly
cron: the catalog in a few nights, then each title again every 30 days, services change their
catalogs every month). A failed call leaves the title for the next run; a title TMDB doesn't know
(404) is marked read with nothing.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
import os
import threading

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from users.jobs import tracked
from users.management.commands.sync_tmdb_related import Command as RelatedCommand
from users.models import Title, TitleOnService
from users.watch_services import services_on


class Command(BaseCommand):
    help = "Streaming services per country from TMDB's watch providers ('On Netflix' rows, browse filter)."

    def add_arguments(self, p):
        p.add_argument("--limit", type=int, default=6000, help="titles a run, most popular first")
        p.add_argument("--days", type=int, default=30, help="read again after this many days")
        p.add_argument("--workers", type=int, default=6, help="parallel TMDB requests")

    _get = RelatedCommand._get  # TMDB JSON with retries; {} on 404, None when it kept failing

    @tracked("sync_tmdb_watch_providers")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        self.api_key = os.environ.get("TMDB_API_KEY") or getattr(settings, "TMDB_API_KEY", None)
        if not self.api_key:
            raise CommandError("Set TMDB_API_KEY.")
        self.local = threading.local()

        stale = timezone.now() - timedelta(days=o["days"])
        titles = list(
            Title.objects.exclude(tmdb_id__isnull=True)
            .filter(Q(services_synced_at__isnull=True) | Q(services_synced_at__lt=stale))
            .order_by("-popularity", "id")
            .only("id", "type", "tmdb_id", "title")[: o["limit"]]
        )
        self.stdout.write(f"{len(titles)} titles to read")
        done = offers = failed = 0
        with ThreadPoolExecutor(max_workers=max(1, o["workers"])) as pool:
            futures = {pool.submit(self._get, f"/{t.type}/{t.tmdb_id}/watch/providers"): t for t in titles}
            for future in as_completed(futures):
                title = futures[future]
                data = future.result()
                if data is None:  # failed: the next run tries again
                    failed += 1
                    continue
                offers += self.save(title, data)
                done += 1
                if done % 1000 == 0:
                    self.stdout.write(f"  {done}/{len(titles)} titles")
        self.stdout.write(f"{done} titles read: {offers} service offers, {failed} failed.")

    @staticmethod
    def save(title, data):
        """Replaces the title's services. Returns how many (country, service) it has."""
        found = services_on(data)
        with transaction.atomic():
            TitleOnService.objects.filter(title_id=title.id).delete()
            TitleOnService.objects.bulk_create(
                [TitleOnService(title_id=title.id, country=c, service=s) for c, s in sorted(found)]
            )
            Title.objects.filter(id=title.id).update(services_synced_at=timezone.now())
        return len(found)
