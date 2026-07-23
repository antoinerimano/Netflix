
# users/management/commands/sync_tmdb_monthly.py
import os
import re
import time
import datetime
from typing import Any, Dict, List, Optional

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
    # Titles (movies)
    "movie_link4": "https://vidfast.pro/movie/{tmdb_id}",
    "movie_link5": "https://player.vidplus.to/embed/movie/{tmdb_id}?autoplay=false&poster=true&title=true&watchparty=false&chromecast=true&servericon=true&setting=true&pip=true&icons=netflix&primarycolor=FF6161&secondarycolor=000000&iconcolor=CB4848&font=Roboto&fontcolor=FFFFFF&fontsize=20&opacity=0.5",
    "movie_link6": "https://111movies.com/movie/{tmdb_id}",

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


def parse_year_from_ymd(s: str) -> Optional[int]:
    s = (s or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return None


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


def fill_field(obj, field: str, new_val, overwrite: bool) -> bool:
    """
    Returns True if changed.
      - overwrite=False: fill only if current is empty (None/""/[])
      - overwrite=True: set if different
    """
    curr = getattr(obj, field, None)
    if overwrite:
        if new_val != curr:
            setattr(obj, field, new_val)
            return True
        return False

    if (curr in (None, "", [])) and (new_val not in (None, "", [])):
        setattr(obj, field, new_val)
        return True

    return False


def tmdb_trailer_url(full: dict) -> str:
    for v in (full.get("videos") or {}).get("results", []) or []:
        if v.get("site") == "YouTube" and v.get("type") == "Trailer":
            key = v.get("key")
            if key:
                return f"https://www.youtube.com/watch?v={key}"
    return ""


def tmdb_director_from_credits(full: dict) -> str:
    for c in (full.get("credits") or {}).get("crew", []) or []:
        if c.get("job") == "Director":
            return c.get("name") or ""
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


def tmdb_movie_keywords(full: dict) -> List[str]:
    return [k.get("name") for k in ((full.get("keywords") or {}).get("keywords") or []) if k.get("name")]


def tmdb_tv_keywords(full: dict) -> List[str]:
    return [k.get("name") for k in ((full.get("keywords") or {}).get("results") or []) if k.get("name")]


def movie_title_links(tmdb_id: int, imdb_code: Optional[str] = None) -> Dict[str, str]:
    movie_link3 = f"https://vidsrc.sbs/embed/movie/{tmdb_id}" if tmdb_id else ""

    return {
        "video_url":   f"https://www.vidking.net/embed/movie/{tmdb_id}" if tmdb_id else "",
        "movie_link2": f"https://player.videasy.net/movie/{tmdb_id}" if tmdb_id else "",
        "movie_link3": movie_link3,
        "movie_link4": fmt(TEMPLATES["movie_link4"], tmdb_id=tmdb_id),
        "movie_link5": fmt(TEMPLATES["movie_link5"], tmdb_id=tmdb_id),
        "movie_link6": fmt(TEMPLATES["movie_link6"], tmdb_id=tmdb_id),
    }


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
    help = (
        "TMDB sync: discover popular movies/tv not yet in DB, fill like seed_titlesV2, "
        "and improve TV syncing by also using TMDb airing/on_the_air/trending lists to catch new popular shows."
    )

    def add_arguments(self, parser):
        parser.add_argument("--pages", type=int, default=10, help="How many discover pages to scan per type.")
        parser.add_argument("--min-votes", type=int, default=800, help="discover.vote_count.gte")
        parser.add_argument("--min-rating", type=float, default=0.0, help="discover.vote_average.gte (0 = disabled).")
        parser.add_argument("--language", type=str, default="en-US")
        parser.add_argument("--overwrite", action="store_true", help="Overwrite non-empty fields (default: fill only if empty).")
        parser.add_argument("--verbose-adds", action="store_true", help="Print created/updated titles.")
        parser.add_argument("--only-created", action="store_true", help="If verbose, print only created (not updated).")

        # TV episodes sync is ON by default
        parser.set_defaults(tv_sync_episodes=True)
        parser.add_argument("--tv-sync-episodes", dest="tv_sync_episodes", action="store_true", help="Also sync seasons/episodes for tv (default: ON).")
        parser.add_argument("--no-tv-sync-episodes", dest="tv_sync_episodes", action="store_false", help="Disable syncing seasons/episodes for tv.")

        # Old behavior: season 1..N
        parser.add_argument("--tv-max-seasons", type=int, default=2, help="(Discover TV) Max seasons to sync per tv show starting at season 1.")
        parser.add_argument("--skip-specials", action="store_true", help="Skip season 0.")

        # NEW: Airing/On-the-air/Trending sources to catch new popular shows + sync latest seasons
        parser.set_defaults(tv_use_airing_sources=True)
        parser.add_argument("--tv-use-airing-sources", dest="tv_use_airing_sources", action="store_true", help="Use TMDb airing/on_the_air/trending sources (default: ON).")
        parser.add_argument("--no-tv-use-airing-sources", dest="tv_use_airing_sources", action="store_false", help="Disable airing/on_the_air/trending sources.")

        parser.add_argument("--tv-airing-pages", type=int, default=5, help="Pages to scan for airing_today/on_the_air/trending.")
        parser.add_argument("--tv-min-votes-airing", type=int, default=100, help="Minimum vote_count for airing/trending candidates.")
        parser.add_argument("--tv-min-rating-airing", type=float, default=6.5, help="Minimum vote_average for airing/trending candidates.")
        parser.add_argument("--tv-sync-latest-seasons", type=int, default=1, help="For airing/trending shows: sync the latest N seasons (default: 1).")

        parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between detail calls (avoid TMDB rate spikes).")
        parser.add_argument("--check-dups", action="store_true", help="Print duplicate groups (type,tmdb_id) if any.")
        parser.add_argument("--max-print", type=int, default=200, help="Max verbose lines printed per type.")

        # Optional one-off force sync
        parser.add_argument("--tv-id", type=int, default=0, help="Force sync a specific TV tmdb_id and exit.")
        parser.add_argument("--movie-id", type=int, default=0, help="Force sync a specific Movie tmdb_id and exit.")

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

    # --- NEW: safer actor character field to avoid MySQL 1406 errors ---
    def _safe_character(self, s: str) -> str:
        # If your DB column is VARCHAR(255), this prevents "Data too long" crashes.
        # If you later change it to TEXT, this truncation is still harmless.
        return (s or "")[:255]

    def _sync_actors(self, title_obj: Title, full: dict):
        cast_list = (full.get("credits") or {}).get("cast", []) or []
        for c in cast_list[:30]:
            name = (c.get("name") or "").strip()
            if not name:
                continue
            Actor.objects.update_or_create(
                title=title_obj,
                name_norm=norm(name),
                defaults={
                    "name": name,
                    "tmdb_id": safe_int(c.get("id")),
                    "profile_path": c.get("profile_path") or "",
                    "character": self._safe_character(c.get("character") or ""),
                },
            )

    # --- NEW: collect IDs from airing/on_the_air/trending with quality filter ---
    def _collect_tv_ids_from_list(
        self,
        tmdb: TMDbClient,
        path: str,
        pages: int,
        language: str,
        min_votes: int,
        min_rating: float,
        sleep_s: float,
        is_trending: bool = False,
    ) -> List[int]:
        out: List[int] = []
        params_base = {}
        if not is_trending:
            params_base["language"] = language

        for page in range(1, pages + 1):
            params = dict(params_base)
            params["page"] = page
            data = tmdb.get(path, params=params)
            self._maybe_sleep(sleep_s)

            for it in (data.get("results") or []):
                tid = safe_int(it.get("id"))
                if not tid:
                    continue
                vc = safe_int(it.get("vote_count"), 0) or 0
                va = safe_float(it.get("vote_average"), 0.0) or 0.0
                if vc >= min_votes and va >= min_rating:
                    out.append(tid)

        # unique preserving order
        seen = set()
        uniq: List[int] = []
        for tid in out:
            if tid not in seen:
                seen.add(tid)
                uniq.append(tid)
        return uniq

    @transaction.atomic
    def _upsert_movie(
        self,
        tmdb: TMDbClient,
        tmdb_id: int,
        language: str,
        overwrite: bool,
        verbose: bool,
        only_created: bool,
        max_print: int,
        sleep_s: float,
        stats: dict,
    ):
        full = tmdb.get(f"/movie/{tmdb_id}", params={"language": language, "append_to_response": "credits,videos,keywords"})
        self._maybe_sleep(sleep_s)

        ext = {}
        try:
            ext = tmdb.get(f"/movie/{tmdb_id}/external_ids")
        except Exception:
            ext = {}
        self._maybe_sleep(sleep_s)

        imdb_code = (ext.get("imdb_id") or None)

        title_str = (full.get("title") or full.get("original_title") or "").strip()
        if not title_str:
            return

        release_date = (full.get("release_date") or "").strip()
        release_year = parse_year_from_ymd(release_date)

        links = movie_title_links(tmdb_id, imdb_code)
        genre_str = ", ".join([g.get("name") for g in (full.get("genres") or []) if g.get("name")])

        row = {
            "type": "movie",
            "imdb_code": imdb_code,
            "tmdb_id": tmdb_id,
            "title": title_str,
            "original_title": (full.get("original_title") or "").strip(),
            "original_language": (full.get("original_language") or "").strip(),

            "release_date": release_date,
            "release_year": release_year,
            "runtime_minutes": safe_int(full.get("runtime")),

            "description": (full.get("overview") or "").strip(),
            "tagline": (full.get("tagline") or "").strip(),
            "status": (full.get("status") or "").strip(),

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

            "keywords": tmdb_movie_keywords(full),
            "production_companies": [{"id": c.get("id"), "name": c.get("name")} for c in (full.get("production_companies") or [])],
            "production_countries": [c.get("name") for c in (full.get("production_countries") or []) if c.get("name")],
            "spoken_languages": [l.get("name") for l in (full.get("spoken_languages") or []) if l.get("name")],
            "belongs_to_collection": full.get("belongs_to_collection"),

            "director": tmdb_director_from_credits(full),
            "cast": tmdb_cast_names(full, limit=10),
        }

        obj, created = Title.objects.get_or_create(type="movie", tmdb_id=tmdb_id, defaults=row)

        changed = False
        if not created:
            for f, v in row.items():
                if f in ("type", "tmdb_id"):
                    continue
                if fill_field(obj, f, v, overwrite=overwrite):
                    changed = True
            if changed:
                obj.save()

        self._sync_actors(obj, full)

        if created:
            stats["movie"]["created"] += 1
        else:
            stats["movie"]["updated"] += 1

        if verbose and stats["movie"]["printed"] < max_print:
            if (not only_created) or created:
                tag = "CREATE" if created else ("UPDATE" if changed else "SKIP")
                self._log(f"[{tag}] movie tmdb_id={tmdb_id} year={release_year or '????'} title={title_str}")
                stats["movie"]["printed"] += 1

    def _pick_season_numbers(
        self,
        full_tv: dict,
        skip_specials: bool,
        mode: str,
        max_seasons_from_start: int,
        latest_n: int,
    ) -> List[int]:
        """
        mode:
          - "discover": sync season 1..max_seasons_from_start
          - "airing": sync latest N seasons (latest_n)
        """
        season_numbers = []
        for s in (full_tv.get("seasons") or []):
            sn = safe_int(s.get("season_number"))
            if sn is None:
                continue
            if skip_specials and sn == 0:
                continue
            if sn > 0:
                season_numbers.append(sn)

        season_numbers = sorted(set(season_numbers))
        if not season_numbers:
            return []

        if mode == "airing":
            n = max(1, int(latest_n or 1))
            return season_numbers[-n:]

        # discover mode
        m = int(max_seasons_from_start or 0)
        if m <= 0:
            return season_numbers
        return [sn for sn in season_numbers if sn <= m]

    @transaction.atomic
    def _upsert_tv(
        self,
        tmdb: TMDbClient,
        tv_id: int,
        language: str,
        overwrite: bool,
        verbose: bool,
        only_created: bool,
        max_print: int,
        sleep_s: float,
        sync_eps: bool,
        max_seasons: int,
        skip_specials: bool,
        stats: dict,
        season_mode: str = "discover",          # "discover" or "airing"
        latest_seasons_n: int = 1,              # used when season_mode == "airing"
    ):
        full = tmdb.get(f"/tv/{tv_id}", params={"language": language, "append_to_response": "credits,videos,keywords"})
        self._maybe_sleep(sleep_s)

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

        changed = False
        if not created:
            for f, v in row.items():
                if f in ("type", "tmdb_id"):
                    continue
                if fill_field(obj, f, v, overwrite=overwrite):
                    changed = True
            if changed:
                obj.save()

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

        self._sync_actors(obj, full)

        if created:
            stats["tv"]["created"] += 1
        else:
            stats["tv"]["updated"] += 1

        if verbose and stats["tv"]["printed"] < max_print:
            if (not only_created) or created:
                tag = "CREATE" if created else ("UPDATE" if changed else "SKIP")
                self._log(f"[{tag}] tv tmdb_id={tv_id} first_air={first_air_date or '????-??-??'} title={title_str}")
                stats["tv"]["printed"] += 1

        if not sync_eps:
            return

        season_numbers = self._pick_season_numbers(
            full_tv=full,
            skip_specials=skip_specials,
            mode=season_mode,
            max_seasons_from_start=max_seasons,
            latest_n=latest_seasons_n,
        )

        seasons_synced = 0
        for snum in season_numbers:
            # find the season dict (for metadata defaults) if present
            season_dict = None
            for s in (full.get("seasons") or []):
                if safe_int(s.get("season_number")) == snum:
                    season_dict = s
                    break
            season_dict = season_dict or {}

            season_obj, _ = Season.objects.update_or_create(
                tv=obj,
                season_number=snum,
                defaults={
                    "tmdb_id": safe_int(season_dict.get("id")),
                    "name": season_dict.get("name") or "",
                    "overview": season_dict.get("overview") or "",
                    "air_date": season_dict.get("air_date") or "",
                    "poster": season_dict.get("poster_path") or "",
                },
            )

            try:
                sfull = tmdb.get(f"/tv/{tv_id}/season/{snum}", params={"language": language})
            except Exception:
                continue
            self._maybe_sleep(sleep_s)

            episodes = sfull.get("episodes") or []
            for e in episodes:
                enum = safe_int(e.get("episode_number"), 0) or 0
                if enum <= 0:
                    continue

                links = episode_links(tv_id, snum, enum, imdb_code)
                ep_defaults = {
                    "tmdb_id": safe_int(e.get("id")),
                    "name": e.get("name") or "",
                    "overview": e.get("overview") or "",
                    "air_date": e.get("air_date") or "",
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
                        if fill_field(ep_obj, f, v, overwrite=overwrite):
                            ep_changed = True
                    if ep_changed:
                        ep_obj.save()

            seasons_synced += 1

        stats["tv"]["seasons_synced"] += seasons_synced

    def handle(self, *args, **opts):
        pages = int(opts["pages"])
        min_votes = int(opts["min_votes"])
        min_rating = float(opts["min_rating"])
        language = str(opts["language"])
        overwrite = bool(opts["overwrite"])
        verbose = bool(opts["verbose_adds"])
        only_created = bool(opts["only_created"])
        sync_eps = bool(opts["tv_sync_episodes"])
        max_seasons = int(opts["tv_max_seasons"])
        skip_specials = bool(opts["skip_specials"])
        sleep_s = float(opts["sleep"])
        check_dups = bool(opts["check_dups"])
        max_print = int(opts["max_print"])

        tv_use_airing_sources = bool(opts["tv_use_airing_sources"])
        tv_airing_pages = int(opts["tv_airing_pages"])
        tv_min_votes_airing = int(opts["tv_min_votes_airing"])
        tv_min_rating_airing = float(opts["tv_min_rating_airing"])
        tv_sync_latest_seasons = int(opts["tv_sync_latest_seasons"])

        force_tv_id = int(opts["tv_id"] or 0)
        force_movie_id = int(opts["movie_id"] or 0)

        tmdb = TMDbClient()

        self._log("====================================================")
        self._log("[sync_tmdb_monthly] starting…")
        self._log(f"pages={pages} min_votes={min_votes} min_rating={min_rating} language={language} overwrite={overwrite}")
        self._log(f"tv_sync_episodes={sync_eps} tv_max_seasons={max_seasons} skip_specials={skip_specials}")
        self._log(f"tv_use_airing_sources={tv_use_airing_sources} tv_airing_pages={tv_airing_pages} "
                  f"tv_min_votes_airing={tv_min_votes_airing} tv_min_rating_airing={tv_min_rating_airing} "
                  f"tv_sync_latest_seasons={tv_sync_latest_seasons}")
        self._log(f"sleep={sleep_s}s")
        self._log("====================================================")

        stats = {
            "movie": {"created": 0, "updated": 0, "printed": 0},
            "tv": {"created": 0, "updated": 0, "printed": 0, "seasons_synced": 0},
        }

        today = today_ymd()

        # --- One-off forced sync shortcuts ---
        if force_movie_id:
            self._log(f"[force] movie tmdb_id={force_movie_id}")
            self._upsert_movie(
                tmdb=tmdb,
                tmdb_id=force_movie_id,
                language=language,
                overwrite=overwrite,
                verbose=True,
                only_created=False,
                max_print=max_print,
                sleep_s=sleep_s,
                stats=stats,
            )
            self._log("DONE.")
            return

        if force_tv_id:
            self._log(f"[force] tv tmdb_id={force_tv_id}")
            self._upsert_tv(
                tmdb=tmdb,
                tv_id=force_tv_id,
                language=language,
                overwrite=overwrite,
                verbose=True,
                only_created=False,
                max_print=max_print,
                sleep_s=sleep_s,
                sync_eps=sync_eps,
                max_seasons=max_seasons,
                skip_specials=skip_specials,
                stats=stats,
                season_mode="airing" if sync_eps else "discover",
                latest_seasons_n=max(1, tv_sync_latest_seasons),
            )
            self._log("DONE.")
            return

        # ----------------
        # Movies (discover)
        # ----------------
        self._log("[movies] discover…")
        for page in range(1, pages + 1):
            params = {
                "language": language,
                "sort_by": "popularity.desc",
                "include_adult": "false",
                "include_video": "false",
                "page": page,
                "vote_count.gte": min_votes,
                "release_date.lte": today,
            }
            if min_rating and min_rating > 0:
                params["vote_average.gte"] = min_rating

            data = tmdb.get("/discover/movie", params=params)
            results = data.get("results") or []
            self._log(f"[movies] page={page} results={len(results)}")

            for it in results:
                mid = safe_int(it.get("id"))
                if not mid:
                    continue
                try:
                    self._upsert_movie(
                        tmdb=tmdb,
                        tmdb_id=mid,
                        language=language,
                        overwrite=overwrite,
                        verbose=verbose,
                        only_created=only_created,
                        max_print=max_print,
                        sleep_s=sleep_s,
                        stats=stats,
                    )
                except Exception as ex:
                    self._log(f"[movies] ERROR tmdb_id={mid}: {ex}")

        # ----------------
        # TV (airing/on_the_air/trending first)
        # ----------------
        if tv_use_airing_sources:
            self._log("[tv] airing/on_the_air/trending…")
            airing_ids: List[int] = []
            try:
                airing_ids += self._collect_tv_ids_from_list(
                    tmdb=tmdb,
                    path="/tv/airing_today",
                    pages=tv_airing_pages,
                    language=language,
                    min_votes=tv_min_votes_airing,
                    min_rating=tv_min_rating_airing,
                    sleep_s=sleep_s,
                )
            except Exception as ex:
                self._log(f"[tv] airing_today ERROR: {ex}")

            try:
                airing_ids += self._collect_tv_ids_from_list(
                    tmdb=tmdb,
                    path="/tv/on_the_air",
                    pages=tv_airing_pages,
                    language=language,
                    min_votes=tv_min_votes_airing,
                    min_rating=tv_min_rating_airing,
                    sleep_s=sleep_s,
                )
            except Exception as ex:
                self._log(f"[tv] on_the_air ERROR: {ex}")

            try:
                airing_ids += self._collect_tv_ids_from_list(
                    tmdb=tmdb,
                    path="/trending/tv/week",
                    pages=tv_airing_pages,
                    language=language,
                    min_votes=tv_min_votes_airing,
                    min_rating=tv_min_rating_airing,
                    sleep_s=sleep_s,
                    is_trending=True,
                )
            except Exception as ex:
                self._log(f"[tv] trending/week ERROR: {ex}")

            # unique preserving order
            airing_ids = list(dict.fromkeys(airing_ids))
            self._log(f"[tv] airing candidates={len(airing_ids)}")

            for tid in airing_ids:
                try:
                    self._upsert_tv(
                        tmdb=tmdb,
                        tv_id=tid,
                        language=language,
                        overwrite=overwrite,
                        verbose=verbose,
                        only_created=only_created,
                        max_print=max_print,
                        sleep_s=sleep_s,
                        sync_eps=sync_eps,
                        max_seasons=max_seasons,  # still used for discover mode; airing mode uses latest seasons
                        skip_specials=skip_specials,
                        stats=stats,
                        season_mode="airing",
                        latest_seasons_n=max(1, tv_sync_latest_seasons),
                    )
                except Exception as ex:
                    self._log(f"[tv] airing ERROR tmdb_id={tid}: {ex}")

        # ----------------
        # TV (discover, catalogue fill)
        # ----------------
        self._log("[tv] discover…")
        for page in range(1, pages + 1):
            params = {
                "language": language,
                "sort_by": "popularity.desc",
                "page": page,
                "vote_count.gte": min_votes,
                "first_air_date.lte": today,
            }
            if min_rating and min_rating > 0:
                params["vote_average.gte"] = min_rating

            data = tmdb.get("/discover/tv", params=params)
            results = data.get("results") or []
            self._log(f"[tv] page={page} results={len(results)}")

            for it in results:
                tid = safe_int(it.get("id"))
                if not tid:
                    continue
                try:
                    self._upsert_tv(
                        tmdb=tmdb,
                        tv_id=tid,
                        language=language,
                        overwrite=overwrite,
                        verbose=verbose,
                        only_created=only_created,
                        max_print=max_print,
                        sleep_s=sleep_s,
                        sync_eps=sync_eps,
                        max_seasons=max_seasons,
                        skip_specials=skip_specials,
                        stats=stats,
                        season_mode="discover",
                        latest_seasons_n=1,
                    )
                except Exception as ex:
                    self._log(f"[tv] ERROR tmdb_id={tid}: {ex}")

        self._log("====================================================")
        self._log("[SUMMARY]")
        self._log(f"movies: created={stats['movie']['created']} updated={stats['movie']['updated']}")
        self._log(f"tv: created={stats['tv']['created']} updated={stats['tv']['updated']} seasons_synced={stats['tv']['seasons_synced']}")
        self._log("====================================================")

        if check_dups:
            self._check_duplicates()

        self._log("DONE.")



"""
====================================================
SYNC_TMDB_MONTHLY — HOW TO RUN (CHEAT SHEET)
====================================================

This command is a Django management command:

    python manage.py sync_tmdb_monthly [options...]

It does 2 things:
1) Movies: uses TMDb /discover/movie (released <= today) and upserts into Title(type="movie")
2) TV: improved sync
   - (A) "Airing sources" pass (default ON): /tv/airing_today + /tv/on_the_air + /trending/tv/week
         * great for NEW / currently hot series
         * syncs the LATEST seasons (default 1 season) so episode sync is relevant
   - (B) "Discover TV" pass: /discover/tv (first_air_date <= today) like your original script
         * good for general catalogue fill
         * by default syncs seasons 1..tv_max_seasons (default 2)

LOGS / OUTPUT
- [CREATE] => new Title created (what you want when building catalogue)
- [UPDATE] => existing Title got some missing fields filled (or overwrite=True)
- [SKIP]   => existing Title and no changes

----------------------------------------------------
✅ MAIN RECOMMENDED RUN (Balanced)
- Finds new popular movies + tv
- TV uses airing/trending to catch new releases
- Prints only created Titles
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --pages 10 \
  --min-votes 800 \
  --verbose-adds --only-created

----------------------------------------------------
✅ NEW POPULAR TV FOCUS (best for “what’s hot now”)
- Same as above but makes airing/trending less strict so new shows pass
- Keeps catalogue discover strict-ish
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --pages 10 \
  --min-votes 800 \
  --tv-airing-pages 5 \
  --tv-min-votes-airing 100 \
  --tv-min-rating-airing 6.5 \
  --tv-sync-latest-seasons 1 \
  --verbose-adds --only-created

----------------------------------------------------
✅ STRICT MODE (fewer titles, very mainstream)
- Warning: this can MISS brand-new shows because vote_count is slow to grow
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --pages 10 \
  --min-votes 2000 \
  --verbose-adds --only-created

----------------------------------------------------
✅ WIDE MODE (more titles, more chances to find missing stuff)
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --pages 20 \
  --min-votes 500 \
  --verbose-adds --only-created

----------------------------------------------------
✅ ALSO SYNC EPISODES FOR TV
TV episode syncing is ON by default, but this shows the explicit flags.
- Discover TV: sync season 1..2 (tv_max_seasons)
- Airing/trending: sync latest season(s) (tv_sync_latest_seasons)
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --pages 10 \
  --min-votes 800 \
  --tv-sync-episodes \
  --tv-max-seasons 2 \
  --tv-sync-latest-seasons 1 \
  --verbose-adds --only-created

----------------------------------------------------
✅ DISABLE AIRING/TRENDING TV (old behavior)
If you want TV to behave exactly like before (only /discover/tv):
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --no-tv-use-airing-sources \
  --pages 10 \
  --min-votes 800 \
  --tv-sync-episodes \
  --tv-max-seasons 2 \
  --verbose-adds --only-created

----------------------------------------------------
✅ SKIP SPECIALS (season 0)
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --pages 10 \
  --min-votes 800 \
  --skip-specials \
  --verbose-adds --only-created

----------------------------------------------------
✅ IF YOU GET TMDb RATE LIMIT (429)
Slow down between TMDb calls.
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --pages 10 \
  --min-votes 800 \
  --sleep 0.35 \
  --verbose-adds --only-created

----------------------------------------------------
✅ CHECK FOR DUPLICATES AT THE END
Looks for duplicate (type, tmdb_id) groups in Title table.
----------------------------------------------------
python manage.py sync_tmdb_monthly \
  --pages 10 \
  --min-votes 800 \
  --check-dups \
  --verbose-adds --only-created

----------------------------------------------------
✅ FORCE ADD / FORCE RESYNC A SPECIFIC TITLE
This bypasses discover/airing lists. Useful when a show is missing.
- Force a TV show by TMDb ID:
----------------------------------------------------
python manage.py sync_tmdb_monthly --tv-id 12345 --verbose-adds

----------------------------------------------------
- Force a movie by TMDb ID:
----------------------------------------------------
python manage.py sync_tmdb_monthly --movie-id 98765 --verbose-adds

----------------------------------------------------
PARAMETER EXPLANATIONS (Quick)
----------------------------------------------------
--pages N
  How many pages (20 results/page) to scan for /discover (movies + tv).

--min-votes X
  vote_count.gte for /discover (filters obscure titles).

--min-rating R
  vote_average.gte for /discover (optional; default 0 = off).

--tv-use-airing-sources / --no-tv-use-airing-sources
  Enable/disable TV "airing_today/on_the_air/trending" pass (default ON).

--tv-airing-pages N
  Pages to scan for airing_today/on_the_air/trending.

--tv-min-votes-airing X
  Minimum vote_count for airing/trending candidates.

--tv-min-rating-airing R
  Minimum vote_average for airing/trending candidates.

--tv-sync-latest-seasons N
  For airing/trending shows, sync the latest N seasons (default 1).
  (This makes episode sync relevant for currently-airing shows.)

--tv-max-seasons N
  For discover TV only: sync seasons 1..N.

--tv-sync-episodes / --no-tv-sync-episodes
  Enable/disable season/episode syncing (default ON).

--overwrite
  Overwrites existing non-empty fields (DANGEROUS).
  Default behavior fills only missing/empty fields.

--verbose-adds
  Prints CREATE/UPDATE/SKIP lines (up to --max-print per type).

--only-created
  When verbose, print only [CREATE] lines.

--max-print
  Max lines printed per type.

====================================================
"""        