# users/management/commands/sync_tmdb_daily_episodes.py
import os
import re
import time
import datetime
from typing import Dict, List, Optional, Set, Tuple

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from users.models import Title, TVShowExtras, Season, Episode, Actor

# =========================
# Provider URL templates
# =========================
TEMPLATES: Dict[str, str] = {
    # Titles (tv -> S1E1)
    "tv_link4": "https://vidfast.pro/tv/{tmdb_id}/1/1",
    "tv_link5": "https://player.vidplus.to/embed/tv/{tmdb_id}/1/1?autoplay=false&autonext=false&nextbutton=false&poster=true&title=true&watchparty=false&chromecast=true&episodelist=true&servericon=true&setting=true&pip=true&icons=netflix&primarycolor=FF6161&secondarycolor=000000&iconcolor=CB4848&font=Roboto&fontcolor=FFFFFF&fontsize=20&opacity=0.5",
    "tv_link6": "https://111movies.com/tv/{tmdb_id}/1/1",

    # Episodes (tv)
    "episode_link4": "https://vidfast.pro/tv/{tmdb_id}/{season}/{episode}",
    "episode_link5": "https://player.vidplus.to/embed/tv/{tmdb_id}/{season}/{episode}?autoplay=false&autonext=false&nextbutton=false&poster=true&title=true&watchparty=false&chromecast=true&episodelist=true&servericon=true&setting=true&pip=true&icons=netflix&primarycolor=FF6161&secondarycolor=000000&iconcolor=CB4848&font=Roboto&fontcolor=FFFFFF&fontsize=20&opacity=0.5",
    "episode_link6": "https://111movies.com/tv/{tmdb_id}/{season}/{episode}",
}


def today_ymd() -> str:
    return datetime.date.today().isoformat()


def days_ago_ymd(n: int) -> str:
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


def safe_int(x, default=None):
    try:
        if x is None:
            return default
        return int(x)
    except Exception:
        return default


def safe_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def img_url(path: Optional[str], size: str = "original") -> str:
    if not path:
        return ""
    p = str(path).lstrip("/")
    return f"https://image.tmdb.org/t/p/{size}/{p}"


def fmt(template: str, tmdb_id: int, season: Optional[int] = None, episode: Optional[int] = None) -> str:
    if not template or not tmdb_id:
        return ""
    try:
        return template.format(tmdb_id=tmdb_id, season=season, episode=episode)
    except Exception:
        return ""


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def primary_genre_norm_from_genre_string(genre_str: str) -> str:
    g = (genre_str or "").split(",")[0].strip()
    return norm(g)[:32] if g else ""


def parse_ymd_date(s: str) -> Optional[datetime.date]:
    s = (s or "").strip()
    if len(s) != 10:
        return None
    try:
        return datetime.date.fromisoformat(s)
    except Exception:
        return None


def tmdb_trailer_url(full: dict) -> str:
    for v in (full.get("videos") or {}).get("results", []) or []:
        if v.get("site") == "YouTube" and v.get("type") == "Trailer":
            key = v.get("key")
            if key:
                return f"https://www.youtube.com/watch?v={key}"
    return ""


def tmdb_cast_names(full: dict, limit: int = 10) -> List[str]:
    out = []
    for c in (full.get("credits") or {}).get("cast", []) or []:
        n = c.get("name")
        if n:
            out.append(n)
        if len(out) >= limit:
            break
    return out


def tmdb_tv_keywords(full: dict) -> List[str]:
    return [k.get("name") for k in ((full.get("keywords") or {}).get("results") or []) if k.get("name")]


def tv_title_links(tv_tmdb_id: int, imdb_code: Optional[str] = None) -> Dict[str, str]:
    movie_link3 = f"https://vidsrc.sbs/embed/tv/{tv_tmdb_id}/1/1/" if tv_tmdb_id else ""

    return {
        "video_url":   f"https://www.vidking.net/embed/tv/{tv_tmdb_id}/1/1?episodeSelector=true",
        "movie_link2": f"https://player.videasy.net/tv/{tv_tmdb_id}/1/1?episodeSelector=true",
        "movie_link3": movie_link3,
        "movie_link4": fmt(TEMPLATES["tv_link4"], tmdb_id=tv_tmdb_id, season=1, episode=1),
        "movie_link5": fmt(TEMPLATES["tv_link5"], tmdb_id=tv_tmdb_id, season=1, episode=1),
        "movie_link6": fmt(TEMPLATES["tv_link6"], tmdb_id=tv_tmdb_id, season=1, episode=1),
    }


def episode_links(tv_tmdb_id: int, season: int, episode: int, imdb_code: Optional[str] = None) -> Dict[str, str]:
    episode_link3 = f"https://vidsrc.sbs/embed/tv/{tv_tmdb_id}/{season}/{episode}/" if tv_tmdb_id else ""

    return {
        "video_url":     f"https://www.vidking.net/embed/tv/{tv_tmdb_id}/{season}/{episode}",
        "episode_link2": f"https://player.videasy.net/tv/{tv_tmdb_id}/{season}/{episode}",
        "episode_link3": episode_link3,
        "episode_link4": fmt(TEMPLATES["episode_link4"], tmdb_id=tv_tmdb_id, season=season, episode=episode),
        "episode_link5": fmt(TEMPLATES["episode_link5"], tmdb_id=tv_tmdb_id, season=season, episode=episode),
        "episode_link6": fmt(TEMPLATES["episode_link6"], tmdb_id=tv_tmdb_id, season=season, episode=episode),
    }


def get_model_maxlen(model_cls, field_name: str, fallback: int = 255) -> int:
    try:
        f = model_cls._meta.get_field(field_name)
        ml = getattr(f, "max_length", None)
        return int(ml) if ml else fallback
    except Exception:
        return fallback


class TMDbClient:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        self.api_key = (
            api_key
            or os.environ.get("TMDB_API_KEY")
            or getattr(settings, "TMDB_API_KEY", None)
            or getattr(settings, "TMDB_KEY", None)
        )
        if not self.api_key:
            raise RuntimeError("Set TMDB_API_KEY (or put TMDB_KEY / TMDB_API_KEY in settings.py).")

        self.base = "https://api.themoviedb.org/3"
        self.timeout = timeout
        self.s = requests.Session()

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        params["api_key"] = self.api_key
        url = self.base + path
        r = self.s.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()


class Command(BaseCommand):
    help = "Daily TV updater: fetch airing/on_the_air/trending TV and sync latest seasons + newest episodes."

    def add_arguments(self, parser):
        parser.add_argument("--pages", type=int, default=5, help="How many pages per TMDb list endpoint.")
        parser.add_argument("--language", type=str, default="en-US")

        parser.add_argument("--latest-seasons", type=int, default=2, help="Sync last N seasons per show.")
        parser.add_argument("--lookback-days", type=int, default=120, help="Only keep/sync episodes with air_date >= today-lookback.")

        parser.add_argument("--min-votes", type=int, default=0, help="Skip shows with vote_count < this (airing lists).")
        parser.add_argument("--min-rating", type=float, default=0.0, help="Skip shows with vote_average < this (airing lists).")

        parser.add_argument("--no-airing-today", action="store_true", help="Disable /tv/airing_today pass.")
        parser.add_argument("--no-on-the-air", action="store_true", help="Disable /tv/on_the_air pass.")
        parser.add_argument("--no-trending", action="store_true", help="Disable /trending/tv/day pass.")

        parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between TMDb calls.")
        parser.add_argument("--verbose", action="store_true", help="Print more logs.")
        parser.add_argument("--only-created", action="store_true", help="If verbose, print only created titles.")
        parser.add_argument("--max-print", type=int, default=200, help="Max verbose lines printed.")

        parser.add_argument("--check-dups", action="store_true", help="Print duplicate groups (type,tmdb_id) if any.")

    def _log(self, msg: str):
        self.stdout.write(msg)

    def _maybe_sleep(self, sec: float):
        if sec and sec > 0:
            time.sleep(sec)

    def _check_duplicates(self):
        qs = (
            Title.objects.exclude(tmdb_id__isnull=True)
            .values("type", "tmdb_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
            .order_by("-c")
        )
        n = qs.count()
        if n == 0:
            self._log("[dups] OK: no duplicate (type, tmdb_id) groups found.")
            return
        self._log(f"[dups] WARNING: {n} duplicate groups found. Showing first 25:")
        for row in qs[:25]:
            self._log(f"  - type={row['type']} tmdb_id={row['tmdb_id']} count={row['c']}")

    def _sync_actors(self, title_obj: Title, full: dict):
        # Prevent MySQL "Data too long for column 'character'" by truncating
        char_max = get_model_maxlen(Actor, "character", fallback=255)

        cast_list = (full.get("credits") or {}).get("cast", []) or []
        for c in cast_list[:30]:
            name = (c.get("name") or "").strip()
            if not name:
                continue

            character = (c.get("character") or "").strip()
            if char_max and character and len(character) > char_max:
                character = character[:char_max]

            Actor.objects.update_or_create(
                title=title_obj,
                name_norm=norm(name),
                defaults={
                    "name": name,
                    "tmdb_id": safe_int(c.get("id")),
                    "profile_path": c.get("profile_path") or "",
                    "character": character,
                },
            )

    @transaction.atomic
    def _upsert_tv_and_latest_eps(
        self,
        tmdb: TMDbClient,
        tv_id: int,
        language: str,
        latest_seasons: int,
        lookback_days: int,
        sleep_s: float,
        verbose: bool,
        only_created: bool,
        max_print: int,
        stats: dict,
    ):
        # full tv + credits/videos/keywords
        full = tmdb.get(
            f"/tv/{tv_id}",
            params={"language": language, "append_to_response": "credits,videos,keywords"},
        )
        self._maybe_sleep(sleep_s)

        # external ids (optional)
        ext = {}
        try:
            ext = tmdb.get(f"/tv/{tv_id}/external_ids")
        except Exception:
            ext = {}
        self._maybe_sleep(sleep_s)

        imdb_code = (ext.get("imdb_id") or None)

        title_str = (full.get("name") or full.get("original_name") or "").strip()
        if not title_str:
            return

        first_air_date = (full.get("first_air_date") or "").strip()
        genre_str = ", ".join([g.get("name") for g in (full.get("genres") or []) if g.get("name")])

        links = tv_title_links(tv_id, imdb_code)

        row = {
            "type": "tv",
            "imdb_code": imdb_code,
            "tmdb_id": tv_id,
            "title": title_str,

            "original_title": (full.get("original_name") or "").strip(),
            "original_language": (full.get("original_language") or "").strip(),

            "first_air_date": first_air_date,
            "description": (full.get("overview") or "").strip(),
            "status": (full.get("status") or "").strip(),

            # these change over time; we always refresh them
            "rating": str(full.get("vote_average") or ""),
            "vote_average": safe_float(full.get("vote_average")),
            "vote_count": safe_int(full.get("vote_count")),
            "popularity": safe_float(full.get("popularity")),

            "poster": img_url(full.get("poster_path"), "original"),
            "landscape_image": img_url(full.get("backdrop_path"), "original"),

            "video_url": links["video_url"],
            "movie_link2": links["movie_link2"],
            "movie_link3": links["movie_link3"],
            "movie_link4": links["movie_link4"],
            "movie_link5": links["movie_link5"],
            "movie_link6": links["movie_link6"],

            "trailer_url": tmdb_trailer_url(full),

            "genre": genre_str,
            "primary_genre_norm": primary_genre_norm_from_genre_string(genre_str),

            "keywords": tmdb_tv_keywords(full),
            "production_companies": [{"id": c.get("id"), "name": c.get("name")} for c in (full.get("production_companies") or [])],
            "production_countries": [c.get("name") for c in (full.get("production_countries") or []) if c.get("name")],
            "spoken_languages": [l.get("name") for l in (full.get("spoken_languages") or []) if l.get("name")],
            "belongs_to_collection": None,

            "director": "",
            "cast": tmdb_cast_names(full, limit=10),
        }

        obj, created = Title.objects.get_or_create(type="tv", tmdb_id=tv_id, defaults=row)

        # Update a mix of fill-if-empty + always-refresh stats
        changed = False
        if not created:
            # fill-if-empty for most fields
            for f, v in row.items():
                if f in ("type", "tmdb_id"):
                    continue

                # Always refresh these changing numbers
                if f in ("rating", "vote_average", "vote_count", "popularity", "status"):
                    if getattr(obj, f, None) != v:
                        setattr(obj, f, v)
                        changed = True
                    continue

                curr = getattr(obj, f, None)
                if (curr in (None, "", [])) and (v not in (None, "", [])):
                    setattr(obj, f, v)
                    changed = True

            if changed:
                obj.save()

        # TV extras (always refresh)
        TVShowExtras.objects.update_or_create(
            title=obj,
            defaults={
                "number_of_seasons": safe_int(full.get("number_of_seasons"), 0) or 0,
                "number_of_episodes": safe_int(full.get("number_of_episodes"), 0) or 0,
                "in_production": bool(full.get("in_production")),
                "episode_run_time": full.get("episode_run_time") or [],
                "network_names": [n.get("name") for n in (full.get("networks") or []) if n.get("name")],
            },
        )

        # Actors
        self._sync_actors(obj, full)

        if created:
            stats["created"] += 1
        else:
            stats["updated"] += 1

        if verbose and stats["printed"] < max_print:
            if (not only_created) or created:
                tag = "CREATE" if created else ("UPDATE" if changed else "SKIP")
                self._log(f"[{tag}] tv tmdb_id={tv_id} first_air={first_air_date or '????-??-??'} title={title_str}")
                stats["printed"] += 1

        # ---- Seasons / Episodes (latest seasons only) ----
        total_seasons = safe_int(full.get("number_of_seasons"), 0) or 0
        if total_seasons <= 0:
            return

        latest_seasons = max(1, int(latest_seasons))
        start_season = max(1, total_seasons - latest_seasons + 1)

        cutoff = None
        if lookback_days and lookback_days > 0:
            cutoff = datetime.date.today() - datetime.timedelta(days=int(lookback_days))

        seasons_synced = 0
        episodes_upserted = 0

        for snum in range(start_season, total_seasons + 1):
            # TMDb season details includes episodes
            try:
                sfull = tmdb.get(f"/tv/{tv_id}/season/{snum}", params={"language": language})
            except Exception:
                continue
            self._maybe_sleep(sleep_s)

            season_obj, _ = Season.objects.update_or_create(
                tv=obj,
                season_number=snum,
                defaults={
                    "tmdb_id": safe_int(sfull.get("id")),
                    "name": sfull.get("name") or "",
                    "overview": sfull.get("overview") or "",
                    "air_date": sfull.get("air_date") or "",
                    "poster": sfull.get("poster_path") or "",
                },
            )

            episodes = sfull.get("episodes") or []
            for e in episodes:
                enum = safe_int(e.get("episode_number"), 0) or 0
                if enum <= 0:
                    continue

                air_date = (e.get("air_date") or "").strip()
                if cutoff:
                    d = parse_ymd_date(air_date)
                    if d and d < cutoff:
                        continue

                links = episode_links(tv_id, snum, enum, imdb_code)

                ep_defaults = {
                    "tmdb_id": safe_int(e.get("id")),
                    "name": e.get("name") or "",
                    "overview": e.get("overview") or "",
                    "air_date": air_date,
                    "still_path": e.get("still_path") or "",
                    "vote_average": safe_float(e.get("vote_average")),
                    "vote_count": safe_int(e.get("vote_count")),
                    "runtime": safe_int(e.get("runtime")),

                    "imdb_code": None,
                    "video_url": links["video_url"],
                    "episode_link2": links["episode_link2"],
                    "episode_link3": links["episode_link3"],
                    "episode_link4": links["episode_link4"],
                    "episode_link5": links["episode_link5"],
                    "episode_link6": links["episode_link6"],
                }

                ep_obj, ep_created = Episode.objects.get_or_create(
                    season=season_obj,
                    episode_number=enum,
                    defaults=ep_defaults,
                )

                if not ep_created:
                    ep_changed = False
                    for f, v in ep_defaults.items():
                        if f in ("vote_average", "vote_count", "runtime", "air_date"):
                            if getattr(ep_obj, f, None) != v:
                                setattr(ep_obj, f, v)
                                ep_changed = True
                            continue

                        curr = getattr(ep_obj, f, None)
                        if (curr in (None, "", [])) and (v not in (None, "", [])):
                            setattr(ep_obj, f, v)
                            ep_changed = True

                    if ep_changed:
                        ep_obj.save()

                episodes_upserted += 1

            seasons_synced += 1

        stats["seasons_synced"] += seasons_synced
        stats["episodes_upserted"] += episodes_upserted

    def _collect_ids_from_endpoint(
        self,
        tmdb: TMDbClient,
        path: str,
        pages: int,
        language: str,
        sleep_s: float,
    ) -> List[int]:
        out: List[int] = []
        for page in range(1, pages + 1):
            params = {"page": page}
            # some endpoints accept language; trending ignores it, but harmless
            if language:
                params["language"] = language
            data = tmdb.get(path, params=params)
            self._maybe_sleep(sleep_s)
            results = data.get("results") or []
            for it in results:
                tid = safe_int(it.get("id"))
                if tid:
                    out.append(tid)
        return out

    def handle(self, *args, **opts):
        pages = int(opts["pages"])
        language = str(opts["language"])
        latest_seasons = int(opts["latest_seasons"])
        lookback_days = int(opts["lookback_days"])
        min_votes = int(opts["min_votes"])
        min_rating = float(opts["min_rating"])

        no_airing_today = bool(opts["no_airing_today"])
        no_on_the_air = bool(opts["no_on_the_air"])
        no_trending = bool(opts["no_trending"])

        sleep_s = float(opts["sleep"])
        verbose = bool(opts["verbose"])
        only_created = bool(opts["only_created"])
        max_print = int(opts["max_print"])
        check_dups = bool(opts["check_dups"])

        tmdb = TMDbClient()

        self._log("====================================================")
        self._log("[sync_tmdb_daily_episodes] starting…")
        self._log(f"pages={pages} language={language} latest_seasons={latest_seasons} lookback_days={lookback_days}")
        self._log(f"min_votes={min_votes} min_rating={min_rating} sleep={sleep_s}s")
        self._log(f"airing_today={'OFF' if no_airing_today else 'ON'} on_the_air={'OFF' if no_on_the_air else 'ON'} trending={'OFF' if no_trending else 'ON'}")
        self._log("====================================================")

        existing_tv: Set[int] = set(
            Title.objects.filter(type="tv")
            .exclude(tmdb_id__isnull=True)
            .values_list("tmdb_id", flat=True)
        )

        # Collect candidates
        candidates: List[Tuple[str, int]] = []

        if not no_airing_today:
            self._log("[tv] airing_today…")
            for tid in self._collect_ids_from_endpoint(tmdb, "/tv/airing_today", pages, language, sleep_s):
                candidates.append(("airing_today", tid))

        if not no_on_the_air:
            self._log("[tv] on_the_air…")
            for tid in self._collect_ids_from_endpoint(tmdb, "/tv/on_the_air", pages, language, sleep_s):
                candidates.append(("on_the_air", tid))

        if not no_trending:
            self._log("[tv] trending/day…")
            for tid in self._collect_ids_from_endpoint(tmdb, "/trending/tv/day", pages, language, sleep_s):
                candidates.append(("trending", tid))

        # De-dupe while keeping order
        seen: Set[int] = set()
        ordered_ids: List[int] = []
        for _, tid in candidates:
            if tid not in seen:
                seen.add(tid)
                ordered_ids.append(tid)

        self._log(f"[tv] candidates={len(ordered_ids)} (deduped from {len(candidates)})")

        stats = {"created": 0, "updated": 0, "printed": 0, "seasons_synced": 0, "episodes_upserted": 0, "skipped_filters": 0}

        # Process
        for tv_id in ordered_ids:
            # quick filter by stats from lightweight tv detail? we already need full detail to sync eps,
            # but we can still skip some after fetching.
            try:
                # Fetch full once inside _upsert_tv_and_latest_eps; but we need votes/rating filter before doing lots of season calls.
                full = tmdb.get(f"/tv/{tv_id}", params={"language": language})
                self._maybe_sleep(sleep_s)

                vc = safe_int(full.get("vote_count"), 0) or 0
                va = safe_float(full.get("vote_average"), 0.0) or 0.0
                if (min_votes and vc < min_votes) or (min_rating and va < min_rating):
                    stats["skipped_filters"] += 1
                    continue

                # Now do the heavy upsert + latest seasons episodes
                self._upsert_tv_and_latest_eps(
                    tmdb=tmdb,
                    tv_id=tv_id,
                    language=language,
                    latest_seasons=latest_seasons,
                    lookback_days=lookback_days,
                    sleep_s=sleep_s,
                    verbose=verbose,
                    only_created=only_created,
                    max_print=max_print,
                    stats=stats,
                )
            except Exception as ex:
                self._log(f"[tv] ERROR tmdb_id={tv_id}: {ex}")

        self._log("====================================================")
        self._log("[SUMMARY]")
        self._log(f"tv: created={stats['created']} updated={stats['updated']}")
        self._log(f"seasons_synced={stats['seasons_synced']} episodes_upserted={stats['episodes_upserted']}")
        self._log(f"skipped_by_filters={stats['skipped_filters']}")
        self._log("====================================================")

        if check_dups:
            self._check_duplicates()

        self._log("DONE.")

"""
====================================================
SYNC_TMDB_DAILY_EPISODES — HOW TO RUN
====================================================

✅ RECOMMENDED DAILY (airing + on_the_air + trending/day)
- Syncs latest seasons (default 2) + episodes in last 120 days (default)
- Good balance of speed vs completeness

python manage.py sync_tmdb_daily_episodes --pages 5 --latest-seasons 2 --lookback-days 120

----------------------------------------------------
ONLY SHOWS AIRING NOW (no trending)
python manage.py sync_tmdb_daily_episodes --no-trending --pages 5 --latest-seasons 2 --lookback-days 120

----------------------------------------------------
MORE COMPLETE EPISODE COVERAGE (bigger lookback)
python manage.py sync_tmdb_daily_episodes --pages 5 --latest-seasons 2 --lookback-days 365

----------------------------------------------------
IF YOU WANT TO FILTER OUT “LOW SIGNAL” SHOWS
(helps avoid syncing lots of obscure stuff)
python manage.py sync_tmdb_daily_episodes --pages 5 --min-votes 50 --min-rating 6.0

----------------------------------------------------
VERBOSE LOGS
python manage.py sync_tmdb_daily_episodes --pages 5 --verbose

----------------------------------------------------
RUN IN DOCKER (your setup)
docker compose exec backend python manage.py sync_tmdb_daily_episodes --pages 5 --latest-seasons 2 --lookback-days 120

CRON (daily @ 05:30 UTC)
30 5 * * * cd /opt/taurus/backend && docker compose exec -T backend python manage.py sync_tmdb_daily_episodes --pages 5 --latest-seasons 2 --lookback-days 120 >> /var/log/sync_tmdb_daily_episodes.log 2>&1

====================================================
"""