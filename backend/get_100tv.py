import requests
import ast
import time
import math

API_KEY = "f6988ac086c88bbfe779ab0ed2eed215"
BASE_URL = "https://api.themoviedb.org/3"
SLEEP = 0.08

TARGET = 5000
SKIP_FILE = "a.txt"
OUT_FILE = "b.txt"

# --- Utils ---
def load_skip_ids(path=SKIP_FILE):
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            if not raw:
                return set()
            data = ast.literal_eval(raw)  # ex: "[1,2,3]" ou "{1,2,3}"
            if isinstance(data, (list, tuple, set)):
                return set(int(x) for x in data)
            return set()
    except FileNotFoundError:
        return set()
    except Exception:
        # si mal formatté, on ne bloque pas le script
        return set()

def fetch_pages(path, params=None, hard_page_cap=500):
    if params is None:
        params = {}
    params = dict(params)
    params["api_key"] = API_KEY
    params.setdefault("language", "en-US")

    page = 1
    while page <= hard_page_cap:
        params["page"] = page
        r = requests.get(f"{BASE_URL}{path}", params=params, timeout=25)
        r.raise_for_status()
        data = r.json()

        results = data.get("results", [])
        if not results:
            break

        yield from results

        total_pages = int(data.get("total_pages") or 0)
        if page >= total_pages:
            break

        page += 1
        time.sleep(SLEEP)

def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def compute_score(item, source_weight=1.0):
    """
    Score "connu + recherché + bon" (heuristique).
    item contient souvent: popularity, vote_average, vote_count
    """
    pop = float(item.get("popularity") or 0.0)
    va = float(item.get("vote_average") or 0.0)
    vc = float(item.get("vote_count") or 0.0)

    # note normalisée (0..1) et plafonnée
    rating = clamp(va / 10.0, 0.0, 1.0)

    # confiance via nb de votes (croissance lente)
    votes_conf = math.log1p(vc)  # ~0..(≈12-14)

    # popularité en log pour éviter que ça écrase tout
    pop_log = math.log1p(pop)    # ~0..(≈10-12)

    # Mix: favorise connu (pop), puis "bon et crédible" (rating * votes)
    score = (
    1.6 * pop_log +              # ↓ from 2.2
    2.0 * (rating * votes_conf) + # ↑ reward credibility
    0.8 * votes_conf              # ↑ legacy trust
    )

    return score * float(source_weight)

def build_5000_tv(skip_ids, target=TARGET):
    # Map id -> {"score": float, "item": dict}
    best = {}

    # Sources: “connues/recherchées” + “meilleures” + “tendance” + “complément”
    sources = [
        # Modern visibility
        ("/tv/popular", {}, 1.35),
        ("/tv/top_rated", {}, 1.10),
        ("/trending/tv/week", {}, 1.25),
        ("/tv/on_the_air", {}, 1.05),

        # Modern discover
        ("/discover/tv", {"sort_by": "popularity.desc", "vote_count.gte": 50}, 1.20),
        ("/discover/tv", {"sort_by": "vote_average.desc", "vote_count.gte": 200}, 1.00),

        # ⭐ CLASSICS / LEGACY TV (CRITICAL)
        ("/discover/tv", {
            "sort_by": "vote_count.desc",
            "vote_count.gte": 1000,
            "first_air_date.lte": "2015-12-31"
        }, 1.60),
    ]


    # On ratisse large pour être sûr d’avoir 5000 après skip + dédup
    # (si ton a.txt est énorme, augmente hard_page_cap)
    HARD_CAP = 500

    for path, params, w in sources:
        for item in fetch_pages(path, params=params, hard_page_cap=HARD_CAP):
            sid = item.get("id")
            if not sid:
                continue
            sid = int(sid)

            if sid in skip_ids:
                continue

            s = compute_score(item, source_weight=w)
            prev = best.get(sid)
            if prev is None or s > prev["score"]:
                best[sid] = {"score": s, "item": item}

    # Trier par score décroissant
    ranked = sorted(best.items(), key=lambda kv: kv[1]["score"], reverse=True)
    ids = [sid for sid, _ in ranked[:target]]

    return ids, len(best)

if __name__ == "__main__":
    skip_ids = load_skip_ids(SKIP_FILE)
    ids, pool_size = build_5000_tv(skip_ids, target=TARGET)

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        for sid in ids:
            f.write(f"{sid}\n")


    print(f"✅ Skip (a.txt): {len(skip_ids)} ids")
    print(f"✅ Pool unique candidates: {pool_size}")
    print(f"✅ Saved: {len(ids)} ids -> {OUT_FILE}")

    if len(ids) < TARGET:
        print("⚠️ Pas assez d'IDs après skip. Solutions:")
        print("   - diminue le filtrage (vote_count.gte)")
        print("   - augmente HARD_CAP (pages)")
        print("   - ou ton a.txt contient déjà trop des séries populaires")
