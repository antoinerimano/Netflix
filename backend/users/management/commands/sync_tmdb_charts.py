"""
manage.py sync_tmdb_charts: TMDB's trending charts for the "Top 10" home rows (ROADMAP 9.4).

  - /trending/movie/day   -> "Top 10 movies today"
  - /trending/tv/week     -> "Top 10 shows this week"

Free TMDB data, 2 pages (40 titles) a chart so 10 are left once the titles we lack and a profile's
age limit are taken out. Only titles already in the catalog are kept (sync_tmdb_new_releases adds
the new trending movies every night, sync_tmdb_daily_episodes the new shows), at TMDB's position.
A chart that couldn't be read keeps its last list. Cron: every 6 hours (ops/crontab).
reco/top10.py mixes them with our own plays once there are enough.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from users.jobs import tracked
from users.management.commands.sync_tmdb_monthly import TMDbClient, safe_int
from users.models import Title, TitleChartEntry

CHARTS = {
    TitleChartEntry.MOVIE_DAY: ("movie", "/trending/movie/day"),
    TitleChartEntry.TV_WEEK: ("tv", "/trending/tv/week"),
}


def chart_tmdb_ids(tmdb, path, pages):
    """TMDB ids in the chart's order, no repeats, no adult titles."""
    ids = []
    for page in range(1, pages + 1):
        data = tmdb.get(path, params={"page": page})
        for it in data.get("results") or []:
            tid = safe_int(it.get("id"))
            if tid and tid not in ids and not it.get("adult"):
                ids.append(tid)
        if page >= (safe_int(data.get("total_pages"), 1) or 1):
            break
    return ids


def save_chart(chart, kind, tmdb_ids):
    """Replaces the chart with the catalog's titles at their TMDB position. Returns how many."""
    by_tmdb = dict(Title.objects.filter(type=kind, tmdb_id__in=tmdb_ids).values_list("tmdb_id", "id"))
    now = timezone.now()
    rows = [
        TitleChartEntry(chart=chart, position=pos, title_id=by_tmdb[tid], synced_at=now)
        for pos, tid in enumerate(tmdb_ids, start=1) if tid in by_tmdb
    ]
    with transaction.atomic():
        TitleChartEntry.objects.filter(chart=chart).delete()
        TitleChartEntry.objects.bulk_create(rows)
    return len(rows)


class Command(BaseCommand):
    help = "TMDB trending (movies today, shows this week) for the Top 10 home rows."

    def add_arguments(self, p):
        p.add_argument("--pages", type=int, default=2, help="pages (20 titles) read from each chart")

    @tracked("sync_tmdb_charts")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        tmdb = TMDbClient()
        failed = []
        for chart, (kind, path) in CHARTS.items():
            try:
                ids = chart_tmdb_ids(tmdb, path, max(1, o["pages"]))
            except Exception as ex:  # the chart keeps its last list
                failed.append(chart)
                self.stdout.write(f"[charts] {path}: {type(ex).__name__}: {ex}")
                continue
            kept = save_chart(chart, kind, ids)
            self.stdout.write(f"[charts] {chart}: {len(ids)} on TMDB, {kept} in the catalog")
        if len(failed) == len(CHARTS):
            raise RuntimeError("no chart could be read from TMDB")
