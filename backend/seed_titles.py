# seed_titles.py
# Populate Movies (from IMDb IDs OR TMDB movie IDs) and TV Shows (from TMDB TV IDs OR IMDb series IDs)
#
# Examples:
#   python seed_titles.py --mode movies --ids-file imdb_or_tmdb_movie_ids.txt
#   python seed_titles.py --mode tv --ids-file tv_ids.txt
#   python seed_titles.py --mode tv --ids-file tv_ids.txt --skip-existing-tmdb
#   python seed_titles.py --mode tv --ids-file tv_ids.txt --with-episode-imdb   (SLOW)

import os
import sys
import argparse
from typing import Dict, Any, Optional, List, Tuple

import requests

# --- Bootstrap Django ---
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "streaming_backend.settings")
import django  # noqa: E402
django.setup()  # noqa: E402

from users.models import Title, Season, Episode, TVShowExtras  # noqa: E402

TMDB_KEY = "f6988ac086c88bbfe779ab0ed2eed215"  # your key from current file
SKIP_SPECIALS = True  # skip TMDB season_number==0

# ========= HTTP / TMDB helpers =========

def _http_get(path: str, **params) -> Dict[str, Any]:
    base = "https://api.themoviedb.org/3"
    params.setdefault("api_key", TMDB_KEY)
    r = requests.get(f"{base}{path}", params=params, timeout=25)
    r.raise_for_status()
    return r.json()

def _tmdb_img_url(path: Optional[str], size: str = "original") -> str:
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else ""

def tmdb_find_by_imdb(imdb_code: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Returns (movie_tmdb_id, tv_tmdb_id) for an IMDb id.
    Exactly one will typically be non-null.
    """
    data = _http_get(f"/find/{imdb_code}", external_source="imdb_id")
    mid = (data.get("movie_results") or [{}])[0].get("id") if data.get("movie_results") else None
    tid = (data.get("tv_results") or [{}])[0].get("id") if data.get("tv_results") else None
    return mid, tid

# ---- movie fetchers ----

def tmdb_movie_full(tmdb_id: int) -> Dict[str, Any]:
    return _http_get(f"/movie/{tmdb_id}", append_to_response="credits,videos,images,keywords")

def tmdb_director(tmdb: Dict[str, Any]) -> str:
    for c in (tmdb.get("credits", {}) or {}).get("crew", []):
        if c.get("job") == "Director":
            return c.get("name") or ""
    return ""

def tmdb_cast_names(tmdb: Dict[str, Any], limit: int = 10) -> List[str]:
    return [c.get("name") for c in (tmdb.get("credits", {}) or {}).get("cast", []) if c.get("name")][:limit]

def tmdb_trailer_url(tmdb: Dict[str, Any]) -> str:
    for v in (tmdb.get("videos", {}) or {}).get("results", []):
        if v.get("site") == "YouTube" and v.get("type") == "Trailer":
            key = v.get("key")
            if key:
                return f"https://www.youtube.com/watch?v={key}"
    return ""

# ---- tv fetchers ----

def tmdb_tv_full(tv_id: int) -> Dict[str, Any]:
    return _http_get(f"/tv/{tv_id}", append_to_response="credits,videos,keywords")

def tmdb_season_full(tv_id: int, season_number: int) -> Dict[str, Any]:
    return _http_get(f"/tv/{tv_id}/season/{season_number}")

def tmdb_episode_external_ids(tv_id: int, season_number: int, episode_number: int) -> Dict[str, Any]:
    return _http_get(f"/tv/{tv_id}/season/{season_number}/episode/{episode_number}/external_ids")

# ========= Link builders =========

def movie_title_links(tmdb_id: Optional[int], imdb_code: Optional[str]) -> Dict[str, str]:
    return {
        "video_url":   f"https://www.vidking.net/embed/movie/{tmdb_id}" if tmdb_id else "",
        "movie_link2": f"https://player.videasy.net/movie/{tmdb_id}" if tmdb_id else "",
        "movie_link3": f"https://vidsrc.xyz/embed/movie/{imdb_code}" if imdb_code else "",
    }

def tv_title_links(tmdb_id: int) -> Dict[str, str]:
    """ Title-level default links (S1E1 with selector=true), all using TMDB id per your spec. """
    return {
        "video_url":   f"https://www.vidking.net/embed/tv/{tmdb_id}/1/1?episodeSelector=true",
        "movie_link2": f"https://player.videasy.net/tv/{tmdb_id}/1/1?episodeSelector=true",
        "movie_link3": f"https://vidsrc.xyz/embed/tv/{tmdb_id}/1-1",
    }

def episode_links(tv_tmdb_id: int, season: int, episode: int) -> Dict[str, str]:
    """ Build episode links. ALL THREE use TMDB for TV; vidsrc uses TMDB too. """
    return {
        "video_url":     f"https://www.vidking.net/embed/tv/{tv_tmdb_id}/{season}/{episode}",
        "episode_link2": f"https://player.videasy.net/tv/{tv_tmdb_id}/{season}/{episode}",
        "episode_link3": f"https://vidsrc.xyz/embed/tv/{tv_tmdb_id}/{season}-{episode}",
    }

# ========= DB helpers (skip existing) =========

def movie_exists_tmdb(tmdb_id: int) -> bool:
    return Title.objects.filter(type="movie", tmdb_id=tmdb_id).exists()

def tv_exists_tmdb(tv_id: int) -> bool:
    return Title.objects.filter(type="tv", tmdb_id=tv_id).exists()

# ========= Upserts =========

def upsert_movie_from_tmdb(imdb_code: Optional[str], tmdb: Dict[str, Any], overwrite: bool = False) -> str:
    tmdb_id = tmdb.get("id")
    links = movie_title_links(tmdb_id, imdb_code)

    row = {
        "type": "movie",
        "imdb_code": imdb_code,
        "tmdb_id": tmdb_id,
        "title": tmdb.get("title") or tmdb.get("original_title") or "",
        "original_title": tmdb.get("original_title") or "",
        "original_language": tmdb.get("original_language") or "",
        "release_date": tmdb.get("release_date") or "",
        "release_year": int((tmdb.get("release_date") or "0000")[:4]) if tmdb.get("release_date") else None,
        "runtime_minutes": tmdb.get("runtime"),
        "description": tmdb.get("overview") or "",
        "tagline": tmdb.get("tagline") or "",
        "status": tmdb.get("status") or "",
        "rating": str(tmdb.get("vote_average") or ""),
        "vote_average": tmdb.get("vote_average"),
        "vote_count": tmdb.get("vote_count"),
        "popularity": tmdb.get("popularity"),
        "poster": _tmdb_img_url(tmdb.get("poster_path")),
        "landscape_image": _tmdb_img_url(tmdb.get("backdrop_path")),
        "video_url": links["video_url"],
        "movie_link2": links["movie_link2"],
        "movie_link3": links["movie_link3"],
        "trailer_url": tmdb_trailer_url(tmdb),
        "genre": ", ".join([g["name"] for g in tmdb.get("genres", []) if g.get("name")]),
        "keywords": [k.get("name") for k in (tmdb.get("keywords") or {}).get("keywords", []) if k.get("name")],
        "production_companies": [{"id": c.get("id"), "name": c.get("name")} for c in (tmdb.get("production_companies") or [])],
        "production_countries": [c.get("name") for c in (tmdb.get("production_countries") or [])],
        "spoken_languages": [l.get("name") for l in (tmdb.get("spoken_languages") or [])],
        "belongs_to_collection": tmdb.get("belongs_to_collection"),
        "director": tmdb_director(tmdb),
        "cast": tmdb_cast_names(tmdb),
    }

    qs = Title.objects.filter(type="movie", tmdb_id=tmdb_id) if tmdb_id else Title.objects.filter(type="movie", imdb_code=imdb_code)
    if not qs.exists():
        Title.objects.create(**row)
        return "CREATED"

    updated_any = False
    for t in qs:
        for f, val in row.items():
            curr = getattr(t, f, None)
            if overwrite:
                if val != curr:
                    setattr(t, f, val); updated_any = True
            else:
                if (curr in (None, "", [])) and val not in (None, "", []):
                    setattr(t, f, val); updated_any = True
        if updated_any:
            t.save()
    return "UPDATED" if updated_any else "SKIPPED"

def upsert_tv_from_tmdb(tv: Dict[str, Any], overwrite: bool = False, with_episode_imdb: bool = False, verbose: bool = False) -> str:
    tv_id = tv.get("id")
    title_links = tv_title_links(tv_id)

    base_row = {
        "type": "tv",
        "imdb_code": None,  # series-level IMDb often not present in TMDB
        "tmdb_id": tv_id,
        "title": tv.get("name") or tv.get("original_name") or "",
        "original_title": tv.get("original_name") or "",
        "original_language": tv.get("original_language") or "",
        "first_air_date": tv.get("first_air_date") or "",
        "description": tv.get("overview") or "",
        "status": tv.get("status") or "",
        "rating": str(tv.get("vote_average") or ""),
        "vote_average": tv.get("vote_average"),
        "vote_count": tv.get("vote_count"),
        "popularity": tv.get("popularity"),
        "poster": _tmdb_img_url(tv.get("poster_path")),
        "landscape_image": _tmdb_img_url(tv.get("backdrop_path")),
        # Title-level TV links (S1E1 + selector)
        "video_url": title_links["video_url"],
        "movie_link2": title_links["movie_link2"],
        "movie_link3": title_links["movie_link3"],
        "trailer_url": tmdb_trailer_url(tv),
        "genre": ", ".join([g["name"] for g in tv.get("genres", []) if g.get("name")]),
        "keywords": [k.get("name") for k in (tv.get("keywords") or {}).get("results", []) if k.get("name")],
        "production_companies": [{"id": c.get("id"), "name": c.get("name")} for c in (tv.get("production_companies") or [])],
        "production_countries": [c.get("name") for c in (tv.get("production_countries") or [])],
        "spoken_languages": [l.get("name") for l in (tv.get("spoken_languages") or [])],
        "belongs_to_collection": None,
        "director": "",  # directors are episode-level
        "cast": [c.get("name") for c in (tv.get("credits") or {}).get("cast", []) if c.get("name")][:10],
    }

    # upsert Title
    t_qs = Title.objects.filter(type="tv", tmdb_id=tv_id)
    if not t_qs.exists():
        title = Title.objects.create(**base_row)
        created_title = True
    else:
        title = t_qs.first()
        created_title = False
        changed = False
        for f, val in base_row.items():
            curr = getattr(title, f, None)
            if overwrite:
                if val != curr:
                    setattr(title, f, val); changed = True
            else:
                if (curr in (None, "", [])) and val not in (None, "", []):
                    setattr(title, f, val); changed = True
        if changed:
            title.save()

    # upsert TV extras
    TVShowExtras.objects.update_or_create(
        title=title,
        defaults={
            "number_of_seasons": tv.get("number_of_seasons") or 0,
            "number_of_episodes": tv.get("number_of_episodes") or 0,
            "in_production": bool(tv.get("in_production")),
            "episode_run_time": tv.get("episode_run_time") or [],
            "network_names": [n.get("name") for n in (tv.get("networks") or []) if n.get("name")],
        },
    )

    # seasons + episodes (with episode-level links)
    for s in tv.get("seasons") or []:
        snum = s.get("season_number")

        # Skip TMDB "Season 0" (specials) to keep URLs 1-based
        if snum is None or (SKIP_SPECIALS and snum == 0):
            continue

        season_obj, _ = Season.objects.update_or_create(
            tv=title, season_number=snum,
            defaults={
                "tmdb_id": s.get("id"),
                "name": s.get("name") or "",
                "overview": s.get("overview") or "",
                "air_date": s.get("air_date") or "",
                "poster": s.get("poster_path") or "",
            }
        )

        sfull = tmdb_season_full(tv_id, snum)
        episodes = sfull.get("episodes") or []
        if verbose:
            print(f"   [SEASON] tv={tv_id} season={snum} episodes={len(episodes)}")

        for e in episodes:
            enum = e.get("episode_number", 0)

            # IMPORTANT: this is extremely slow if enabled (1 request per episode).
            ep_imdb = None
            if with_episode_imdb:
                try:
                    ext = tmdb_episode_external_ids(tv_id, snum, enum)
                except Exception:
                    ext = {}
                ep_imdb = ext.get("imdb_id") or None

            links = episode_links(tv_id, snum, enum)

            Episode.objects.update_or_create(
                season=season_obj,
                episode_number=enum,
                defaults={
                    "tmdb_id": e.get("id"),
                    "name": e.get("name") or "",
                    "overview": e.get("overview") or "",
                    "air_date": e.get("air_date") or "",
                    "still_path": e.get("still_path") or "",
                    "vote_average": e.get("vote_average"),
                    "vote_count": e.get("vote_count"),
                    "runtime": e.get("runtime"),
                    "imdb_code": ep_imdb,
                    "video_url": links["video_url"],
                    "episode_link2": links["episode_link2"],
                    "episode_link3": links["episode_link3"],
                }
            )

    return "CREATED" if created_title else "UPDATED"

# ========= ID sources =========

def load_ids_from_file(path: str) -> List[str]:
    ids: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            val = line.strip()
            if val and not val.startswith("#"):
                ids.append(val)
    return ids

# ========= CLI =========

def main():
    ap = argparse.ArgumentParser(description="Seed Titles: movies (IMDb/TMDB) and tv (TMDB/IMDb).")
    ap.add_argument("--mode", choices=["movies", "tv"], required=True, help="What to seed")
    ap.add_argument("--ids-file", required=True, help="Path to .txt file with ids (one per line)")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite non-empty fields")
    ap.add_argument(
        "--skip-existing-tmdb",
        action="store_true",
        help="Skip items whose tmdb_id already exists in DB (avoid UPDATED + save API calls)"
    )
    ap.add_argument(
        "--with-episode-imdb",
        action="store_true",
        help="(TV only, SLOW) Fetch episode external_ids to fill episode imdb_code"
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress logs (FETCH/SEASON) so it never looks frozen"
    )
    args = ap.parse_args()

    if args.mode == "movies":
        ids = load_ids_from_file(args.ids_file)
        created = updated = skipped = 0

        for raw in ids:
            try:
                raw = raw.strip()
                if not raw:
                    continue

                # Case 1: TMDB movie id (numeric)
                if raw.isdigit():
                    tmdb_id = int(raw)

                    if args.skip_existing_tmdb and movie_exists_tmdb(tmdb_id):
                        print(f"[SKIP] movie tmdb={tmdb_id} already in DB")
                        skipped += 1
                        continue

                    if args.verbose:
                        print(f"[FETCH] movie tmdb={tmdb_id} ...")

                    tmdb = tmdb_movie_full(tmdb_id)
                    imdb_code = tmdb.get("imdb_id") or None

                    res = upsert_movie_from_tmdb(imdb_code=imdb_code, tmdb=tmdb, overwrite=args.overwrite)

                    if res == "CREATED":
                        created += 1
                    elif res == "UPDATED":
                        updated += 1
                    else:
                        skipped += 1

                    print(f"[{res}] {tmdb.get('title')} ({tmdb.get('release_date')}) tmdb={tmdb_id} imdb={imdb_code}")
                    continue

                # Case 2: IMDb id (tt...)
                imdb_code = raw
                mid, _ = tmdb_find_by_imdb(imdb_code)
                if not mid:
                    print(f"[SKIP] {imdb_code} no TMDB movie match")
                    skipped += 1
                    continue

                if args.skip_existing_tmdb and movie_exists_tmdb(mid):
                    print(f"[SKIP] {imdb_code} -> tmdb={mid} already in DB")
                    skipped += 1
                    continue

                if args.verbose:
                    print(f"[FETCH] movie imdb={imdb_code} -> tmdb={mid} ...")

                tmdb = tmdb_movie_full(mid)

                tmdb_imdb = tmdb.get("imdb_id") or None
                if not imdb_code.startswith("tt") and tmdb_imdb:
                    imdb_code = tmdb_imdb

                res = upsert_movie_from_tmdb(imdb_code=imdb_code, tmdb=tmdb, overwrite=args.overwrite)

                if res == "CREATED":
                    created += 1
                elif res == "UPDATED":
                    updated += 1
                else:
                    skipped += 1

                print(f"[{res}] {tmdb.get('title')} ({tmdb.get('release_date')}) imdb={imdb_code} tmdb={mid}")

            except Exception as e:
                print(f"[WARN] {raw} -> {e}")
                skipped += 1

        print(f"\n[DONE movies] created={created} updated={updated} skipped={skipped}")

    if args.mode == "tv":
        raw_ids = load_ids_from_file(args.ids_file)
        created = updated = skipped = 0

        for raw in raw_ids:
            try:
                raw = raw.strip()
                if not raw:
                    continue

                if raw.startswith("tt"):           # IMDb series id
                    _, tid = tmdb_find_by_imdb(raw)
                    tv_tmdb_id = tid
                else:                               # TMDB tv id
                    tv_tmdb_id = int(raw)

                if not tv_tmdb_id:
                    print(f"[SKIP] {raw} no TMDB tv match")
                    skipped += 1
                    continue

                if args.skip_existing_tmdb and tv_exists_tmdb(tv_tmdb_id):
                    print(f"[SKIP] tv id={tv_tmdb_id} already in DB")
                    skipped += 1
                    continue

                if args.verbose:
                    print(f"[FETCH] tv id={tv_tmdb_id} ...")

                tv = tmdb_tv_full(tv_tmdb_id)
                res = upsert_tv_from_tmdb(tv, overwrite=args.overwrite, with_episode_imdb=args.with_episode_imdb, verbose=args.verbose)

                if res == "CREATED":
                    created += 1
                elif res == "UPDATED":
                    updated += 1
                else:
                    skipped += 1

                print(f"[{res}] {tv.get('name')} (first_air_date={tv.get('first_air_date')}) id={tv_tmdb_id}")

            except Exception as e:
                print(f"[WARN] {raw} -> {e}")
                skipped += 1

        print(f"\n[DONE tv] created={created} updated={updated} skipped={skipped}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

# Movies (IDs IMDb tt... OU TMDB numériques, 1 par ligne)

#python seed_titles_full.py --mode movies --ids-file movie_ids.txt --skip-existing-tmdb --verbose


#TV (IDs TMDB numériques OU IMDb tt..., 1 par ligne)

#python seed_titles_full.py --mode tv --ids-file tv_ids.txt --skip-existing-tmdb --verbose


#TV (si tu veux vraiment remplir imdb_code des épisodes — très lent)

#python seed_titles_full.py --mode tv --ids-file tv_ids.txt --with-episode-imdb --verbose        
