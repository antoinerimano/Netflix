# users/management/commands/sync_tmdb_translations.py
"""
Fill TitleTranslation (and optionally EpisodeTranslation) from TMDB, so the API can serve
titles, synopses and taglines in the user's language (users/localize.py).

One request per title (/movie|tv/{id}/translations) brings every language at once. A row is
stored for each app language even when TMDB has nothing (empty texts = English is shown), so
the default run only asks TMDB about titles never synced: run it after the catalog syncs.

  python manage.py sync_tmdb_translations                 # titles without translations yet
  python manage.py sync_tmdb_translations --all           # refresh everything
  python manage.py sync_tmdb_translations --languages fr,es --limit 500
  python manage.py sync_tmdb_translations --episodes --latest-seasons 2 --limit 300
      # + episode names / synopses of the latest seasons (1 request per season and language)
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Exists, OuterRef

from users.i18n import APP_LANGUAGES, DEFAULT_LANGUAGE, TMDB_CODES
from users.jobs import tracked
from users.models import Episode, EpisodeTranslation, Season, Title, TitleTranslation

API = "https://api.themoviedb.org/3"
# TMDB has one translation per language + country: the country to prefer for each language.
# Chinese: only Simplified-script countries (TW / HK are Traditional).
REGIONS = {
    "fr": ["FR", "CA", "BE", "CH"],
    "es": ["ES", "MX", "AR", "CO"],
    "de": ["DE", "AT", "CH"],
    "it": ["IT", "CH"],
    "ja": ["JP"],
    "zh": ["CN", "SG"],
}


def _clean(s, max_len=None):
    s = (s or "").strip()
    return s[:max_len] if max_len else s


def pick(translations, lang):
    """The best TMDB translation of lang -> {"name", "overview", "tagline"} (empty when none)."""
    by_region = {
        t.get("iso_3166_1"): t.get("data") or {}
        for t in translations
        if t.get("iso_639_1") == lang
    }
    for region in REGIONS.get(lang, []):
        if region in by_region:
            data = by_region[region]
            break
    else:
        data = {} if lang == "zh" else next(iter(by_region.values()), {})
    return {
        "name": _clean(data.get("title") or data.get("name"), 255),
        "overview": _clean(data.get("overview")),
        "tagline": _clean(data.get("tagline"), 255),
    }


class Command(BaseCommand):
    help = "Titles / synopses (and optionally episode texts) in every app language, from TMDB."

    def add_arguments(self, parser):
        parser.add_argument("--languages", default=",".join(l for l in APP_LANGUAGES if l != DEFAULT_LANGUAGE),
                            help="Comma-separated app codes (default: every language but English).")
        parser.add_argument("--all", action="store_true", help="Refresh titles already synced too.")
        parser.add_argument("--limit", type=int, default=0, help="Max titles (0 = all), most popular first.")
        parser.add_argument("--workers", type=int, default=8, help="Parallel TMDB requests.")
        parser.add_argument("--type", choices=["movie", "tv", "all"], default="all")
        parser.add_argument("--episodes", action="store_true", help="Also episode names / synopses (shows).")
        parser.add_argument("--latest-seasons", type=int, default=2, help="With --episodes: seasons per show.")

    @tracked("sync_tmdb_translations")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **opts):
        self.api_key = os.environ.get("TMDB_API_KEY") or getattr(settings, "TMDB_API_KEY", None)
        if not self.api_key:
            raise CommandError("Set TMDB_API_KEY.")
        langs = [l.strip() for l in opts["languages"].split(",") if l.strip()]
        bad = [l for l in langs if l not in APP_LANGUAGES or l == DEFAULT_LANGUAGE]
        if bad:
            raise CommandError(f"Unknown or English language(s): {', '.join(bad)} (app languages: {', '.join(APP_LANGUAGES)})")
        self.local = threading.local()

        qs = Title.objects.exclude(tmdb_id__isnull=True)
        if opts["type"] != "all":
            qs = qs.filter(type=opts["type"])
        if not opts["all"]:
            # never synced = no row in one of the languages asked
            for lang in langs:
                qs = qs.filter(~Exists(TitleTranslation.objects.filter(title=OuterRef("pk"), language=lang)))
        qs = qs.order_by("-popularity", "id").only("id", "type", "tmdb_id")
        if opts["limit"]:
            qs = qs[: opts["limit"]]
        titles = list(qs)
        self.stdout.write(f"{len(titles)} titles to translate into {', '.join(langs)}")

        done = found = 0
        batch = []
        with ThreadPoolExecutor(max_workers=max(1, opts["workers"])) as pool:
            futures = {pool.submit(self._get, f"/{t.type}/{t.tmdb_id}/translations"): t for t in titles}
            for future in as_completed(futures):
                title = futures[future]
                data = future.result()
                if data is None:
                    continue  # failed: retried on the next run (still missing)
                translations = data.get("translations") or []
                for lang in langs:
                    texts = pick(translations, lang)
                    found += bool(texts["name"] or texts["overview"])
                    batch.append(TitleTranslation(title_id=title.id, language=lang, **texts))
                done += 1
                if len(batch) >= 1000:
                    self._save_titles(batch)
                    batch = []
                if done % 500 == 0:
                    self.stdout.write(f"  {done}/{len(titles)} titles")
        self._save_titles(batch)
        self.stdout.write(f"{done} titles synced, {found} translations found.")

        if opts["episodes"]:
            self._sync_episodes(langs, opts, [t for t in titles if t.type == "tv"] if not opts["all"] else None)

    # ---------- TMDB ----------

    def _get(self, path, **params):
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

    # ---------- saving ----------

    @staticmethod
    def _upsert(model, rows, unique, fields):
        """Insert, or update the existing (item, language) row (MySQL: ON DUPLICATE KEY UPDATE)."""
        if not rows:
            return
        # MySQL upserts on any unique key and refuses a target; PostgreSQL / SQLite need one
        target = {"unique_fields": unique} if connection.features.supports_update_conflicts_with_target else {}
        model.objects.bulk_create(rows, update_conflicts=True, update_fields=fields, **target)

    def _save_titles(self, rows):
        self._upsert(TitleTranslation, rows, ["title", "language"], ["name", "overview", "tagline", "synced_at"])

    def _save_episodes(self, rows):
        self._upsert(EpisodeTranslation, rows, ["episode", "language"], ["name", "overview", "synced_at"])

    # ---------- episodes ----------

    def _sync_episodes(self, langs, opts, shows):
        """Episode names / synopses of each show's latest seasons: /tv/{id}/season/{n}?language=xx."""
        if shows is None:
            shows = list(Title.objects.filter(type="tv").exclude(tmdb_id__isnull=True).order_by("-popularity", "id")
                         .only("id", "tmdb_id")[: opts["limit"] or None])
        seasons = []
        for show in shows:
            numbers = list(
                Season.objects.filter(tv_id=show.id, season_number__gt=0)
                .order_by("-season_number").values_list("id", "season_number")[: opts["latest_seasons"]]
            )
            seasons.extend((show, sid, n) for sid, n in numbers)
        self.stdout.write(f"{len(seasons)} seasons x {len(langs)} languages of episode texts")

        jobs = [(show, sid, n, lang) for show, sid, n in seasons for lang in langs]
        rows = []
        with ThreadPoolExecutor(max_workers=max(1, opts["workers"])) as pool:
            futures = {
                pool.submit(self._get, f"/tv/{show.tmdb_id}/season/{n}", language=TMDB_CODES[lang]): (sid, lang)
                for show, sid, n, lang in jobs
            }
            for future in as_completed(futures):
                sid, lang = futures[future]
                data = future.result() or {}
                by_number = dict(Episode.objects.filter(season_id=sid).values_list("episode_number", "id"))
                for ep in data.get("episodes") or []:
                    eid = by_number.get(ep.get("episode_number"))
                    if eid:
                        rows.append(EpisodeTranslation(
                            episode_id=eid, language=lang,
                            name=_clean(ep.get("name"), 300), overview=_clean(ep.get("overview")),
                        ))
                if len(rows) >= 1000:
                    self._save_episodes(rows)
                    rows = []
        self._save_episodes(rows)
        self.stdout.write("Episode texts synced.")
