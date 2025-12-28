import time
import requests
from datetime import date

API_KEY = "f6988ac086c88bbfe779ab0ed2eed215"
BASE_URL = "https://api.themoviedb.org/3"
SLEEP = 0.08

def fetch_ids(path, params=None, hard_page_cap=500):
    if params is None:
        params = {}
    params = dict(params)
    params["api_key"] = API_KEY
    params.setdefault("language", "en-US")

    out = []
    page = 1

    while page <= hard_page_cap:
        params["page"] = page

        # --- retry / resilience ---
        tries = 0
        data = None
        while True:
            tries += 1
            try:
                r = requests.get(f"{BASE_URL}{path}", params=params, timeout=25)

                # TMDB hiccups / rate limit
                if r.status_code in (429, 500, 502, 503, 504):
                    if tries <= 6:
                        wait = min(30, 2 ** (tries - 1))  # 1,2,4,8,16,30
                        print(f"[WARN] HTTP {r.status_code} {path} page={page} retry={tries}/6 sleep={wait}s")
                        time.sleep(wait)
                        continue
                    else:
                        print(f"[SKIP] HTTP {r.status_code} {path} page={page} (giving up)")
                        data = None
                else:
                    r.raise_for_status()
                    data = r.json()

                break

            except requests.RequestException as e:
                if tries <= 6:
                    wait = min(30, 2 ** (tries - 1))
                    print(f"[WARN] {e} {path} page={page} retry={tries}/6 sleep={wait}s")
                    time.sleep(wait)
                    continue
                print(f"[SKIP] network error {path} page={page}: {e}")
                data = None
                break

        if not data:
            # skip this page and keep going
            page += 1
            continue

        results = data.get("results", [])
        if not results:
            break

        for m in results:
            mid = m.get("id")
            if mid:
                out.append(int(mid))

        total_pages = int(data.get("total_pages") or 0)
        if total_pages and page >= total_pages:
            break

        page += 1
        time.sleep(SLEEP)

    return out

def discover_ids(sort_by, release_gte, release_lte,
                vote_count_gte=None, vote_average_gte=None,
                hard_page_cap=500):
    params = {
        "sort_by": sort_by,
        "include_adult": "false",
        "include_video": "false",
        "release_date.gte": release_gte,
        "release_date.lte": release_lte,
    }
    if vote_count_gte is not None:
        params["vote_count.gte"] = vote_count_gte
    if vote_average_gte is not None:
        params["vote_average.gte"] = vote_average_gte

    return fetch_ids("/discover/movie", params=params, hard_page_cap=hard_page_cap)

def windows_years(start_year, end_year, step_years):
    y = start_year
    while y <= end_year:
        y1 = min(end_year, y + step_years - 1)
        yield (y, y1)
        y = y1 + 1

def load_ids_file(path):
    ids = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.isdigit():
                ids.append(int(s))
    return ids

def add_unique(final, seen, ids, target):
    for mid in ids:
        if mid not in seen:
            seen.add(mid)
            final.append(mid)
            if len(final) >= target:
                return True
    return False

def build(base_ids_file, target=20000, last_n_years=40):
    today_year = date.today().year
    start_year = today_year - last_n_years

    # 1) Base top list (tes ~4000/4600)
    base = load_ids_file(base_ids_file)
    final, seen = [], set()
    add_unique(final, seen, base, target)
    print(f"base loaded: {len(final)}")

    # 2) “Gros connus” récents (franchises)
    for path, cap in [
        ("/movie/popular", 200),
        ("/trending/movie/week", 20),
        ("/movie/now_playing", 50),
        ("/movie/upcoming", 50),
    ]:
        ids = fetch_ids(path, params={}, hard_page_cap=cap)
        if add_unique(final, seen, ids, target):
            return final
        print(f"{path}: total={len(final)}")

    # 3) Blockbusters box-office (revenue desc) sur 40 ans
    # Fenêtres de 2 ans
    for y0, y1 in windows_years(start_year, today_year, 2):
        ids = discover_ids(
            sort_by="revenue.desc",
            release_gte=f"{y0}-01-01",
            release_lte=f"{y1}-12-31",
            vote_count_gte=80,
            hard_page_cap=200
        )
        if add_unique(final, seen, ids, target):
            return final
        print(f"revenue {y0}-{y1}: total={len(final)}")

    # 4) Très connus même si note moyenne (popularity desc) sur 40 ans
    # Fenêtres de 3 ans
    for y0, y1 in windows_years(start_year, today_year, 3):
        ids = discover_ids(
            sort_by="popularity.desc",
            release_gte=f"{y0}-01-01",
            release_lte=f"{y1}-12-31",
            vote_count_gte=50,
            vote_average_gte=5.0,
            hard_page_cap=300
        )
        if add_unique(final, seen, ids, target):
            return final
        print(f"popular {y0}-{y1}: total={len(final)}")

    # 5) Dernier filet “consensus mainstream” (vote_count desc)
    for y0, y1 in windows_years(start_year, today_year, 5):
        ids = discover_ids(
            sort_by="vote_count.desc",
            release_gte=f"{y0}-01-01",
            release_lte=f"{y1}-12-31",
            vote_count_gte=200,
            vote_average_gte=5.5,
            hard_page_cap=300
        )
        if add_unique(final, seen, ids, target):
            return final
        print(f"votes {y0}-{y1}: total={len(final)}")

    return final

if __name__ == "__main__":
    # ⚠️ Mets ici le fichier de base (tes 4616 IDs “bons”)
    BASE_FILE = "tmdb_top_4616_movie_ids.txt"

    ids = build(BASE_FILE, target=20000, last_n_years=40)

    out_file = "tmdb_top_plus_blockbusters40y_20000.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        for mid in ids[:20000]:
            f.write(str(mid) + "\n")

    print(f"✅ wrote {min(len(ids), 20000)} ids to {out_file}")
