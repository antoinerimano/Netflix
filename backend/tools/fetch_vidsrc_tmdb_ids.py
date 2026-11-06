# fetch_vidsrc_tmdb_ids.py
import argparse
import sys
import time
from typing import List, Set, Optional

import requests

BASE = "https://vidsrc-embed.ru"
SLEEP_SECONDS = 0.12  # petit délai pour éviter de se faire throttler


def fetch_page(kind: str, page: int, timeout: int = 60, retries: int = 6) -> List[dict]:
    """
    kind: 'movies' ou 'tvshows'
    """
    url = f"{BASE}/{kind}/latest/page-{page}.json"
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            data = r.json()

            results = data.get("result")
            return results if isinstance(results, list) else []

        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = e
            wait = min(2 ** attempt, 30)  # 2s, 4s, 8s... max 30s
            print(
                f"[WARN] page={page} attempt={attempt}/{retries} timeout/conn -> retry in {wait}s",
                file=sys.stderr,
            )
            time.sleep(wait)

        except requests.HTTPError as e:
            # si 404 ou autre HTTP error, on stop net (souvent fin des pages)
            raise e

    # après retries
    raise last_err


def extract_tmdb_ids(items: List[dict]) -> List[str]:
    out: List[str] = []
    for it in items:
        tmdb_id = it.get("tmdb_id")
        if tmdb_id is None:
            continue
        s = str(tmdb_id).strip()
        if s:
            out.append(s)
    return out


def run(kind: str, start_page: int, end_page: Optional[int], out_file: str, skip_errors: bool) -> None:
    collected: Set[str] = set()
    page = start_page

    while True:
        if end_page is not None and page > end_page:
            break

        try:
            items = fetch_page(kind, page)
        except requests.HTTPError as e:
            print(f"[STOP] HTTP error on page {page}: {e}", file=sys.stderr)
            break
        except Exception as e:
            if skip_errors:
                print(f"[SKIP] Error on page {page}: {e}", file=sys.stderr)
                page += 1
                continue
            print(f"[STOP] Error on page {page}: {e}", file=sys.stderr)
            break

        if not items:
            print(f"[STOP] No results on page {page}.", file=sys.stderr)
            break

        ids = extract_tmdb_ids(items)
        before = len(collected)
        for x in ids:
            collected.add(x)
        added = len(collected) - before

        print(
            f"[OK] page={page} items={len(items)} ids_found={len(ids)} new_unique={added}",
            file=sys.stderr,
        )

        page += 1
        time.sleep(SLEEP_SECONDS)

    # tri propre (numérique si possible)
    def sort_key(v: str):
        try:
            return (0, int(v))
        except:
            return (1, v)

    ordered = sorted(collected, key=sort_key)

    with open(out_file, "w", encoding="utf-8") as f:
        for tmdb_id in ordered:
            f.write(tmdb_id + "\n")

    print(f"[DONE] Wrote {len(ordered)} unique tmdb_id to: {out_file}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch tmdb_id list from vidsrc-embed latest pages.")
    parser.add_argument("--type", choices=["movies", "tvshows"], required=True)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=None, help="If omitted, stops on empty results/HTTP error.")
    parser.add_argument("--out", default="tmdb_ids.txt")
    parser.add_argument("--skip-errors", action="store_true", help="Skip bad pages instead of stopping.")
    args = parser.parse_args()

    run(
        kind=args.type,
        start_page=args.start,
        end_page=args.end,
        out_file=args.out,
        skip_errors=args.skip_errors,
    )
