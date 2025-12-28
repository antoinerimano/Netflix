#!/usr/bin/env python3
"""
make_trailer_clips.py  (disk-safe temp usage + per-title cleanup + proxy rotation)

- Downloads trailers via yt-dlp, cuts a 20s mid-clip with ffmpeg,
  uploads to Bunny Storage at: /{BUNNY_STORAGE_ZONE}/trailers/{tmdb_id}.mp4
  and updates Title.trailer_clip_url to: {BUNNY_CDN_BASE}/trailers/{tmdb_id}.mp4

- Minimizes disk usage:
  * Uses --no-cache-dir for yt-dlp.
  * Cleans each title's temp dir immediately on success OR failure.
  * Supports moving temp base to another drive via TRAILER_TMP_BASE (e.g., D:\trailer_temp).

- Proxy rotation:
  * Configure proxies via PROXY_LIST (CSV), PROXY_JSON (JSON array), or PROXY_FILE (one per line).
  * Lines like host:port:user:pass are URL-encoded to http://user:pass@host:port
  * Rotate proxies per-title; retry strategies & simple backoff.
"""

import os
import sys
import json
import math
import time
import tempfile
import shutil
import subprocess
from pathlib import Path
from itertools import cycle, islice
from urllib.parse import quote
import random

import django
from django.db import transaction
from django.db.models import Q

# ---------- CONFIG ----------
DJANGO_SETTINGS_MODULE = os.getenv("DJANGO_SETTINGS_MODULE", "streaming_backend.settings")
TITLE_MODEL_IMPORT     = os.getenv("TITLE_MODEL_IMPORT", "users.models")
TITLE_MODEL_NAME       = os.getenv("TITLE_MODEL_NAME", "Title")

# Bunny Storage
BUNNY_STORAGE_ZONE = os.getenv("BUNNY_STORAGE_ZONE", "my-storage-zone-zuvo")
BUNNY_API_KEY      = os.getenv("BUNNY_API_KEY", "b88705bf-39e4-4443-9b3ab0219d6e-922c-4f71")  # set in env
BUNNY_STORAGE_HOST = os.getenv("BUNNY_STORAGE_HOST", "ny.storage.bunnycdn.com")
BUNNY_CDN_BASE     = os.getenv("BUNNY_CDN_BASE", "https://zuvo-movies-cdn.b-cdn.net")

# now just trailers (no clips folder)
BUNNY_STORAGE_SUBDIR = os.getenv("BUNNY_STORAGE_SUBDIR", "trailers")

# Processing behavior
ONLY_MISSING = os.getenv("ONLY_MISSING", "1") == "1"  # retained for backwards compat
DRY_RUN      = os.getenv("DRY_RUN", "0") == "1"
LIMIT        = int(os.getenv("LIMIT", "0"))

# ffmpeg settings
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")
CLIP_DURATION = int(os.getenv("CLIP_DURATION", "20"))
VIDEO_CRF = os.getenv("VIDEO_CRF", "23")
VIDEO_PRESET = os.getenv("VIDEO_PRESET", "veryfast")
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE", "128k")

# Proxy settings
YTDLP_USE_PROXY = os.getenv("YTDLP_USE_PROXY", "0") == "1"
BUNNY_USE_PROXY = os.getenv("BUNNY_USE_PROXY", "0") == "1"
PROXY_LIST = os.getenv("PROXY_LIST", "")
PROXY_JSON = os.getenv("PROXY_JSON", "")
PROXY_FILE = os.getenv("PROXY_FILE", "")

# Optional: limit how many consecutive proxy failures before giving up this title
MAX_PROXY_TRIES_PER_TITLE = int(os.getenv("MAX_PROXY_TRIES_PER_TITLE", "5"))

# Backoff
INITIAL_BACKOFF = float(os.getenv("PROXY_BACKOFF_INITIAL", "0.6"))
BACKOFF_FACTOR  = float(os.getenv("PROXY_BACKOFF_FACTOR", "1.7"))
BACKOFF_MAX     = float(os.getenv("PROXY_BACKOFF_MAX", "6.0"))

# Custom temp base to avoid filling C:\
TRAILER_TMP_BASE = os.getenv("TRAILER_TMP_BASE", "").strip()  # e.g. "D:/trailer_temp" or "E:\\trailer_temp"

# ---------- Django bootstrap ----------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", DJANGO_SETTINGS_MODULE)
django.setup()

_title_mod = __import__(TITLE_MODEL_IMPORT, fromlist=[TITLE_MODEL_NAME])
Title = getattr(_title_mod, TITLE_MODEL_NAME)

# ---------- Proxy rotation ----------
def _normalize_proxy(p: str) -> str:
    p = (p or "").strip()
    if not p:
        return ""
    if "://" in p:
        return p
    parts = p.split(":")
    if len(parts) == 4:
        host, port, user, pw = parts
        return f"http://{quote(user, safe='')}:{quote(pw, safe='')}@{host}:{port}"
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    return "http://" + p

def _load_proxies() -> list[str]:
    proxies: list[str] = []
    if PROXY_LIST.strip():
        for item in PROXY_LIST.split(","):
            pr = _normalize_proxy(item)
            if pr:
                proxies.append(pr)
    if not proxies and PROXY_JSON.strip():
        try:
            arr = json.loads(PROXY_JSON)
            if isinstance(arr, list):
                for item in arr:
                    pr = _normalize_proxy(str(item))
                    if pr:
                        proxies.append(pr)
        except Exception:
            pass
    if not proxies and PROXY_FILE.strip():
        p = Path(PROXY_FILE)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                pr = _normalize_proxy(line)
                if pr:
                    proxies.append(pr)
    seen = set()
    uniq = []
    for pr in proxies:
        if pr not in seen:
            seen.add(pr)
            uniq.append(pr)
    return uniq

_PROXY_LIST = _load_proxies()
_PROXY_CYCLE = cycle(_proxy for _proxy in _PROXY_LIST) if _PROXY_LIST else None

def get_next_proxy() -> str | None:
    if not _PROXY_CYCLE:
        return None
    return next(_PROXY_CYCLE)

def backoff_sleep(attempt_idx: int):
    delay = min(INITIAL_BACKOFF * (BACKOFF_FACTOR ** attempt_idx), BACKOFF_MAX)
    time.sleep(delay)

# ---------- Shell helpers ----------
def sh(cmd, check=True):
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed (rc={proc.returncode}):\n"
            f"{' '.join(map(str, cmd))}\n\nSTDERR:\n{proc.stderr.strip()}\n\nSTDOUT:\n{proc.stdout.strip()}"
        )
    return proc.stdout, proc.stderr

# ---------- Media helpers ----------
def ffprobe_duration(path: Path) -> float:
    cmd = [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)]
    out, _ = sh(cmd)
    data = json.loads(out or "{}")
    dur = float(data.get("format", {}).get("duration", 0.0) or 0.0)
    return max(dur, 0.0)

def cut_mid_clip(src: Path, dst: Path, clip_len: int = CLIP_DURATION):
    duration = ffprobe_duration(src)
    if duration <= 0:
        raise RuntimeError("Unable to determine input duration")
    start = max(0.0, (duration * 0.5) - (clip_len / 2.0))
    if duration < clip_len:
        start = 0.0
        clip_len = max(1, int(math.floor(duration)))
    cmd = [
        FFMPEG,
        "-y",
        "-ss", f"{start:.3f}",
        "-i", str(src),
        "-t", str(clip_len),
        "-c:v", "libx264",
        "-preset", VIDEO_PRESET,
        "-crf", VIDEO_CRF,
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(dst),
    ]
    sh(cmd)

# ---------- yt-dlp ----------
def _ytdlp_cmd_base(outtmpl: str, proxy: str | None) -> list[str]:
    base = [
        sys.executable, "-m", "yt_dlp",
        "--ignore-config", "--no-playlist", "--geo-bypass",
        "--no-cache-dir",            # avoid caching to disk
        "-o", outtmpl
    ]
    if os.getenv("YTDLP_FORCE_IPV4", "0") == "1":
        base += ["--force-ipv4"]
    browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip().lower()
    if browser in {"chrome", "edge", "firefox"}:
        base += ["--cookies-from-browser", browser]
    if proxy and YTDLP_USE_PROXY:
        base += ["--proxy", proxy]
    return base

def ytdlp_download(url: str, out_dir: Path, per_title_proxy: str | None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(out_dir / "%(id)s.%(ext)s")

    strategies = [
        ["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]", "--merge-output-format", "mp4"],
        ["-f", "bv*+ba/best", "--merge-output-format", "mp4"],
        ["-f", "best", "--merge-output-format", "mp4"],
    ]

    proxies_to_try = []
    if per_title_proxy:
        proxies_to_try.append(per_title_proxy)
    elif _PROXY_LIST and YTDLP_USE_PROXY:
        proxies_to_try = list(islice(_PROXY_CYCLE, 0, min(MAX_PROXY_TRIES_PER_TITLE, len(_PROXY_LIST))))
    else:
        proxies_to_try = [None]

    last_err = None
    for p_attempt_idx, proxy in enumerate(proxies_to_try):
        for s_attempt_idx, strat in enumerate(strategies):
            try:
                base = _ytdlp_cmd_base(outtmpl, proxy)
                sh(base + strat + [url], check=True)
                break
            except Exception as e:
                last_err = e
                backoff_sleep(p_attempt_idx + s_attempt_idx)
        else:
            continue
        break
    else:
        raise RuntimeError(f"yt-dlp failed for URL: {url}\nLast error:\n{last_err}")

    latest = None
    latest_mtime = -1
    for p in out_dir.glob("*"):
        if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            mtime = p.stat().st_mtime
            if mtime > latest_mtime:
                latest = p
                latest_mtime = mtime
    if not latest:
        raise RuntimeError(f"yt-dlp reported success but no file created for URL: {url}")
    return latest

# ---------- Bunny upload ----------
def bunny_upload(mp4_path: Path, remote_rel_path: str, proxy: str | None):
    import requests
    if not BUNNY_API_KEY:
        raise RuntimeError("BUNNY_API_KEY not set")

    storage_url = f"https://{BUNNY_STORAGE_HOST}/{BUNNY_STORAGE_ZONE}/{remote_rel_path.lstrip('/')}"
    headers = {"AccessKey": BUNNY_API_KEY, "Content-Type": "application/octet-stream"}

    proxies = None
    if proxy and BUNNY_USE_PROXY:
        proxies = {"http": proxy, "https": proxy}

    attempts = 0
    last_exc = None
    while attempts < 3:
        attempts += 1
        try:
            with mp4_path.open("rb") as f:
                resp = requests.put(storage_url, data=f, headers=headers, timeout=120, proxies=proxies)
            if resp.status_code in (200, 201):
                return
            if 500 <= resp.status_code < 600:
                backoff_sleep(attempts)
                continue
            raise RuntimeError(f"Bunny upload failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            last_exc = e
            backoff_sleep(attempts)
    raise RuntimeError(f"Bunny upload failed after retries: {last_exc}")

# ---------- URL builders ----------
def build_public_url(tmdb_id: int) -> str:
    return f"{BUNNY_CDN_BASE.rstrip('/')}/{BUNNY_STORAGE_SUBDIR.strip('/')}/{tmdb_id}.mp4"

def remote_rel_path(tmdb_id: int) -> str:
    return f"{BUNNY_STORAGE_SUBDIR.strip('/')}/{tmdb_id}.mp4"

# ---------- DB queryset ----------
def iter_titles_queryset():
    qs = Title.objects.exclude(trailer_url="").exclude(trailer_url=None)
    qs = qs.exclude(tmdb_id=None)
    qs = qs.filter(Q(trailer_clip_url__isnull=True) | Q(trailer_clip_url=""))
    titles = list(qs)
    random.shuffle(titles)  # randomize processing order
    if LIMIT > 0:
        titles = titles[:LIMIT]
    return titles

# ---------- Helpers ----------
def safe_rmtree(p: Path):
    try:
        shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass

def safe_unlink(p: Path):
    try:
        p.unlink(missing_ok=True)
    except Exception:
        pass

# ---------- Main ----------
def main():
    print(f"Starting trailer clip generation (DRY_RUN={DRY_RUN})")
    if _PROXY_LIST:
        print(f"Loaded {len(_PROXY_LIST)} proxies. YTDLP_USE_PROXY={YTDLP_USE_PROXY}, BUNNY_USE_PROXY={BUNNY_USE_PROXY}")
    else:
        print("No proxies configured; proceeding direct.")

    # Choose temp root (prefer TRAILER_TMP_BASE if provided)
    tmp_root: Path
    if TRAILER_TMP_BASE:
        base = Path(TRAILER_TMP_BASE)
        base.mkdir(parents=True, exist_ok=True)
        tmp_root = Path(tempfile.mkdtemp(prefix="trailer_clips_", dir=str(base)))
    else:
        tmp_root = Path(tempfile.mkdtemp(prefix="trailer_clips_"))

    processed = 0
    errors = 0

    try:
        for title in iter_titles_queryset():
            title_id = title.id
            tmdb_id = title.tmdb_id
            trailer_url = (title.trailer_url or "").strip()

            if not tmdb_id or not trailer_url:
                continue

            print(f"* Processing Title id={title_id} [{getattr(title,'type','?')}] tmdb={tmdb_id}")
            workdir = tmp_root / f"{title_id}_{tmdb_id}"

            # Each title in its own try/finally to guarantee cleanup
            src_path = None
            out_mp4 = None
            try:
                workdir.mkdir(parents=True, exist_ok=True)

                per_title_proxy = get_next_proxy() if _PROXY_LIST else None

                src_path = ytdlp_download(trailer_url, workdir, per_title_proxy)
                out_mp4 = workdir / f"clip_{tmdb_id}.mp4"
                cut_mid_clip(src_path, out_mp4, CLIP_DURATION)

                rel_path = remote_rel_path(tmdb_id)
                public_url = build_public_url(tmdb_id)

                if not DRY_RUN:
                    bunny_upload(out_mp4, rel_path, per_title_proxy)
                    with transaction.atomic():
                        fresh = Title.objects.select_for_update().get(pk=title_id)
                        fresh.trailer_clip_url = public_url
                        fresh.save(update_fields=["trailer_clip_url"])

                print(f"  ✓ Done: {public_url}")
                processed += 1

            except Exception as e:
                errors += 1
                print(f"  ✗ Error on id={title_id} tmdb={tmdb_id}: {e}")

            finally:
                # Per-title cleanup to avoid filling disk
                safe_unlink(src_path) if src_path else None
                safe_unlink(out_mp4) if out_mp4 else None
                safe_rmtree(workdir)

            time.sleep(0.2)

    finally:
        # Remove the whole temp root at the end (should be mostly empty already)
        safe_rmtree(tmp_root)

    print(f"Finished. Processed={processed}, Errors={errors}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
