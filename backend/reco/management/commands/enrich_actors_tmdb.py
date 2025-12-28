import os
import time
import json
import random
import requests
import traceback
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db import models
from users.models import Actor

TMDB_KEY = "f6988ac086c88bbfe779ab0ed2eed215"
BASE = "https://api.themoviedb.org/3"


def norm(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Command(BaseCommand):
    help = "Enrich Actor rows with tmdb_id + profile_path via TMDB with robust logs/retries + persistent file cache (jsonl)."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=0.12, help="Base sleep between TMDB calls")
        parser.add_argument("--log-every", type=int, default=200, help="Console log every N processed actors")
        parser.add_argument("--db-refresh-every", type=int, default=500, help="close_old_connections every N actors")
        parser.add_argument("--max-retries", type=int, default=5, help="Max retries for transient failures")
        parser.add_argument("--batch", type=int, default=0, help="0 = no limit (process all matching rows)")
        parser.add_argument(
            "--only-missing-photo",
            action="store_true",
            help="Process actors where profile_path is null/empty. Else: tmdb_id is null.",
        )
        parser.add_argument("--logfile", type=str, default="tmdb_enrich.log", help="Write detailed logs to this file")
        parser.add_argument("--no-filelog", action="store_true", help="Disable file logging")

        # Persistent cache (file-based)
        parser.add_argument("--cache-file", type=str, default="tmdb_actor_cache.txt", help="Persistent cache file (jsonl).")
        parser.add_argument(
            "--cache-days",
            type=int,
            default=365,
            help="How long to trust negative cache (no_photo/not_found) before retrying.",
        )
        parser.add_argument(
            "--force-cache-refresh",
            action="store_true",
            help="Ignore cache and call TMDB anyway.",
        )

    # ---------- Logging helpers ----------
    def filelog(self, fp, obj):
        fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fp.flush()

    # ---------- Persistent cache helpers ----------
    def load_persistent_cache(self, path: str):
        """
        JSONL file: one json per line.
        Returns dict[name_norm] = {status, tmdb_id, profile_path, ts, ...}
        Last write wins (latest line for a given key).
        """
        cache = {}
        if not path or not os.path.exists(path):
            return cache

        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    key = obj.get("key")
                    if not key:
                        continue
                    cache[key] = obj
                except Exception:
                    continue
        return cache

    def append_cache_line(self, fp, obj: dict):
        fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fp.flush()

    def cache_allows_skip(self, entry: dict, cache_days: int):
        """
        Skip if entry is negative-cached recently.
        """
        if not entry:
            return False
        status = entry.get("status")
        if status not in ("no_photo", "not_found"):
            return False

        ts = entry.get("ts")
        if not ts:
            return True  # no timestamp => assume skip
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return True

        return (datetime.now() - dt) < timedelta(days=cache_days)

    # ---------- TMDB call ----------
    def tmdb_search_person(self, name: str, max_retries: int, base_sleep: float, fp=None):
        """
        Returns (tmdb_id, profile_path, status_string)
        status_string in: ok, no_photo, not_found, http_error_XXX, exception, retries_exhausted
        Network errors are retried; 429 gets backoff; 5xx gets retries.
        """
        url = f"{BASE}/search/person"
        params = {"api_key": TMDB_KEY, "query": name}

        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(url, params=params, timeout=15)

                # 429: rate limit -> backoff
                if r.status_code == 429:
                    backoff = min(8.0, (1.0 + attempt) * 0.8) + random.random() * 0.4
                    if fp:
                        self.filelog(fp, {
                            "ts": now_str(), "event": "rate_limit", "name": name,
                            "attempt": attempt, "backoff_s": round(backoff, 2)
                        })
                    time.sleep(backoff)
                    continue

                # other http errors
                if r.status_code >= 400:
                    if fp:
                        self.filelog(fp, {
                            "ts": now_str(), "event": "http_error", "name": name,
                            "status_code": r.status_code, "body": (r.text[:300] if r.text else "")
                        })
                    # retry 5xx
                    if 500 <= r.status_code < 600 and attempt < max_retries:
                        time.sleep(min(5.0, base_sleep * (2 ** attempt)))
                        continue
                    return (None, None, f"http_error_{r.status_code}")

                data = r.json()
                results = data.get("results") or []
                if not results:
                    return (None, None, "not_found")

                best = results[0]
                tmdb_id = best.get("id")
                profile_path = best.get("profile_path")

                # ok but no photo
                if tmdb_id and not profile_path:
                    return (tmdb_id, None, "no_photo")

                return (tmdb_id, profile_path, "ok")

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                backoff = min(8.0, base_sleep * (2 ** attempt)) + random.random() * 0.4
                if fp:
                    self.filelog(fp, {
                        "ts": now_str(), "event": "network_error", "name": name,
                        "attempt": attempt, "err": repr(e), "backoff_s": round(backoff, 2)
                    })
                time.sleep(backoff)
                continue
            except Exception as e:
                if fp:
                    self.filelog(fp, {
                        "ts": now_str(), "event": "exception", "name": name,
                        "err": repr(e), "trace": traceback.format_exc()[:2000]
                    })
                return (None, None, "exception")

        return (None, None, "retries_exhausted")

    # ---------- Main ----------
    def handle(self, *args, **opts):
        if not TMDB_KEY:
            self.stdout.write(self.style.ERROR("TMDB_KEY missing"))
            return

        sleep = float(opts["sleep"])
        log_every = int(opts["log_every"])
        db_refresh_every = int(opts["db_refresh_every"])
        max_retries = int(opts["max_retries"])
        batch = int(opts["batch"])
        only_missing_photo = bool(opts["only_missing_photo"])
        logfile = opts["logfile"]
        no_filelog = bool(opts["no_filelog"])

        cache_file = opts["cache_file"]
        cache_days = int(opts["cache_days"])
        force_cache_refresh = bool(opts["force_cache_refresh"])

        # Queryset
        qs = Actor.objects.exclude(name="").order_by("id")
        if only_missing_photo:
            qs = qs.filter(models.Q(profile_path__isnull=True) | models.Q(profile_path=""))
        else:
            qs = qs.filter(tmdb_id__isnull=True)

        total = qs.count()
        if batch and batch > 0:
            qs = qs[:batch]
            total = min(total, batch)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"enrich_actors_tmdb start: total={total} sleep={sleep}s retries={max_retries} "
            f"only_missing_photo={only_missing_photo} cache_file={cache_file} cache_days={cache_days} "
            f"force_cache_refresh={force_cache_refresh}"
        ))

        # File log (detailed)
        fp = None
        if not no_filelog:
            fp = open(logfile, "a", encoding="utf-8")
            self.filelog(fp, {"ts": now_str(), "event": "start", "total": total})

        # Persistent cache
        p_cache = self.load_persistent_cache(cache_file)
        cache_fp = open(cache_file, "a", encoding="utf-8")

        processed = ok = miss = err = 0
        cache_hits = 0
        cache_skips = 0
        api_calls = 0
        t0 = time.time()

        for actor in qs:
            processed += 1

            if processed % db_refresh_every == 0:
                close_old_connections()

            key = actor.name_norm or norm(actor.name)

            tmdb_id = None
            profile_path = None
            status = "unknown"

            # 1) persistent cache lookup
            entry = p_cache.get(key)

            if not force_cache_refresh and entry:
                if self.cache_allows_skip(entry, cache_days):
                    # negative-cached recently => skip API call
                    cache_skips += 1
                    cache_hits += 1
                    status = entry.get("status", "cached")
                    tmdb_id = entry.get("tmdb_id")
                    profile_path = entry.get("profile_path")
                elif entry.get("status") == "ok":
                    # reuse ok cached result (no API call)
                    cache_hits += 1
                    status = "ok"
                    tmdb_id = entry.get("tmdb_id")
                    profile_path = entry.get("profile_path")

            # 2) if not satisfied by cache => call TMDB
            if status == "unknown":
                api_calls += 1
                tmdb_id, profile_path, status = self.tmdb_search_person(
                    actor.name, max_retries=max_retries, base_sleep=sleep, fp=fp
                )

                # write/update cache for this key
                cache_obj = {
                    "ts": now_str(),
                    "key": key,
                    "name": actor.name,
                    "status": status,
                    "tmdb_id": tmdb_id,
                    "profile_path": profile_path,
                }
                p_cache[key] = cache_obj
                self.append_cache_line(cache_fp, cache_obj)

            # 3) update DB if found/changed (no schema change)
            try:
                changed = False

                if tmdb_id and actor.tmdb_id != tmdb_id:
                    actor.tmdb_id = tmdb_id
                    changed = True

                # only set profile_path if we actually have one
                if profile_path and actor.profile_path != profile_path:
                    actor.profile_path = profile_path
                    changed = True

                if changed:
                    actor.save(update_fields=["tmdb_id", "profile_path"])
                    ok += 1
                    if fp:
                        self.filelog(fp, {
                            "ts": now_str(), "event": "updated",
                            "actor_id": actor.id, "name": actor.name,
                            "tmdb_id": tmdb_id, "profile_path": profile_path,
                            "status": status, "cache_hit": (status != "unknown" and api_calls == 0)
                        })
                else:
                    miss += 1
                    if fp and status != "ok":
                        self.filelog(fp, {
                            "ts": now_str(), "event": "miss",
                            "actor_id": actor.id, "name": actor.name,
                            "status": status
                        })

            except Exception as e:
                err += 1
                self.stdout.write(self.style.WARNING(
                    f"[DB ERROR] actor_id={actor.id} name={actor.name} err={repr(e)}"
                ))
                if fp:
                    self.filelog(fp, {
                        "ts": now_str(), "event": "db_error",
                        "actor_id": actor.id, "name": actor.name,
                        "err": repr(e), "trace": traceback.format_exc()[:2000]
                    })

            # periodic console log
            if processed % log_every == 0 or processed == total:
                elapsed = time.time() - t0
                rate = processed / elapsed if elapsed > 0 else 0
                remaining = total - processed
                eta = (remaining / rate) if rate > 0 else 0
                self.stdout.write(
                    f"[{processed}/{total}] ok={ok} miss={miss} err={err} "
                    f"cache_hits={cache_hits} cache_skips={cache_skips} api_calls={api_calls} "
                    f"rate={rate:.2f}/s ETA={eta/60:.1f}m"
                )

            time.sleep(sleep)

        elapsed = time.time() - t0
        self.stdout.write(self.style.SUCCESS(
            f"enrich_actors_tmdb DONE: processed={processed} ok={ok} miss={miss} err={err} "
            f"cache_hits={cache_hits} cache_skips={cache_skips} api_calls={api_calls} elapsed={elapsed:.1f}s"
        ))

        if fp:
            self.filelog(fp, {
                "ts": now_str(), "event": "done", "processed": processed,
                "ok": ok, "miss": miss, "err": err,
                "cache_hits": cache_hits, "cache_skips": cache_skips, "api_calls": api_calls,
                "elapsed_s": round(elapsed, 2)
            })
            fp.close()

        cache_fp.close()
