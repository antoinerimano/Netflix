#!/usr/bin/env python3
"""
Trailer preview clips, made on a machine at home (not the web server, see README.md).

    python make_previews.py jobs.json            # jobs.json: manage.py export_trailer_jobs

For each title: read the YouTube video's details, check its name is the title's, download only
the part that is kept (about 17 s, 540p at most), encode a small clip (~2 MB), upload it to
Bunny Storage at the job's path, and note the result in results.json (saved after every title:
stop it any time, the next run carries on). manage.py import_trailer_results reads that file.

Statuses in results.json:
  ok           uploaded; the import saves it on the title
  rejected     the video's name isn't the title's (another show, a sequel, or not a trailer): not uploaded
  unavailable  private / removed / blocked video: not tried again until TMDB has another one
  error        anything else (network, ffmpeg...): tried again on the next runs, 3 times at most

YouTube blocks addresses that download too fast ("Sign in to confirm you're not a bot"): the
script waits DELAY_MIN..DELAY_MAX seconds between titles, and stops (exit code 75) as soon as
YouTube refuses, to try again on the next run.

Needs: Python 3.10+, ffmpeg / ffprobe, `pip install -r requirements.txt`. Settings: .env (see
.env.example).
"""
import argparse
import hashlib
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXIT_BLOCKED = 75  # YouTube refused: try again later


# ---------- settings (.env next to this file, then the environment) ----------
def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env(HERE / ".env")
BUNNY_STORAGE_ZONE = os.getenv("BUNNY_STORAGE_ZONE", "")
BUNNY_STORAGE_HOST = os.getenv("BUNNY_STORAGE_HOST", "ny.storage.bunnycdn.com")
BUNNY_API_KEY = os.getenv("BUNNY_API_KEY", "")
BUNNY_CDN_BASE = os.getenv("BUNNY_CDN_BASE", "https://zuvo-movies-cdn.b-cdn.net").rstrip("/")
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
CLIP_SECONDS = float(os.getenv("CLIP_SECONDS", "15"))
HEIGHT = int(os.getenv("PREVIEW_HEIGHT", "540"))  # rows show ~300-500 px; the home banner too
CRF = os.getenv("VIDEO_CRF", "27")
MAXRATE_K = int(os.getenv("VIDEO_MAXRATE_K", "1100"))
PRESET = os.getenv("VIDEO_PRESET", "slow")  # slow: smaller files; a home PC has the time
DELAY_MIN = float(os.getenv("DELAY_MIN", "10"))
DELAY_MAX = float(os.getenv("DELAY_MAX", "20"))
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))
COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()  # optional, if YouTube insists
TMP_BASE = os.getenv("TMP_BASE", "").strip() or None

# "Please sign in" and "use a VPN or a proxy" are YouTube refusing this machine too: counted as a
# title's error, they used up its 3 attempts and the title was never tried again
BLOCKED_RE = re.compile(r"confirm you.re not a bot|HTTP Error 429|Too Many Requests|rate.limit|"
                        r"Please sign in|use a VPN or a proxy", re.I)
UNAVAILABLE_RE = re.compile(
    r"Video unavailable|Private video|has been removed|account .* terminated|not available in your country|"
    r"members-only|age.restricted|Sign in to confirm your age|copyright", re.I)


class Blocked(Exception):
    pass


class Unavailable(Exception):
    pass


class Rejected(Exception):
    pass


# ---------- shell ----------
def run(cmd: list, timeout: int = 300) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"timed out: {cmd[0]} {cmd[1] if len(cmd) > 1 else ''}")
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "").strip()
        if BLOCKED_RE.search(err):
            raise Blocked(err.splitlines()[-1] if err else "blocked")
        if UNAVAILABLE_RE.search(err):
            raise Unavailable(err.splitlines()[-1] if err else "unavailable")
        raise RuntimeError(err[-800:] or f"exit code {p.returncode}")
    return p.stdout


def ytdlp(*args: str) -> list:
    cmd = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-cache-dir",
           "--no-progress", "--quiet", "--no-warnings"]
    if COOKIES_FILE:
        cmd += ["--cookies", COOKIES_FILE]
    return cmd + list(args)


# ---------- is this video the title's trailer? ----------
def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").casefold()
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ")
    return " ".join(re.sub(r"[^\w]+", " ", s).split())


def _compact_on_word_edges(n_compact: str, v_words: list) -> bool:
    """n with its spaces removed is in v with its spaces removed, starting and ending where v's
    words do: "Spider-Man" in "Spiderman Trailer", but not "Alien" in "Aliens Trailer"."""
    v_compact = "".join(v_words)
    starts, ends, pos = set(), set(), 0
    for w in v_words:
        starts.add(pos)
        pos += len(w)
        ends.add(pos)
    i = v_compact.find(n_compact)
    while i != -1:
        if i in starts and i + len(n_compact) in ends:
            return True
        i = v_compact.find(n_compact, i + 1)
    return False


def name_matches(video_name: str, *names: str) -> bool:
    """The title (or its original title) is in the video's name, give or take punctuation."""
    v = norm(video_name)
    words = v.split()
    for name in names:
        n = norm(name)
        if not n:
            continue
        if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", v):
            return True
        n_compact = n.replace(" ", "")
        if len(n_compact) >= 5 and _compact_on_word_edges(n_compact, words):  # "Spider-Man" / "Spiderman"
            return True
        # a letter or two off inside the name ("Pirates of the Carribean"), never at its first or
        # last word: "American Horror Stories" is another show than "American Horror Story"
        n_words = n.split()
        if len(n) >= 8 and len(n_words) >= 2:
            size = len(n_words)
            for width in (size - 1, size, size + 1):
                for i in range(max(0, len(words) - width + 1)):
                    window = words[i:i + width]
                    if window[0] != n_words[0] or window[-1] != n_words[-1]:
                        continue
                    if SequenceMatcher(None, n, " ".join(window)).ratio() >= 0.88:
                        return True
        # "Star Wars: Episode IV - A New Hope" vs a video called "Star Wars: A New Hope": the part
        # after the colon is enough when it is long
        for part in re.split(r"\s*[:\-–]\s*", name):
            p = norm(part)
            if len(p) >= 10 and re.search(rf"(?<!\w){re.escape(p)}(?!\w)", v):
                return True
    return False


# what follows a film's name in its sequel's: "Toy Story 4", "Dune: Part Two", "John Wick: Chapter 2"
SEQUEL = r"(?:[2-9]|1[0-9]|ii|iii|iv|vi|vii|viii|ix|x|part \w+|chapter \w+)"


def is_sequel_of(video_name: str, *names: str) -> bool:
    """The video's name is the film's name followed by a sequel's number / part (and that isn't
    in the film's own name: "Fast & Furious 6" is fine for "Fast & Furious 6")."""
    v = norm(video_name)
    for name in names:
        n = norm(name)
        if not n:
            continue
        for m in re.finditer(rf"(?<!\w){re.escape(n)} ({SEQUEL})(?!\w)", v):
            if not re.search(rf"(?<!\w){re.escape(n)} {re.escape(m.group(1))}(?!\w)", n):
                return True
    return False


def check_video(info: dict, job: dict) -> None:
    duration = float(info.get("duration") or 0)
    if duration and duration < 20:
        raise Rejected(f"too short to be a trailer ({duration:.0f} s)")
    if duration > 600:
        raise Rejected(f"too long to be a trailer ({duration / 60:.0f} min)")
    if info.get("is_live") or info.get("was_live"):
        raise Rejected("a live stream")
    names = (job.get("title", ""), job.get("original_title", ""))
    if not name_matches(info.get("title") or "", *names):
        raise Rejected(f"the video is called {info.get('title')!r}")
    # a show's "Season 2 Trailer" is still the show's; a film's "... 2 Trailer" is another film
    if job.get("type") == "movie" and is_sequel_of(info.get("title") or "", *names):
        raise Rejected(f"the video is called {info.get('title')!r} (a sequel)")


# ---------- one title ----------
def has_dubbed_audio(info: dict) -> bool:
    """The video carries more than its own audio (YouTube's AI dubs, other language tracks)."""
    audio = [f for f in info.get("formats") or [] if f.get("acodec") not in (None, "none")]
    if any("original" in (f.get("format_note") or "").lower() for f in audio):
        return True  # YouTube only says "original" when there are other tracks
    langs = {(f.get("language") or "").split("-")[0].lower() for f in audio if f.get("language")}
    return len(langs) > 1


def make_clip(job: dict, workdir: Path, info: dict | None = None, check: bool = True) -> tuple[Path, dict]:
    url = job["trailer_url"]
    if info is None:
        info = json.loads(run(ytdlp("-J", "--skip-download", url), timeout=120) or "{}")
    if check:
        check_video(info, job)

    duration = float(info.get("duration") or 0)
    clip = min(CLIP_SECONDS, max(5.0, duration - 2)) if duration else CLIP_SECONDS
    # the middle of the trailer: past the studio logos, before the credits
    start = max(0.0, duration / 2 - clip / 2) if duration else 0.0
    section = f"*{max(0.0, start - 1):.1f}-{start + clip + 2:.1f}"

    # the trailer's own audio: many videos now also carry YouTube's AI-dubbed tracks (Russian,
    # Indonesian...), often a few KB smaller, so "+size" alone picked one. "original" is in the
    # original track's format_note; "lang" sorts it first when the note is missing.
    run(ytdlp("-f", "bv*+ba[format_note*=original]/bv*+ba/b", "-S", f"lang,res:{HEIGHT},+size",
              "--download-sections", section,
              "--merge-output-format", "mkv", "-o", str(workdir / "src.%(ext)s"), url), timeout=600)
    sources = [p for p in workdir.iterdir() if p.name.startswith("src.") and p.stat().st_size > 0]
    if not sources:
        raise RuntimeError("yt-dlp downloaded nothing")

    out = workdir / "preview.mp4"
    fade_out = max(0.0, clip - 0.6)
    run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(sources[0]), "-t", f"{clip:.2f}",
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale=-2:'min({HEIGHT},ih)',fade=t=in:st=0:d=0.4,fade=t=out:st={fade_out:.2f}:d=0.6,format=yuv420p",
        "-c:v", "libx264", "-preset", PRESET, "-crf", CRF, "-profile:v", "main",
        "-maxrate", f"{MAXRATE_K}k", "-bufsize", f"{MAXRATE_K * 2}k", "-g", "48",
        "-af", f"afade=t=in:d=0.4,afade=t=out:st={fade_out:.2f}:d=0.6",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2",
        "-movflags", "+faststart",  # plays while it downloads
        str(out),
    ], timeout=900)
    size = out.stat().st_size if out.exists() else 0
    if size < 50_000:
        raise RuntimeError(f"ffmpeg made a {size} byte file")
    return out, {"video_title": info.get("title") or "", "channel": info.get("channel") or "", "bytes": size}


def bunny_upload(path: Path, remote: str) -> None:
    import requests

    data = path.read_bytes()
    url = f"https://{BUNNY_STORAGE_HOST}/{BUNNY_STORAGE_ZONE}/{remote}"
    headers = {
        "AccessKey": BUNNY_API_KEY,
        "Content-Type": "application/octet-stream",
        "Checksum": hashlib.sha256(data).hexdigest().upper(),  # Bunny refuses a damaged upload
    }
    last = None
    for attempt in range(3):
        try:
            r = requests.put(url, data=data, headers=headers, timeout=120)
            if r.status_code in (200, 201):
                return
            last = f"{r.status_code} {r.text[:200]}"
            if r.status_code < 500:
                break
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Bunny upload failed: {last}")


# ---------- results.json ----------
def job_key(job: dict) -> str:
    return f"{job['type']}:{job['tmdb_id']}:{job['youtube_key']}"


def load_results(path: Path) -> dict:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("results"), dict):
            return data
    return {"version": 1, "results": {}}


def save_results(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    os.replace(tmp, path)  # never half a file, even if the power goes


def is_done(r: dict | None) -> bool:
    if not r:
        return False
    return r.get("status") in ("ok", "rejected", "unavailable") or r.get("attempts", 0) >= MAX_ATTEMPTS


def lock(path: Path):
    """One run at a time (a nightly run still going when the next one starts)."""
    f = open(path, "w")
    try:
        import fcntl
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        pass  # not Linux: no lock
    except OSError:
        print("Another run is going: stopping.")
        sys.exit(0)
    return f


# ---------- clips made before the original audio was asked for ----------
def next_rev(rev: str) -> str:
    """'' -> 'a' -> 'b'...: the name suffix of a clip made again (see recheck_audio)."""
    return chr(ord(rev) + 1) if len(rev) == 1 and "a" <= rev < "z" else "a"


def redo_path(entry: dict, rev: str) -> str:
    """Same name as the server's users/trailers.preview_path(type, tmdb_id, key, rev)."""
    kind = "tv" if entry["type"] == "tv" else "movie"
    return f"previews/{kind}/{int(entry['tmdb_id'])}-{entry['youtube_key']}-{rev}.mp4"

def recheck_audio(data: dict, results_path: Path, limit: int, dry_run: bool, deadline, stopping) -> int:
    """
    Clips made before make_clip asked for the original audio could carry one of YouTube's AI
    dubs (The Walking Dead came out in another language). For up to `limit` "ok" clips not
    checked yet: when the video has other audio tracks, make the clip again under a new name
    ("{tmdb_id}-{key}-a.mp4", entry["rev"]: the CDN and browsers keep a file 30 days, so the same
    name would go on serving the old clip; import_trailer_results saves the new URL); otherwise
    just note it is fine.
    entry["audio"]: "single" (one track, the clip was right), "redone", "gone" (video removed).
    """
    results = data["results"]
    todo = [(k, r) for k, r in results.items() if r.get("status") == "ok" and not r.get("audio")]
    print(f"Audio re-check: {len(todo)} clip(s) not checked yet, {min(limit, len(todo))} now")
    counts = {"single": 0, "redone": 0, "gone": 0, "error": 0}
    for i, (key, entry) in enumerate(todo[:limit]):
        if stopping["now"] or (deadline and time.monotonic() > deadline):
            break
        label = f"[audio {i + 1}] {entry['type']} {entry['tmdb_id']} {entry.get('title', '')!r}"
        url = f"https://www.youtube.com/watch?v={entry['youtube_key']}"
        workdir = Path(tempfile.mkdtemp(prefix="recheck_", dir=TMP_BASE))
        try:
            info = json.loads(run(ytdlp("-J", "--skip-download", url), timeout=120) or "{}")
            if not has_dubbed_audio(info):
                entry["audio"] = "single"
            else:
                # the name was checked when it was first made: only the audio is redone
                rev = next_rev(entry.get("rev", ""))
                path = redo_path(entry, rev)
                job = {"type": entry["type"], "tmdb_id": entry["tmdb_id"], "title": entry.get("title", ""),
                       "trailer_url": url, "path": path}
                clip, details = make_clip(job, workdir, info=info, check=False)
                if not dry_run:
                    bunny_upload(clip, path)
                entry.update(details, audio="redone", rev=rev, path=path, url=f"{BUNNY_CDN_BASE}/{path}",
                             at=time.strftime("%Y-%m-%dT%H:%M:%S"))
            print(f"{label} {entry['audio']}")
        except Blocked as e:
            print(f"{label} YouTube refused ({e}): stopping, the next run carries on")
            return EXIT_BLOCKED
        except Unavailable:
            entry["audio"] = "gone"  # the clip already made stays
            print(f"{label} video gone, clip kept")
        except Exception as e:  # noqa: BLE001
            entry["audio_errors"] = entry.get("audio_errors", 0) + 1
            if entry["audio_errors"] >= MAX_ATTEMPTS:
                entry["audio"] = "error"
            print(f"{label} error: {str(e).splitlines()[-1] if str(e) else e}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        counts[entry.get("audio") if entry.get("audio") in counts else "error"] += 1
        if not dry_run:
            save_results(results_path, data)
        time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    print("Audio re-check done: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


# ---------- main ----------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("jobs", nargs="?", help="jobs.json from manage.py export_trailer_jobs")
    ap.add_argument("--results", default=str(HERE / "results.json"))
    ap.add_argument("--limit", type=int, default=0, help="Stop after this many titles.")
    ap.add_argument("--max-minutes", type=float, default=0, help="Stop after this long.")
    ap.add_argument("--dry-run", action="store_true", help="Make the clips, don't upload them.")
    ap.add_argument("--recheck-audio", type=int, default=0, metavar="N",
                    help="Instead of jobs: re-check N clips already made for a dubbed audio track.")
    args = ap.parse_args()
    if not args.jobs and not args.recheck_audio:
        ap.error("give jobs.json, or --recheck-audio N")

    if not args.dry_run and not (BUNNY_API_KEY and BUNNY_STORAGE_ZONE):
        print("Set BUNNY_API_KEY and BUNNY_STORAGE_ZONE in .env (see .env.example).")
        return 2
    if not shutil.which(FFMPEG):
        print(f"ffmpeg not found ({FFMPEG}): sudo apt install ffmpeg")
        return 2

    results_path = Path(args.results)
    _lock = lock(results_path.with_suffix(".lock"))  # noqa: F841 (held until exit)
    data = load_results(results_path)
    results = data["results"]
    stopping = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stopping.update(now=True))
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
    if args.recheck_audio:
        return recheck_audio(data, results_path, args.recheck_audio, args.dry_run, deadline, stopping)

    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8")).get("jobs") or []
    todo = [j for j in jobs if not is_done(results.get(job_key(j)))]
    print(f"{len(jobs)} job(s), {len(todo)} to do")
    counts = {"ok": 0, "rejected": 0, "unavailable": 0, "error": 0}
    exit_code = 0

    for i, job in enumerate(todo):
        if stopping["now"] or (args.limit and i >= args.limit) or (deadline and time.monotonic() > deadline):
            break
        key = job_key(job)
        prev = results.get(key) or {}
        entry = {k: job[k] for k in ("type", "tmdb_id", "youtube_key", "path")}
        entry["title"] = job.get("title", "")
        label = f"[{i + 1}/{len(todo)}] {job['type']} {job['tmdb_id']} {job.get('title', '')!r}"
        workdir = Path(tempfile.mkdtemp(prefix="preview_", dir=TMP_BASE))
        try:
            clip, details = make_clip(job, workdir)
            entry.update(details)
            if not args.dry_run:
                bunny_upload(clip, job["path"])
            entry.update(status="ok", url=f"{BUNNY_CDN_BASE}/{job['path']}")
            print(f"{label} ok ({details['bytes'] // 1024} KB)")
        except Blocked as e:
            print(f"{label} YouTube refused ({e}): stopping, the next run carries on")
            exit_code = EXIT_BLOCKED
            break
        except Rejected as e:
            entry.update(status="rejected", reason=str(e))
            print(f"{label} rejected: {e}")
        except Unavailable as e:
            entry.update(status="unavailable", reason=str(e)[:300])
            print(f"{label} unavailable: {e}")
        except Exception as e:  # noqa: BLE001 (one title's problem must not stop the run)
            entry.update(status="error", reason=str(e)[:500], attempts=prev.get("attempts", 0) + 1)
            print(f"{label} error: {str(e).splitlines()[-1] if str(e) else e}")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        entry["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not args.dry_run:
            results[key] = entry
            save_results(results_path, data)
        counts[entry["status"]] += 1
        if i + 1 < len(todo):
            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))

    print("Done: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped (results.json is up to date).")
        sys.exit(130)
