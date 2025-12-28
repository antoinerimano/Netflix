# users/management/commands/sync_tmdb_monthly.py
import os
import re
import time
import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from users.models import Title, TVShowExtras, Season, Episode, Actor


# =========================
# Provider URL templates
# (from your backfill script)
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
    # genre is stored like "Action, Drama, Thriller"
    g = (genre_str or "").split(",")[0].strip()
    return norm(g)[:32] if g else ""


def fill_field(obj, field: str, new_val, overwrite: bool) -> bool:
    """
    Returns True if changed.
    Matches your seed_titlesV2 behavior:
      - overwrite=False: fill only if current is empty (None/" "/[])
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


def movie_title_links(tmdb_id: int, imdb_code: Optional[str]) -> Dict[str, str]:
    return {
        "video_url":   f"https://www.vidking.net/embed/movie/{tmdb_id}" if tmdb_id else "",
        "movie_link2": f"https://player.videasy.net/movie/{tmdb_id}" if tmdb_id else "",
        "movie_link3": f"https://vidsrc.xyz/embed/movie/{imdb_code}" if imdb_code else "",
        "movie_link4": fmt(TEMPLATES["movie_link4"], tmdb_id=tmdb_id),
        "movie_link5": fmt(TEMPLATES["movie_link5"], tmdb_id=tmdb_id),
        "movie_link6": fmt(TEMPLATES["movie_link6"], tmdb_id=tmdb_id),
    }


def tv_title_links(tv_tmdb_id: int) -> Dict[str, str]:
    # Title-level default = S1E1 + selector=true for the first 3 providers
    return {
        "video_url":   f"https://www.vidking.net/embed/tv/{tv_tmdb_id}/1/1?episodeSelector=true",
        "movie_link2": f"https://player.videasy.net/tv/{tv_tmdb_id}/1/1?episodeSelector=true",
        "movie_link3": f"https://vidsrc.xyz/embed/tv/{tv_tmdb_id}/1-1",

        # For 4/5/6, your convention is S1E1
        "movie_link4": fmt(TEMPLATES["tv_link4"], tmdb_id=tv_tmdb_id, season=1, episode=1),
        "movie_link5": fmt(TEMPLATES["tv_link5"], tmdb_id=tv_tmdb_id, season=1, episode=1),
        "movie_link6": fmt(TEMPLATES["tv_link6"], tmdb_id=tv_tmdb_id, season=1, episode=1),
    }


def episode_links(tv_tmdb_id: int, season: int, episode: int) -> Dict[str, str]:
    return {
        "video_url":     f"https://www.vidking.net/embed/tv/{tv_tmdb_id}/{season}/{episode}",
        "episode_link2": f"https://player.videasy.net/tv/{tv_tmdb_id}/{season}/{episode}",
        "episode_link3": f"https://vidsrc.xyz/embed/tv/{tv_tmdb_id}/{season}-{episode}",
        "episode_link4": fmt(TEMPLATES["episode_link4"], tmdb_id=tv_tmdb_id, season=season, episode=episode),
        "episode_link5": fmt(TEMPLATES["episode_link5"], tmdb_id=tv_tmdb_id, season=season, episode=episode),
        "episode_link6": fmt(TEMPLATES["episode_link6"], tmdb_id=tv_tmdb_id, season=season, episode=episode),
    }


class TMDbClient:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        # Prefer env, else settings, else user constant if you put it in settings.py
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
    help = "Monthly TMDB sync: discover popular movies/tv not yet in DB, upsert fields like seed_titlesV2, optional sync tv seasons/episodes."

    def add_arguments(self, parser):
        parser.add_argument("--pages", type=int, default=10, help="How many discover pages to scan per type.")
        parser.add_argument("--min-votes", type=int, default=800, help="discover.vote_count.gte (filters obscure titles).")
        parser.add_argument("--language", type=str, default="en-US")
        parser.add_argument("--overwrite", action="store_true", help="Overwrite non-empty fields (default: fill only if empty).")
        parser.add_argument("--verbose-adds", action="store_true", help="Print created/updated titles.")
        parser.add_argument("--only-created", action="store_true", help="If verbose, print only created (not updated).")        # TV episodes sync is ON by default (so new TV titles always get seasons/episodes like seed_titlesV2).
        parser.set_defaults(tv_sync_episodes=True)
        parser.add_argument("--tv-sync-episodes", dest="tv_sync_episodes", action="store_true", help="Also sync seasons/episodes for tv (default: ON).")
        parser.add_argument("--no-tv-sync-episodes", dest="tv_sync_episodes", action="store_false", help="Disable syncing seasons/episodes for tv.")
        parser.add_argument("--tv-max-seasons", type=int, default=2, help="Max seasons to sync per tv show (starting at season 1).")
        parser.add_argument("--skip-specials", action="store_true", help="Skip season 0.")

        parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between detail calls (avoid TMDB rate spikes).")

        parser.add_argument("--check-dups", action="store_true", help="Print duplicate groups (type,tmdb_id) if any.")
        parser.add_argument("--max-print", type=int, default=200, help="Max verbose lines printed per type.")

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
        # uses Actor unique constraint (title, name_norm)
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
                    "character": c.get("character") or "",
                },
            )

    @transaction.atomic
    def _upsert_movie(self, tmdb: TMDbClient, tmdb_id: int, language: str, overwrite: bool,
                      verbose: bool, only_created: bool, max_print: int, sleep_s: float,
                      stats: dict):

        # full movie + credits/videos/keywords
        full = tmdb.get(f"/movie/{tmdb_id}", params={"language": language, "append_to_response": "credits,videos,keywords"})
        self._maybe_sleep(sleep_s)

        # external_ids for imdb_id (needed for movie_link3)
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

        # also update actors table (optional but keeps your Actor list fresh)
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

    @transaction.atomic
    def _upsert_tv(self, tmdb: TMDbClient, tv_id: int, language: str, overwrite: bool,
                   verbose: bool, only_created: bool, max_print: int, sleep_s: float,
                   sync_eps: bool, max_seasons: int, skip_specials: bool,
                   stats: dict):

        full = tmdb.get(f"/tv/{tv_id}", params={"language": language, "append_to_response": "credits,videos,keywords"})
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

        links = tv_title_links(tv_id)

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

            "director": "",  # TV director isn't stable like movies
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

        # TV extras
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
            stats["tv"]["created"] += 1
        else:
            stats["tv"]["updated"] += 1

        if verbose and stats["tv"]["printed"] < max_print:
            if (not only_created) or created:
                tag = "CREATE" if created else ("UPDATE" if changed else "SKIP")
                self._log(f"[{tag}] tv tmdb_id={tv_id} first_air={first_air_date or '????-??-??'} title={title_str}")
                stats["tv"]["printed"] += 1

        # Seasons / Episodes sync
        if not sync_eps:
            return

        seasons_list = full.get("seasons") or []
        seasons_synced = 0

        for s in seasons_list:
            snum = safe_int(s.get("season_number"))
            if snum is None:
                continue
            if skip_specials and snum == 0:
                continue
            if snum <= 0:
                continue
            if snum > max_seasons:
                continue

            season_obj, _ = Season.objects.update_or_create(
                tv=obj,
                season_number=snum,
                defaults={
                    "tmdb_id": safe_int(s.get("id")),
                    "name": s.get("name") or "",
                    "overview": s.get("overview") or "",
                    "air_date": s.get("air_date") or "",
                    "poster": s.get("poster_path") or "",
                },
            )

            # season full for episodes
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

                links = episode_links(tv_id, snum, enum)

                # Episode model fields include episode_link4/5/6 :contentReference[oaicite:6]{index=6}
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

                # fill-only-if-empty (unless overwrite)
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

        tmdb = TMDbClient()

        self._log("====================================================")
        self._log("[sync_tmdb_monthly] starting…")
        self._log(f"pages={pages} min_votes={min_votes} language={language} overwrite={overwrite}")
        self._log(f"tv_sync_episodes={sync_eps} tv_max_seasons={max_seasons} skip_specials={skip_specials}")
        self._log(f"sleep={sleep_s}s")
        self._log("====================================================")

        stats = {
            "movie": {"created": 0, "updated": 0, "printed": 0},
            "tv": {"created": 0, "updated": 0, "printed": 0, "seasons_synced": 0},
        }

        # Discover params
        today = today_ymd()

        # ----------------
        # Movies
        # ----------------
        self._log("[movies] discover…")
        for page in range(1, pages + 1):
            data = tmdb.get("/discover/movie", params={
                "language": language,
                "sort_by": "popularity.desc",
                "include_adult": "false",
                "include_video": "false",
                "page": page,
                "vote_count.gte": min_votes,
                "release_date.lte": today,  # only released (or at least dated) <= today
            })

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
        # TV
        # ----------------
        self._log("[tv] discover…")
        for page in range(1, pages + 1):
            data = tmdb.get("/discover/tv", params={
                "language": language,
                "sort_by": "popularity.desc",
                "page": page,
                "vote_count.gte": min_votes,
                "first_air_date.lte": today,
            })

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
SYNC_TMDB_MONTHLY — COMMENT UTILISER (NOUVELLES SORTIES)
====================================================

Ce script sert à:
- chercher sur TMDb des films + séries "connus" (filtrés par popularité via discover)
- qui ont une date de sortie <= aujourd'hui (donc déjà sortis)
- et les ajouter dans ta DB si ils n’existent pas encore (sinon il complète les champs vides)
- optionnel: ajouter aussi Seasons/Episodes pour les séries

IMPORTANT
- Pour voir uniquement CE QUI A ÉTÉ AJOUTÉ (nouveaux titres), utilise:
  --verbose-adds --only-created

EXEMPLES (les plus utiles)

1) NOUVELLES SORTIES (Films + Séries) — recommandé
   - Ajoute uniquement les nouveaux Titles (movie/tv) manquants dans ta DB
   - Affiche uniquement les créations ([CREATE])
python manage.py sync_tmdb_monthly --pages 10 --min-votes 800 --verbose-adds --only-created

2) NOUVELLES SORTIES + épisodes (TV)
   - Ajoute les nouveaux Titles TV + récupère saisons/épisodes (limité aux saisons 1..2)
python manage.py sync_tmdb_monthly --pages 10 --min-votes 800 --tv-sync-episodes --tv-max-seasons 2 --verbose-adds --only-created

3) NOUVELLES SORTIES + check doublons à la fin
python manage.py sync_tmdb_monthly --pages 10 --min-votes 800 --verbose-adds --only-created --check-dups

4) Ajuster ce qui est considéré "connu"
- Plus strict (moins de titres, plus populaires):
python manage.py sync_tmdb_monthly --pages 10 --min-votes 2000 --verbose-adds --only-created
- Plus large (plus de titres, moins strict):
python manage.py sync_tmdb_monthly --pages 10 --min-votes 500 --verbose-adds --only-created

5) Si tu te fais rate-limit (TMDb 429), ralentis un peu:
python manage.py sync_tmdb_monthly --pages 10 --min-votes 800 --sleep 0.35 --verbose-adds --only-created

COMMENT LIRE LES LOGS
- [CREATE] ...  => un nouveau titre a été ajouté (c’est ce que tu veux pour "nouvelles sorties")
- [UPDATE] ...  => un titre existait déjà; le script a complété des champs vides (ou overwrite si activé)
- [SKIP]   ...  => le titre existait déjà et rien n’a changé

OPTIONS IMPORTANTES
- --pages N        : combien de pages TMDb à scanner (plus grand = plus de chances de trouver des nouveautés)
- --min-votes X    : filtre anti-"films obscurs" (vote_count minimum)
- --tv-sync-episodes / --tv-max-seasons : pour remplir Season/Episode
- --overwrite      : DANGEREUX (remplace aussi les champs déjà remplis). Par défaut le script remplit seulement les champs vides.
====================================================
"""
# ✅ COMMANDE PRINCIPALE — CHERCHER + AJOUTER LES NOUVEAUTÉS
# (Films + Séries déjà sortis (<= aujourd’hui) + "connus" via min-votes)
# Affiche UNIQUEMENT ce qui a été ajouté ([CREATE])
# ------------------------------------------------------------
# python manage.py sync_tmdb_monthly --pages 10 --min-votes 800 --verbose-adds --only-created
#
# ------------------------------------------------------------
# NOUVEAUTÉS + épisodes (TV)
# (Ajoute les séries + sync Seasons/Episodes, limité aux saisons 1..2)
# ------------------------------------------------------------
# python manage.py sync_tmdb_monthly --pages 10 --min-votes 800 --tv-sync-episodes --tv-max-seasons 2 --verbose-adds --only-created
#
# ------------------------------------------------------------
# NOUVEAUTÉS + vérification doublons à la fin
# ------------------------------------------------------------
# python manage.py sync_tmdb_monthly --pages 10 --min-votes 800 --verbose-adds --only-created --check-dups
#
# ------------------------------------------------------------
# Plus strict (encore moins "obscur", donc moins de titres)
# ------------------------------------------------------------
# python manage.py sync_tmdb_monthly --pages 10 --min-votes 2000 --verbose-adds --only-created
#
# ------------------------------------------------------------
# Plus large (plus de titres / plus de chances de trouver des nouveautés)
# ------------------------------------------------------------
# python manage.py sync_tmdb_monthly --pages 20 --min-votes 500 --verbose-adds --only-created
#
# ------------------------------------------------------------
# Si tu te fais rate-limit TMDb (429), ralentis un peu
# ------------------------------------------------------------
# python manage.py sync_tmdb_monthly --pages 10 --min-votes 800 --sleep 0.35 --verbose-adds --only-created
#
