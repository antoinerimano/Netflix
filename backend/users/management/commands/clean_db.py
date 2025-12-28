# users/management/commands/clean_db.py
import os
import time
import datetime
from typing import Dict, Any, Optional, List

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Min, Q

from users.models import Title, TVShowExtras, Season, Episode, Actor


# =========================
# Provider URL templates
# =========================
TEMPLATES: Dict[str, str] = {
    # Titles (movies)
    "movie_link4": "https://vidfast.pro/movie/{tmdb_id}",
    "movie_link5": "https://player.vidplus.to/embed/movie/{tmdb_id}?autoplay=false&poster=true&title=true&watchparty=false&chromecast=true&servericon=true&setting=true&pip=true&icons=netflix&primarycolor=FF6161&secondarycolor=000000&iconcolor=CB4848&font=Roboto&fontcolor=FFFFFF&fontsize=20&opacity=0.5",
    "movie_link6": "https://111movies.com/movie/{tmdb_id}",

    # Title (tv -> S1E1)
    "tv_link4": "https://vidfast.pro/tv/{tmdb_id}/1/1",
    "tv_link5": "https://player.vidplus.to/embed/tv/{tmdb_id}/1/1?autoplay=false&autonext=false&nextbutton=false&poster=true&title=true&watchparty=false&chromecast=true&episodelist=true&servericon=true&setting=true&pip=true&icons=netflix&primarycolor=FF6161&secondarycolor=000000&iconcolor=CB4848&font=Roboto&fontcolor=FFFFFF&fontsize=20&opacity=0.5",
    "tv_link6": "https://111movies.com/tv/{tmdb_id}/1/1",

    # Episodes (tv)
    "episode_link4": "https://vidfast.pro/tv/{tmdb_id}/{season}/{episode}",
    "episode_link5": "https://player.vidplus.to/embed/tv/{tmdb_id}/{season}/{episode}?autoplay=false&autonext=false&nextbutton=false&poster=true&title=true&watchparty=false&chromecast=true&episodelist=true&servericon=true&setting=true&pip=true&icons=netflix&primarycolor=FF6161&secondarycolor=000000&iconcolor=CB4848&font=Roboto&fontcolor=FFFFFF&fontsize=20&opacity=0.5",
    "episode_link6": "https://111movies.com/tv/{tmdb_id}/{season}/{episode}",
}


# =========================
# Helpers
# =========================
def now_s() -> float:
    return time.time()

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

def is_empty(v) -> bool:
    return v in (None, "", [])

def fill_field(obj, field: str, new_val, overwrite: bool) -> bool:
    curr = getattr(obj, field, None)
    if overwrite:
        if new_val != curr:
            setattr(obj, field, new_val)
            return True
        return False

    if is_empty(curr) and (not is_empty(new_val)):
        setattr(obj, field, new_val)
        return True

    return False


# =========================
# TMDb client
# =========================
class TMDbClient:
    def __init__(self, api_key: Optional[str] = None, timeout: int = 25):
        self.api_key = (
            api_key
            or os.environ.get("TMDB_API_KEY")
            or getattr(settings, "TMDB_API_KEY", None)
            or getattr(settings, "TMDB_KEY", None)
        )
        if not self.api_key:
            raise RuntimeError("Set TMDB_API_KEY (or put TMDB_API_KEY / TMDB_KEY in settings.py).")

        self.base = "https://api.themoviedb.org/3"
        self.timeout = timeout
        self.s = requests.Session()

    def get(self, path: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        params["api_key"] = self.api_key
        r = self.s.get(self.base + path, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()


def tmdb_trailer_url(full: dict) -> str:
    for v in (full.get("videos") or {}).get("results", []) or []:
        if v.get("site") == "YouTube" and v.get("type") == "Trailer":
            key = v.get("key")
            if key:
                return f"https://www.youtube.com/watch?v={key}"
    return ""

def tmdb_director(full: dict) -> str:
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
    return {
        "video_url":   f"https://www.vidking.net/embed/tv/{tv_tmdb_id}/1/1?episodeSelector=true",
        "movie_link2": f"https://player.videasy.net/tv/{tv_tmdb_id}/1/1?episodeSelector=true",
        "movie_link3": f"https://vidsrc.xyz/embed/tv/{tv_tmdb_id}/1-1",
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


class Command(BaseCommand):
    help = "Clean DB with logs: dedupe titles, backfill provider links, backfill TMDb popular fields, and optionally create TV extras/seasons/episodes."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="No DB writes (prints what would happen).")
        parser.add_argument("--overwrite", action="store_true", help="Overwrite non-empty fields (default: fill only if empty).")
        parser.add_argument("--sleep", type=float, default=0.15, help="Delay between TMDb calls.")
        parser.add_argument("--limit", type=int, default=0, help="Limit titles processed in TMDb backfill (0=all).")

        parser.add_argument("--dedupe", action="store_true", help="Remove duplicates on (type,tmdb_id).")
        parser.add_argument("--backfill-links", action="store_true", help="Fill link4/5/6 for titles and episodes (no TMDb).")
        parser.add_argument("--backfill-tmdb", action="store_true", help="Fetch TMDb and fill popular metadata fields.")

        parser.add_argument("--tv-sync-episodes", action="store_true", help="Ensure TVShowExtras + Seasons + Episodes exist/fill (uses TMDb).")
        parser.add_argument("--tv-fix-missing-episodes", action="store_true", help="Scan TV titles and ONLY sync seasons/episodes for shows missing episodes (or incomplete vs TVShowExtras.number_of_episodes).")
        parser.add_argument("--tv-max-seasons", type=int, default=2)
        parser.add_argument("--skip-specials", action="store_true")

        # LOGGING OPTIONS
        parser.add_argument("--verbose", action="store_true", help="More logs.")
        parser.add_argument("--log-changes", action="store_true", help="Log every row that changed (can be a lot).")
        parser.add_argument("--log-skips", action="store_true", help="Log skips (VERY noisy).")
        parser.add_argument("--progress-every", type=int, default=200, help="Progress log every N titles/episodes.")
        parser.add_argument("--max-log", type=int, default=200, help="Max detailed logs printed for changes/skips.")
        parser.add_argument("--check-dups", action="store_true", help="Print remaining duplicate groups at end.")

    def log(self, msg: str):
        self.stdout.write(msg)

    def maybe_sleep(self, sec: float):
        if sec and sec > 0:
            time.sleep(sec)

    def _step(self, name: str):
        self.log(f"\n========== {name} ==========")

    # -------------------------
    # DEDUPE
    # -------------------------
    def dedupe_titles(self, dry_run: bool, verbose: bool, max_log: int) -> Dict[str, int]:
        stats = {"groups": 0, "titles_deleted": 0, "tvextras_moved": 0, "seasons_moved": 0, "actors_moved": 0}

        qs = (
            Title.objects.exclude(tmdb_id__isnull=True)
            .values("type", "tmdb_id")
            .annotate(cnt=Count("id"), keep_id=Min("id"))
            .filter(cnt__gt=1)
            .order_by("-cnt")
        )
        total = qs.count()
        self.log(f"[dedupe] duplicate groups found={total}")
        if total == 0:
            return stats

        printed = 0
        for g in qs:
            stats["groups"] += 1
            ttype, tmdb_id, keep_id, cnt = g["type"], g["tmdb_id"], g["keep_id"], g["cnt"]

            ids = list(Title.objects.filter(type=ttype, tmdb_id=tmdb_id).values_list("id", flat=True).order_by("id"))
            extra_ids = [i for i in ids if i != keep_id]

            if verbose and printed < max_log:
                self.log(f"[dedupe] group type={ttype} tmdb_id={tmdb_id} cnt={cnt} keep={keep_id} delete={extra_ids[:8]}{'...' if len(extra_ids)>8 else ''}")
                printed += 1

            if dry_run:
                continue

            with transaction.atomic():
                stats["tvextras_moved"] += TVShowExtras.objects.filter(title_id__in=extra_ids).update(title_id=keep_id)
                stats["seasons_moved"] += Season.objects.filter(tv_id__in=extra_ids).update(tv_id=keep_id)
                stats["actors_moved"] += Actor.objects.filter(title_id__in=extra_ids).update(title_id=keep_id)
                deleted, _ = Title.objects.filter(id__in=extra_ids).delete()
                stats["titles_deleted"] += deleted

        self.log(f"[dedupe] DONE groups={stats['groups']} titles_deleted={stats['titles_deleted']} "
                 f"tvextras_moved={stats['tvextras_moved']} seasons_moved={stats['seasons_moved']} actors_moved={stats['actors_moved']}")
        return stats

    # -------------------------
    # BACKFILL LINKS (NO TMDB)
    # -------------------------
    def backfill_links(self, dry_run: bool, overwrite: bool, verbose: bool,
                       log_changes: bool, log_skips: bool, progress_every: int, max_log: int) -> Dict[str, int]:
        stats = {"titles_scanned": 0, "titles_changed": 0, "episodes_scanned": 0, "episodes_changed": 0}
        printed = 0

        def log_change(msg: str):
            nonlocal printed
            if printed < max_log:
                self.log(msg)
                printed += 1

        self.log("[backfill-links] titles...")

        title_qs = Title.objects.filter(type__in=["movie", "tv"]).exclude(Q(tmdb_id__isnull=True) | Q(tmdb_id=0)).order_by("id")
        buf: List[Title] = []
        for i, t in enumerate(title_qs.iterator(chunk_size=2000), start=1):
            stats["titles_scanned"] += 1
            changed = False

            if t.type == "movie":
                links = movie_title_links(int(t.tmdb_id), t.imdb_code)
            else:
                links = tv_title_links(int(t.tmdb_id))

            for f in ("video_url", "movie_link2", "movie_link3", "movie_link4", "movie_link5", "movie_link6"):
                if hasattr(t, f) and fill_field(t, f, links.get(f, ""), overwrite=overwrite):
                    changed = True

            if changed:
                stats["titles_changed"] += 1
                buf.append(t)
                if (log_changes or verbose) and printed < max_log:
                    log_change(f"[backfill-links][TITLE][UPDATE] id={t.id} type={t.type} tmdb={t.tmdb_id} title={t.title}")
            else:
                if log_skips and printed < max_log:
                    log_change(f"[backfill-links][TITLE][SKIP] id={t.id} type={t.type} tmdb={t.tmdb_id} title={t.title}")

            if progress_every and (i % progress_every == 0):
                self.log(f"[backfill-links] progress titles scanned={stats['titles_scanned']} changed={stats['titles_changed']}")

        if buf and not dry_run:
            Title.objects.bulk_update(
                buf,
                fields=[f for f in ("video_url", "movie_link2", "movie_link3", "movie_link4", "movie_link5", "movie_link6") if hasattr(Title, f)]
            )

        self.log("[backfill-links] episodes...")

        eps = Episode.objects.select_related("season", "season__tv").order_by("id")
        ep_buf: List[Episode] = []
        for j, ep in enumerate(eps.iterator(chunk_size=2000), start=1):
            stats["episodes_scanned"] += 1
            tv = getattr(ep.season, "tv", None) if getattr(ep, "season", None) else None
            if not tv or not tv.tmdb_id:
                continue

            links = episode_links(int(tv.tmdb_id), int(ep.season.season_number), int(ep.episode_number))

            changed = False
            for f in ("video_url", "episode_link2", "episode_link3", "episode_link4", "episode_link5", "episode_link6"):
                if hasattr(ep, f) and fill_field(ep, f, links.get(f, ""), overwrite=overwrite):
                    changed = True

            if changed:
                stats["episodes_changed"] += 1
                ep_buf.append(ep)
                if (log_changes or verbose) and printed < max_log:
                    log_change(f"[backfill-links][EP][UPDATE] ep_id={ep.id} tv_tmdb={tv.tmdb_id} S{ep.season.season_number}E{ep.episode_number} name={ep.name}")
            else:
                if log_skips and printed < max_log:
                    log_change(f"[backfill-links][EP][SKIP] ep_id={ep.id} tv_tmdb={tv.tmdb_id} S{ep.season.season_number}E{ep.episode_number} name={ep.name}")

            if progress_every and (j % progress_every == 0):
                self.log(f"[backfill-links] progress episodes scanned={stats['episodes_scanned']} changed={stats['episodes_changed']}")

        if ep_buf and not dry_run:
            Episode.objects.bulk_update(
                ep_buf,
                fields=[f for f in ("video_url", "episode_link2", "episode_link3", "episode_link4", "episode_link5", "episode_link6") if hasattr(Episode, f)]
            )

        self.log(f"[backfill-links] DONE titles_scanned={stats['titles_scanned']} titles_changed={stats['titles_changed']} "
                 f"episodes_scanned={stats['episodes_scanned']} episodes_changed={stats['episodes_changed']}")
        return stats

    # -------------------------
    # BACKFILL TMDB
    # -------------------------
    def backfill_tmdb(self, tmdb: TMDbClient, dry_run: bool, overwrite: bool, sleep_s: float,
                      limit: int, verbose: bool, log_changes: bool, log_skips: bool,
                      progress_every: int, max_log: int,
                      tv_sync_eps: bool, tv_max_seasons: int, skip_specials: bool) -> Dict[str, int]:
        stats = {
            "titles_scanned": 0,
            "titles_changed": 0,
            "titles_errors": 0,
            "tv_extras_upserted": 0,
            "seasons_upserted": 0,
            "episodes_upserted": 0,
        }
        printed = 0

        def log_detail(msg: str):
            nonlocal printed
            if printed < max_log:
                self.log(msg)
                printed += 1

        qs = Title.objects.filter(type__in=["movie", "tv"]).exclude(Q(tmdb_id__isnull=True) | Q(tmdb_id=0)).order_by("id")
        total = qs.count() if limit == 0 else min(limit, qs.count())
        self.log(f"[backfill-tmdb] scanning titles total={total}")

        if limit and limit > 0:
            qs = qs[:limit]

        for idx, t in enumerate(qs.iterator(chunk_size=100), start=1):
            stats["titles_scanned"] += 1

            try:
                changed = False

                if t.type == "movie":
                    full = tmdb.get(f"/movie/{int(t.tmdb_id)}", params={"append_to_response": "credits,videos,keywords"})
                    self.maybe_sleep(sleep_s)

                    ext = {}
                    try:
                        ext = tmdb.get(f"/movie/{int(t.tmdb_id)}/external_ids")
                    except Exception:
                        ext = {}
                    self.maybe_sleep(sleep_s)

                    imdb_code = (ext.get("imdb_id") or t.imdb_code or None)
                    links = movie_title_links(int(t.tmdb_id), imdb_code)

                    row = {
                        "imdb_code": imdb_code,
                        "title": (full.get("title") or full.get("original_title") or "").strip(),
                        "original_title": (full.get("original_title") or "").strip(),
                        "original_language": (full.get("original_language") or "").strip(),
                        "release_date": (full.get("release_date") or "").strip(),
                        "release_year": parse_year_from_ymd(full.get("release_date") or ""),
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
                        "trailer_url": tmdb_trailer_url(full),
                        "genre": ", ".join([g.get("name") for g in (full.get("genres") or []) if g.get("name")]),
                        "keywords": tmdb_movie_keywords(full),
                        "production_companies": [{"id": c.get("id"), "name": c.get("name")} for c in (full.get("production_companies") or [])],
                        "production_countries": [c.get("name") for c in (full.get("production_countries") or []) if c.get("name")],
                        "spoken_languages": [l.get("name") for l in (full.get("spoken_languages") or []) if l.get("name")],
                        "belongs_to_collection": full.get("belongs_to_collection"),
                        "director": tmdb_director(full),
                        "cast": tmdb_cast_names(full, limit=10),
                        # links
                        "video_url": links.get("video_url", ""),
                        "movie_link2": links.get("movie_link2", ""),
                        "movie_link3": links.get("movie_link3", ""),
                        "movie_link4": links.get("movie_link4", ""),
                        "movie_link5": links.get("movie_link5", ""),
                        "movie_link6": links.get("movie_link6", ""),
                    }
                else:
                    full = tmdb.get(f"/tv/{int(t.tmdb_id)}", params={"append_to_response": "credits,videos,keywords"})
                    self.maybe_sleep(sleep_s)
                    links = tv_title_links(int(t.tmdb_id))

                    row = {
                        "title": (full.get("name") or full.get("original_name") or "").strip(),
                        "original_title": (full.get("original_name") or "").strip(),
                        "original_language": (full.get("original_language") or "").strip(),
                        "first_air_date": (full.get("first_air_date") or "").strip(),
                        "description": (full.get("overview") or "").strip(),
                        "status": (full.get("status") or "").strip(),
                        "rating": str(full.get("vote_average") or ""),
                        "vote_average": safe_float(full.get("vote_average")),
                        "vote_count": safe_int(full.get("vote_count")),
                        "popularity": safe_float(full.get("popularity")),
                        "poster": img_url(full.get("poster_path"), "original"),
                        "landscape_image": img_url(full.get("backdrop_path"), "original"),
                        "trailer_url": tmdb_trailer_url(full),
                        "genre": ", ".join([g.get("name") for g in (full.get("genres") or []) if g.get("name")]),
                        "keywords": tmdb_tv_keywords(full),
                        "production_companies": [{"id": c.get("id"), "name": c.get("name")} for c in (full.get("production_companies") or [])],
                        "production_countries": [c.get("name") for c in (full.get("production_countries") or []) if c.get("name")],
                        "spoken_languages": [l.get("name") for l in (full.get("spoken_languages") or []) if l.get("name")],
                        "belongs_to_collection": None,
                        "director": "",
                        "cast": tmdb_cast_names(full, limit=10),
                        # links
                        "video_url": links.get("video_url", ""),
                        "movie_link2": links.get("movie_link2", ""),
                        "movie_link3": links.get("movie_link3", ""),
                        "movie_link4": links.get("movie_link4", ""),
                        "movie_link5": links.get("movie_link5", ""),
                        "movie_link6": links.get("movie_link6", ""),
                    }

                for f, v in row.items():
                    if hasattr(t, f) and fill_field(t, f, v, overwrite=overwrite):
                        changed = True

                if changed:
                    stats["titles_changed"] += 1
                    if (log_changes or verbose) and printed < max_log:
                        log_detail(f"[backfill-tmdb][UPDATE] type={t.type} id={t.id} tmdb={t.tmdb_id} title={t.title}")
                    if not dry_run:
                        t.save()
                else:
                    if log_skips and printed < max_log:
                        log_detail(f"[backfill-tmdb][SKIP] type={t.type} id={t.id} tmdb={t.tmdb_id} title={t.title}")

                # TV extras + optional episodes
                if t.type == "tv":
                    if not dry_run:
                        TVShowExtras.objects.update_or_create(
                            title=t,
                            defaults={
                                "number_of_seasons": safe_int(full.get("number_of_seasons"), 0) or 0,
                                "number_of_episodes": safe_int(full.get("number_of_episodes"), 0) or 0,
                                "in_production": bool(full.get("in_production")),
                                "episode_run_time": full.get("episode_run_time") or [],
                                "network_names": [n.get("name") for n in (full.get("networks") or []) if n.get("name")],
                            },
                        )
                    stats["tv_extras_upserted"] += 1

                    if tv_sync_eps and not dry_run:
                        seasons = full.get("seasons") or []
                        for s in seasons:
                            snum = safe_int(s.get("season_number"))
                            if snum is None:
                                continue
                            if skip_specials and snum == 0:
                                continue
                            if snum <= 0 or snum > tv_max_seasons:
                                continue

                            season_obj, _ = Season.objects.update_or_create(
                                tv=t,
                                season_number=snum,
                                defaults={
                                    "tmdb_id": safe_int(s.get("id")),
                                    "name": s.get("name") or "",
                                    "overview": s.get("overview") or "",
                                    "air_date": s.get("air_date") or "",
                                    "poster": s.get("poster_path") or "",
                                },
                            )
                            stats["seasons_upserted"] += 1

                            sfull = tmdb.get(f"/tv/{int(t.tmdb_id)}/season/{snum}")
                            self.maybe_sleep(sleep_s)

                            for e in (sfull.get("episodes") or []):
                                enum = safe_int(e.get("episode_number"), 0) or 0
                                if enum <= 0:
                                    continue
                                links = episode_links(int(t.tmdb_id), int(snum), int(enum))

                                defaults = {
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

                                ep_obj, created = Episode.objects.get_or_create(
                                    season=season_obj,
                                    episode_number=enum,
                                    defaults=defaults,
                                )
                                if not created:
                                    ep_changed = False
                                    for f, v in defaults.items():
                                        if hasattr(ep_obj, f) and fill_field(ep_obj, f, v, overwrite=overwrite):
                                            ep_changed = True
                                    if ep_changed:
                                        ep_obj.save()

                                stats["episodes_upserted"] += 1

            except Exception as ex:
                stats["titles_errors"] += 1
                if printed < max_log:
                    log_detail(f"[backfill-tmdb][ERROR] type={t.type} id={t.id} tmdb={t.tmdb_id} err={ex}")

            if progress_every and (idx % progress_every == 0):
                self.log(f"[backfill-tmdb] progress scanned={stats['titles_scanned']}/{total} changed={stats['titles_changed']} errors={stats['titles_errors']}")

        self.log(f"[backfill-tmdb] DONE scanned={stats['titles_scanned']} changed={stats['titles_changed']} errors={stats['titles_errors']} "
                 f"tvextras={stats['tv_extras_upserted']} seasons={stats['seasons_upserted']} episodes={stats['episodes_upserted']}")
        return stats

    # -------------------------
    # TV: fix missing episodes (quick scan)
    # -------------------------
    def fix_missing_tv_episodes(
        self,
        dry_run: bool,
        overwrite: bool,
        sleep_s: float,
        tv_max_seasons: int,
        skip_specials: bool,
        verbose: bool,
        progress_every: int,
        max_log: int,
    ) -> Dict[str, int]:
        """
        Find TV Titles that have missing episodes and sync Season/Episode rows from TMDb.
        - If TVShowExtras.number_of_episodes is known, we consider it "complete" when episode_count >= number_of_episodes.
        - Otherwise, we consider it "missing" when episode_count == 0.
        """
        stats = {
            "tv_titles_scanned": 0,
            "tv_titles_fixed": 0,
            "tv_titles_skipped": 0,
            "tv_titles_errors": 0,
            "tv_extras_upserted": 0,
            "seasons_upserted": 0,
            "episodes_upserted": 0,
        }

        tmdb = TMDbClient()
        qs = Title.objects.filter(type="tv").exclude(tmdb_id__isnull=True).order_by("id")
        total = qs.count()
        self.log(f"[tv-fix-missing] START total_tv={total} tv_max_seasons={tv_max_seasons} skip_specials={skip_specials}")

        printed = 0
        for idx, t in enumerate(qs, start=1):
            stats["tv_titles_scanned"] += 1
            try:
                # current state
                current_eps = Episode.objects.filter(season__tv=t).count()
                extras = TVShowExtras.objects.filter(title=t).first()
                expected_eps = int(getattr(extras, "number_of_episodes", 0) or 0)

                missing = (expected_eps > 0 and current_eps < expected_eps) or (expected_eps == 0 and current_eps == 0)
                null_tmdb = Episode.objects.filter(season__tv=t, tmdb_id__isnull=True).exists()
                missing = missing or null_tmdb
                if missing and null_tmdb and verbose:
                    self.log(f"[tv-fix-missing] title_id={t.id} tmdb={t.tmdb_id} has episodes with NULL tmdb_id; will resync")
                if not missing:
                    stats["tv_titles_skipped"] += 1
                    continue

                full = tmdb.get(f"/tv/{int(t.tmdb_id)}", params={"append_to_response": "credits,keywords"})
                if not dry_run:
                    TVShowExtras.objects.update_or_create(
                        title=t,
                        defaults={
                            "number_of_seasons": safe_int(full.get("number_of_seasons"), 0) or 0,
                            "number_of_episodes": safe_int(full.get("number_of_episodes"), 0) or 0,
                            "in_production": bool(full.get("in_production")),
                            "episode_run_time": full.get("episode_run_time") or [],
                            "network_names": [n.get("name") for n in (full.get("networks") or []) if n.get("name")],
                        },
                    )
                stats["tv_extras_upserted"] += 1

                seasons = full.get("seasons") or []
                for s in seasons:
                    snum = safe_int(s.get("season_number"))
                    if snum is None:
                        continue
                    if skip_specials and snum == 0:
                        continue
                    if tv_max_seasons and snum > tv_max_seasons:
                        continue

                    defaults_s = {
                        "tmdb_id": safe_int(s.get("id")),
                        "name": s.get("name") or "",
                        "overview": s.get("overview") or "",
                        "air_date": s.get("air_date") or "",
                        "poster": s.get("poster_path") or "",
                    }

                    if dry_run:
                        season_obj = Season(tv=t, season_number=snum, **defaults_s)
                        created_season = True
                    else:
                        season_obj, created_season = Season.objects.update_or_create(
                            tv=t,
                            season_number=snum,
                            defaults=defaults_s,
                        )
                    stats["seasons_upserted"] += 1

                    # now episodes for that season
                    sfull = tmdb.get(f"/tv/{int(t.tmdb_id)}/season/{snum}", params={})
                    eps = sfull.get("episodes") or []

                    if verbose and printed < max_log:
                        self.log(f"[tv-fix-missing] tv_id={t.id} tmdb={t.tmdb_id} season={snum} episodes={len(eps)}")
                        printed += 1

                    for e in eps:
                        enum = safe_int(e.get("episode_number"), 0) or 0
                        links = episode_links(int(t.tmdb_id), snum, enum)
                        defaults_e = {
                            "tmdb_id": safe_int(e.get("id")),
                            "name": e.get("name") or "",
                            "overview": e.get("overview") or "",
                            "air_date": e.get("air_date") or "",
                            "still_path": e.get("still_path") or "",
                            "vote_average": e.get("vote_average"),
                            "vote_count": e.get("vote_count"),
                            "runtime": e.get("runtime"),
                            "imdb_code": None,
                            "video_url": links["video_url"],
                            "episode_link2": links["episode_link2"],
                            "episode_link3": links["episode_link3"],
                            "episode_link4": links["episode_link4"],
                            "episode_link5": links["episode_link5"],
                            "episode_link6": links["episode_link6"],
                        }

                        if dry_run:
                            stats["episodes_upserted"] += 1
                            continue

                        ep_obj, created = Episode.objects.update_or_create(
                            season=season_obj,
                            episode_number=enum,
                            defaults=defaults_e,
                        )
                        # If overwrite=False, we still want to preserve existing non-empty fields;
                        # update_or_create already set defaults (overwrites). So we re-apply fill-only logic when overwrite is False.
                        if not overwrite:
                            ep_changed = False
                            for f, v in defaults_e.items():
                                if hasattr(ep_obj, f) and fill_field(ep_obj, f, v, overwrite=False):
                                    ep_changed = True
                            if ep_changed and not created:
                                ep_obj.save()

                        stats["episodes_upserted"] += 1

                stats["tv_titles_fixed"] += 1

            except Exception as ex:
                stats["tv_titles_errors"] += 1
                if printed < max_log:
                    self.log(f"[tv-fix-missing][ERROR] title_id={t.id} tmdb={t.tmdb_id} err={ex}")

            if progress_every and (idx % progress_every == 0):
                self.log(
                    f"[tv-fix-missing] progress {idx}/{total} fixed={stats['tv_titles_fixed']} skipped={stats['tv_titles_skipped']} errors={stats['tv_titles_errors']}"
                )

            if sleep_s:
                self.maybe_sleep(sleep_s)

        self.log(
            f"[tv-fix-missing] DONE scanned={stats['tv_titles_scanned']} fixed={stats['tv_titles_fixed']} "
            f"skipped={stats['tv_titles_skipped']} errors={stats['tv_titles_errors']} "
            f"tvextras={stats['tv_extras_upserted']} seasons={stats['seasons_upserted']} episodes={stats['episodes_upserted']}"
        )
        return stats

    def check_dups(self):
        qs = (
            Title.objects.exclude(tmdb_id__isnull=True)
            .values("type", "tmdb_id")
            .annotate(c=Count("id"))
            .filter(c__gt=1)
            .order_by("-c")
        )
        n = qs.count()
        if n == 0:
            self.log("[check-dups] OK: no duplicate groups remain.")
            return
        self.log(f"[check-dups] WARNING: still {n} duplicate groups. First 25:")
        for row in qs[:25]:
            self.log(f"  - type={row['type']} tmdb_id={row['tmdb_id']} count={row['c']}")

    def handle(self, *args, **opts):
        dry_run = bool(opts["dry_run"])
        overwrite = bool(opts["overwrite"])
        sleep_s = float(opts["sleep"])
        limit = int(opts["limit"] or 0)

        do_dedupe = bool(opts["dedupe"])
        do_backfill_links = bool(opts["backfill_links"])
        do_backfill_tmdb = bool(opts["backfill_tmdb"])

        tv_sync_eps = bool(opts["tv_sync_episodes"])
        do_tv_fix_missing = bool(opts.get("tv_fix_missing_episodes"))
        tv_max_seasons = int(opts["tv_max_seasons"])
        skip_specials = bool(opts["skip_specials"])

        verbose = bool(opts["verbose"])
        log_changes = bool(opts["log_changes"])
        log_skips = bool(opts["log_skips"])
        progress_every = int(opts["progress_every"])
        max_log = int(opts["max_log"])

        check_dups = bool(opts["check_dups"])

        self.log("===============================================")
        self.log("[clean_db] START")
        self.log(f"dry_run={dry_run} overwrite={overwrite} sleep={sleep_s}s limit={limit or 'ALL'}")
        self.log(f"dedupe={do_dedupe} backfill_links={do_backfill_links} backfill_tmdb={do_backfill_tmdb}")
        self.log(f"tv_sync_episodes={tv_sync_eps} tv_fix_missing_episodes={do_tv_fix_missing} tv_max_seasons={tv_max_seasons} skip_specials={skip_specials}")
        self.log(f"logs: verbose={verbose} log_changes={log_changes} log_skips={log_skips} progress_every={progress_every} max_log={max_log}")
        self.log("===============================================")

        t0 = now_s()

        if do_dedupe:
            self._step("STEP 1/3 - DEDUPE TITLES")
            self.dedupe_titles(dry_run=dry_run, verbose=verbose, max_log=max_log)

        if do_backfill_links:
            self._step("STEP 2/3 - BACKFILL LINKS (NO TMDB)")
            self.backfill_links(
                dry_run=dry_run,
                overwrite=overwrite,
                verbose=verbose,
                log_changes=log_changes,
                log_skips=log_skips,
                progress_every=progress_every,
                max_log=max_log,
            )

        if do_backfill_tmdb:
            self._step("STEP 3/3 - BACKFILL TMDB (POPULAR FIELDS)")
            tmdb = TMDbClient()
            self.backfill_tmdb(
                tmdb=tmdb,
                dry_run=dry_run,
                overwrite=overwrite,
                sleep_s=sleep_s,
                limit=limit,
                verbose=verbose,
                log_changes=log_changes,
                log_skips=log_skips,
                progress_every=progress_every,
                max_log=max_log,
                tv_sync_eps=tv_sync_eps,
                tv_max_seasons=tv_max_seasons,
                skip_specials=skip_specials,
            )

        if do_tv_fix_missing:
            self._step("TV FIX MISSING EPISODES")
            self.fix_missing_tv_episodes(
                dry_run=dry_run,
                overwrite=overwrite,
                sleep_s=sleep_s,
                tv_max_seasons=tv_max_seasons,
                skip_specials=skip_specials,
                verbose=verbose,
                progress_every=progress_every,
                max_log=max_log,
            )

        if check_dups:
            self._step("POST CHECK - DUPLICATES")
            self.check_dups()

        dt = now_s() - t0
        self.log(f"\n[clean_db] DONE elapsed={dt:.1f}s")

"""
=========================================================
COMMANDES RECOMMANDÉES (avec logs)
=========================================================

# A) DRY RUN (voir les logs sans rien changer)
python manage.py clean_db --dedupe --backfill-links --backfill-tmdb --tv-sync-episodes --tv-max-seasons 2 --check-dups --dry-run --verbose --progress-every 200

# B) Nettoyage complet + logs (recommandé)
python manage.py clean_db --dedupe --backfill-links --backfill-tmdb --tv-sync-episodes --tv-max-seasons 2 --check-dups --verbose --progress-every 200

# C) Nettoyage complet + log chaque changement (plus verbeux)
python manage.py clean_db --dedupe --backfill-links --backfill-tmdb --tv-sync-episodes --tv-max-seasons 2 --check-dups --verbose --log-changes --progress-every 100 --max-log 500

# D) Juste enlever doublons
python manage.py clean_db --dedupe --check-dups --verbose

# E) Juste remplir les liens (rapide, pas de TMDb)
python manage.py clean_db --backfill-links --verbose --log-changes --progress-every 500

# F) Juste backfill TMDb (metadata manquante)
python manage.py clean_db --backfill-tmdb --sleep 0.2 --verbose --progress-every 200
=========================================================
"""
#python manage.py clean_db --dedupe --backfill-links --backfill-tmdb --tv-sync-episodes --tv-max-seasons 2 --check-dups --verbose --progress-every 200
#python manage.py clean_db --tv-fix-missing-episodes --tv-max-seasons 2 --skip-specials --verbose
