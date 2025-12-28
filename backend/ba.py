# backfill_links.py
import os
import sys
import time
from typing import Dict, Optional, List, Tuple

# ======================
# 1) Django bootstrap
# ======================
DJANGO_SETTINGS_MODULE = os.environ.get("DJANGO_SETTINGS_MODULE", "streaming_backend.settings")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", DJANGO_SETTINGS_MODULE)

import django  # noqa
django.setup()

from django.db import transaction  # noqa
from django.db.models import Q  # noqa

# EDIT if your models are elsewhere
from users.models import Title, Episode  # noqa


# ==========================================
# 2) Provider URL templates (authorized only)
# ==========================================
# Movies: use {tmdb_id}
# TV (title -> S1E1): use {tmdb_id}/{season}/{episode} with season=1 episode=1
# Episodes: use {tmdb_id}/{season}/{episode}

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

# Overwrite even if a field is already set
FORCE_OVERWRITE = True

# Batch size for bulk_update
BATCH = 2000

# Print a few example updates
SHOW_EXAMPLES = True
MAX_EXAMPLES = 8

# ======================
# 3) Logging helpers
# ======================
def log(msg: str):
    print(msg, flush=True)

def pct(n: int, d: int) -> str:
    if d <= 0:
        return "0%"
    return f"{(n * 100.0 / d):.1f}%"

def safe_get(obj, name: str, default=""):
    try:
        return getattr(obj, name)
    except Exception:
        return default

def fmt(template: str, tmdb_id: int, season: Optional[int] = None, episode: Optional[int] = None) -> str:
    if not template or not tmdb_id:
        return ""
    try:
        return template.format(tmdb_id=tmdb_id, season=season, episode=episode)
    except Exception:
        return ""

def model_has_field(model, field_name: str) -> bool:
    # works for model instances + class
    return hasattr(model, field_name)


def bulk_flush_titles(buf: List[Title], fields: List[str]) -> int:
    if not buf:
        return 0
    Title.objects.bulk_update(buf, fields)
    return len(buf)

def bulk_flush_episodes(buf: List[Episode], fields: List[str]) -> int:
    if not buf:
        return 0
    Episode.objects.bulk_update(buf, fields)
    return len(buf)


# ======================
# 4) Backfill Titles
# ======================
def backfill_titles_movies() -> Tuple[int, int]:
    """
    Fill movie_link4/5/6 for Title(type='movie') using {tmdb_id}
    Returns: (rows_scanned, rows_updated)
    """
    fields = [f for f in ("movie_link4", "movie_link5", "movie_link6") if model_has_field(Title, f)]
    if not fields:
        log("[Titles:movies] No fields found on Title model (movie_link4/5/6). Skipping.")
        return (0, 0)

    qs = Title.objects.filter(type="movie").exclude(Q(tmdb_id__isnull=True) | Q(tmdb_id=0))
    total = qs.count()
    log(f"[Titles:movies] Scanning {total} rows. Fields={fields} FORCE_OVERWRITE={FORCE_OVERWRITE}")

    scanned = 0
    updated = 0
    buf: List[Title] = []
    examples: List[str] = []

    t0 = time.time()
    for t in qs.iterator(chunk_size=BATCH):
        scanned += 1
        changed = False

        for f in fields:
            old = safe_get(t, f, "") or ""
            if (not FORCE_OVERWRITE) and old:
                continue

            url = fmt(TEMPLATES.get(f, ""), tmdb_id=t.tmdb_id)
            if url and url != old:
                setattr(t, f, url)
                changed = True
                if SHOW_EXAMPLES and len(examples) < MAX_EXAMPLES:
                    examples.append(f"Title(movie) id={t.id} tmdb={t.tmdb_id} set {f}={url}")

        if changed:
            buf.append(t)

        if len(buf) >= BATCH:
            n = bulk_flush_titles(buf, fields)
            updated += n
            log(f"[Titles:movies] batch flush: wrote {n} rows | progress {scanned}/{total} ({pct(scanned,total)})")
            buf.clear()

        if scanned % 5000 == 0:
            dt = time.time() - t0
            log(f"[Titles:movies] progress {scanned}/{total} ({pct(scanned,total)}) elapsed={dt:.1f}s")

    if buf:
        n = bulk_flush_titles(buf, fields)
        updated += n
        log(f"[Titles:movies] final flush: wrote {n} rows")

    dt = time.time() - t0
    log(f"[Titles:movies] DONE scanned={scanned} updated={updated} elapsed={dt:.1f}s")
    if examples:
        log("[Titles:movies] Examples:")
        for ex in examples:
            log(f"  - {ex}")

    return (scanned, updated)


def backfill_titles_tv_to_s1e1() -> Tuple[int, int]:
    """
    Fill movie_link4/5/6 for Title(type='tv') pointing to season=1 episode=1
    Returns: (rows_scanned, rows_updated)
    """
    # We write into movie_link4/5/6 (your new attributes on Title),
    # but using tv templates (tv_link4/5/6) with season=1 episode=1.
    title_fields = [f for f in ("movie_link4", "movie_link5", "movie_link6") if model_has_field(Title, f)]
    if not title_fields:
        log("[Titles:tv] No fields found on Title model (movie_link4/5/6). Skipping.")
        return (0, 0)

    # map title field -> template key
    mapping = {
        "movie_link4": "tv_link4",
        "movie_link5": "tv_link5",
        "movie_link6": "tv_link6",
    }

    qs = Title.objects.filter(type="tv").exclude(Q(tmdb_id__isnull=True) | Q(tmdb_id=0))
    total = qs.count()
    log(f"[Titles:tv] Scanning {total} rows. Will point to S1E1. Fields={title_fields} FORCE_OVERWRITE={FORCE_OVERWRITE}")

    scanned = 0
    updated = 0
    buf: List[Title] = []
    examples: List[str] = []

    t0 = time.time()
    for t in qs.iterator(chunk_size=BATCH):
        scanned += 1
        changed = False

        for f in title_fields:
            tpl_key = mapping.get(f)
            template = TEMPLATES.get(tpl_key, "")
            old = safe_get(t, f, "") or ""
            if (not FORCE_OVERWRITE) and old:
                continue

            url = fmt(template, tmdb_id=t.tmdb_id, season=1, episode=1)
            if url and url != old:
                setattr(t, f, url)
                changed = True
                if SHOW_EXAMPLES and len(examples) < MAX_EXAMPLES:
                    examples.append(f"Title(tv) id={t.id} tmdb={t.tmdb_id} set {f}={url}")

        if changed:
            buf.append(t)

        if len(buf) >= BATCH:
            n = bulk_flush_titles(buf, title_fields)
            updated += n
            log(f"[Titles:tv] batch flush: wrote {n} rows | progress {scanned}/{total} ({pct(scanned,total)})")
            buf.clear()

        if scanned % 5000 == 0:
            dt = time.time() - t0
            log(f"[Titles:tv] progress {scanned}/{total} ({pct(scanned,total)}) elapsed={dt:.1f}s")

    if buf:
        n = bulk_flush_titles(buf, title_fields)
        updated += n
        log(f"[Titles:tv] final flush: wrote {n} rows")

    dt = time.time() - t0
    log(f"[Titles:tv] DONE scanned={scanned} updated={updated} elapsed={dt:.1f}s")
    if examples:
        log("[Titles:tv] Examples:")
        for ex in examples:
            log(f"  - {ex}")

    return (scanned, updated)


# ======================
# 5) Backfill Episodes
# ======================
def backfill_episodes() -> Tuple[int, int, int]:
    """
    Fill episode_link4/5/6 for Episodes using tv.tmdb_id + season_number + episode_number
    Returns: (rows_scanned, rows_updated, rows_skipped_missing_data)
    """
    fields = [f for f in ("episode_link4", "episode_link5", "episode_link6") if model_has_field(Episode, f)]
    if not fields:
        log("[Episodes] No fields found on Episode model (episode_link4/5/6). Skipping.")
        return (0, 0, 0)

    qs = (
        Episode.objects.select_related("season", "season__tv")
        .exclude(Q(season__tv__tmdb_id__isnull=True) | Q(season__tv__tmdb_id=0))
    )
    total = qs.count()
    log(f"[Episodes] Scanning {total} rows. Fields={fields} FORCE_OVERWRITE={FORCE_OVERWRITE}")

    scanned = 0
    updated = 0
    skipped = 0
    buf: List[Episode] = []
    examples: List[str] = []

    t0 = time.time()
    for ep in qs.iterator(chunk_size=BATCH):
        scanned += 1

        tv = safe_get(ep.season, "tv", None)
        tmdb_id = safe_get(tv, "tmdb_id", None)
        s = safe_get(ep.season, "season_number", None)
        e = safe_get(ep, "episode_number", None)

        if not tmdb_id or s is None or e is None:
            skipped += 1
            continue

        changed = False
        for f in fields:
            old = safe_get(ep, f, "") or ""
            if (not FORCE_OVERWRITE) and old:
                continue

            url = fmt(TEMPLATES.get(f, ""), tmdb_id=tmdb_id, season=s, episode=e)
            if url and url != old:
                setattr(ep, f, url)
                changed = True
                if SHOW_EXAMPLES and len(examples) < MAX_EXAMPLES:
                    examples.append(f"Episode id={ep.id} tv_tmdb={tmdb_id} S{s}E{e} set {f}={url}")

        if changed:
            buf.append(ep)

        if len(buf) >= BATCH:
            n = bulk_flush_episodes(buf, fields)
            updated += n
            log(f"[Episodes] batch flush: wrote {n} rows | progress {scanned}/{total} ({pct(scanned,total)}) | skipped={skipped}")
            buf.clear()

        if scanned % 5000 == 0:
            dt = time.time() - t0
            log(f"[Episodes] progress {scanned}/{total} ({pct(scanned,total)}) skipped={skipped} elapsed={dt:.1f}s")

    if buf:
        n = bulk_flush_episodes(buf, fields)
        updated += n
        log(f"[Episodes] final flush: wrote {n} rows")

    dt = time.time() - t0
    log(f"[Episodes] DONE scanned={scanned} updated={updated} skipped_missing={skipped} elapsed={dt:.1f}s")
    if examples:
        log("[Episodes] Examples:")
        for ex in examples:
            log(f"  - {ex}")

    return (scanned, updated, skipped)


# ======================
# 6) Main
# ======================
@transaction.atomic
def main():
    log("========================================")
    log("Backfill provider links starting…")
    log(f"DJANGO_SETTINGS_MODULE={DJANGO_SETTINGS_MODULE}")
    log(f"FORCE_OVERWRITE={FORCE_OVERWRITE} BATCH={BATCH}")
    log(f"SHOW_EXAMPLES={SHOW_EXAMPLES} MAX_EXAMPLES={MAX_EXAMPLES}")
    log("========================================")

    # Sanity logs: which fields exist
    title_fields_exist = [f for f in ("movie_link4", "movie_link5", "movie_link6") if model_has_field(Title, f)]
    ep_fields_exist = [f for f in ("episode_link4", "episode_link5", "episode_link6") if model_has_field(Episode, f)]
    log(f"[Sanity] Title fields found: {title_fields_exist}")
    log(f"[Sanity] Episode fields found: {ep_fields_exist}")

    t0 = time.time()
    m_scanned, m_updated = backfill_titles_movies()
    tv_scanned, tv_updated = backfill_titles_tv_to_s1e1()
    e_scanned, e_updated, e_skipped = backfill_episodes()
    dt = time.time() - t0

    log("========================================")
    log("[SUMMARY]")
    log(f"Titles(movie): scanned={m_scanned} updated={m_updated}")
    log(f"Titles(tv->S1E1): scanned={tv_scanned} updated={tv_updated}")
    log(f"Episodes: scanned={e_scanned} updated={e_updated} skipped_missing={e_skipped}")
    log(f"TOTAL elapsed={dt:.1f}s")
    log("========================================")
    log("DONE.")


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        print(f"[ERROR] {ex}", flush=True)
        sys.exit(1)