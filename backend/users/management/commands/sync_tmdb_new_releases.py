"""
manage.py sync_tmdb_new_releases: the movies that just came out, the day they become popular.

The weekly sync_tmdb_monthly only adds movies with 500+ votes on TMDB, which a new movie gets weeks
after its release. This one runs every night (ops/crontab) and adds the released movies not in the
catalog yet from TMDB's lists of the moment:
  - /trending/movie/day      what people look at today
  - /movie/now_playing       in theatres
  - /discover/movie          out on streaming / digital (release types 4, 5) in the last --days
with --min-votes (default 50) so the empty pages of obscure titles stay out. Titles already in the
catalog are skipped (clean_db keeps them up to date). New TV shows already come in every 3 hours
(sync_tmdb_daily_episodes: airing / on the air / trending).

What a new title needs next is done by the nightly jobs after it: age rating (backfill_ratings),
translations (sync_tmdb_translations), related titles (sync_tmdb_related), search index
(rebuild_title_indexes), embeddings (build_embeddings --missing), then the home pages.
"""
import datetime

from django.core.management.base import BaseCommand

from users.jobs import tracked
from users.management.commands.sync_tmdb_monthly import Command as Sync, TMDbClient, safe_int
from users.models import Title


def released(item: dict, today: str) -> bool:
    date = (item.get("release_date") or "").strip()
    return bool(date) and date <= today


class Command(BaseCommand):
    help = "Add the movies just released (trending today, in theatres, new on streaming) that the catalog lacks."

    def add_arguments(self, p):
        p.add_argument("--pages", type=int, default=3, help="Pages (20 movies) read from each TMDB list.")
        p.add_argument("--min-votes", type=int, default=50, help="TMDB vote_count a movie needs.")
        p.add_argument("--days", type=int, default=60, help="Streaming / digital releases of the last N days.")
        p.add_argument("--max-new", type=int, default=200, help="At most N movies added in one run.")
        p.add_argument("--sleep", type=float, default=0.2, help="Pause between TMDB detail calls.")
        p.add_argument("--dry-run", action="store_true", help="List what would be added, add nothing.")

    def candidates(self, tmdb, pages, min_votes, days):
        today = datetime.date.today()
        today_s = today.isoformat()
        lists = [
            ("/trending/movie/day", {}),
            ("/movie/now_playing", {"language": "en-US"}),
            ("/discover/movie", {
                "language": "en-US", "sort_by": "popularity.desc", "include_adult": "false",
                "with_release_type": "4|5", "vote_count.gte": min_votes,
                "release_date.gte": (today - datetime.timedelta(days=days)).isoformat(),
                "release_date.lte": today_s,
            }),
        ]
        seen = {}
        for path, params in lists:
            for page in range(1, pages + 1):
                try:
                    data = tmdb.get(path, params={**params, "page": page})
                except Exception as ex:
                    self.stdout.write(f"[new-releases] {path} page {page}: {ex}")
                    break
                for it in data.get("results") or []:
                    mid = safe_int(it.get("id"))
                    if (mid and mid not in seen and not it.get("adult")
                            and (safe_int(it.get("vote_count"), 0) or 0) >= min_votes and released(it, today_s)):
                        seen[mid] = (it.get("title") or it.get("original_title") or "").strip()
                if page >= (safe_int(data.get("total_pages"), 1) or 1):
                    break
        return seen

    @tracked("sync_tmdb_new_releases")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        tmdb = TMDbClient()
        found = self.candidates(tmdb, o["pages"], o["min_votes"], o["days"])
        known = set(Title.objects.filter(type="movie", tmdb_id__in=list(found)).values_list("tmdb_id", flat=True))
        new = [mid for mid in found if mid not in known][: o["max_new"]]
        self.stdout.write(f"[new-releases] {len(found)} movies in TMDB's lists, {len(new)} not in the catalog")

        if o["dry_run"]:
            for mid in new:
                self.stdout.write(f"  would add tmdb={mid} {found[mid]}")
            return

        sync = Sync(stdout=self.stdout, stderr=self.stderr)
        stats = {"movie": {"created": 0, "updated": 0, "printed": 0}}
        errors = 0
        for mid in new:
            try:
                sync._upsert_movie(tmdb=tmdb, tmdb_id=mid, language="en-US", overwrite=False, verbose=True,
                                   only_created=True, max_print=10_000, sleep_s=o["sleep"], stats=stats)
            except Exception as ex:
                errors += 1
                self.stdout.write(f"[new-releases] ERROR tmdb={mid} {found[mid]}: {ex}")
        self.stdout.write(f"[new-releases] added {stats['movie']['created']} movies, {errors} errors")
