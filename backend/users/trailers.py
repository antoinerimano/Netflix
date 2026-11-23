"""
Trailers: which YouTube video a title's trailer is, and where its short preview clip lives.

pick_trailer_url(): TMDB lists every video it knows for a title (trailers, teasers, clips, fan
uploads, one per season for a show...). Taking the first "Trailer" gave fan-made uploads,
other languages, or a season 4 trailer for a show. Each video now gets a score instead.

Preview clips (made by trailer-worker/ on a machine other than the web server, see its README):
    {BUNNY_CDN_BASE}/previews/{type}/{tmdb_id}-{youtube_key}.mp4
The type is in the path because TMDB numbers movies and shows separately: a movie and a show
can share an id, and with one folder for both the second clip overwrote the first. The YouTube
key is in the name so a new trailer gets a new file (no stale copy in the CDN's cache).
"""
import re
from typing import Iterable, Optional

YOUTUBE_KEY_RE = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})")

# words in a video's name that mean it is not the title's main trailer
_BAD_NAME_RE = re.compile(
    r"\b(season\s*[2-9]|season\s*\d{2}|s0?[2-9]\b|final season|part\s*[2-9]|volume\s*[2-9]|"
    r"re-?release|anniversary|4k|remaster\w*|restor\w*|featurette|behind the scenes|recap|"
    r"reaction|fan[- ]made|concept|parody|review|interview|clip|tv spot|spot)\b",
    re.IGNORECASE,
)
_GOOD_NAME_RE = re.compile(r"\bofficial\b.*\btrailer\b|\bmain trailer\b|\bseason\s*1\b|\bseries trailer\b", re.IGNORECASE)

_TYPE_SCORE = {"Trailer": 100, "Teaser": 40}


def youtube_key(url: str) -> str:
    """The 11-character video id of a YouTube link, '' if it isn't one."""
    m = YOUTUBE_KEY_RE.search(url or "")
    return m.group(1) if m else ""


def _score(video: dict, original_language: str) -> Optional[float]:
    if video.get("site") != "YouTube" or not video.get("key"):
        return None
    kind = _TYPE_SCORE.get(video.get("type") or "")
    if kind is None:
        return None  # clips, featurettes, behind the scenes, bloopers...
    score = float(kind)
    name = video.get("name") or ""
    if video.get("official"):
        score += 30
    if _GOOD_NAME_RE.search(name):
        score += 10
    if _BAD_NAME_RE.search(name):
        score -= 60
    lang = (video.get("iso_639_1") or "").lower()
    if original_language and lang == original_language.lower():
        score += 15
    elif lang == "en":
        score += 10
    if (video.get("size") or 0) >= 720:
        score += 3
    return score


def ranked_trailer_keys(full: dict, original_language: str = "") -> list:
    """The YouTube keys of a TMDB movie / show's trailers, best first (videos that aren't
    trailers or teasers left out). trailer-worker/ tries the next one when the best is gone,
    blocked in its country or not the title's (it loads this file, no Django needed)."""
    videos: Iterable[dict] = (full.get("videos") or {}).get("results") or []
    original_language = original_language or full.get("original_language") or ""
    ranked = []
    for v in videos:
        s = _score(v, original_language)
        if s is None:
            continue
        # equal scores: the oldest one (the original trailer, not a re-release or a late season)
        ranked.append(((s, -_published(v)), v["key"]))
    ranked.sort(key=lambda x: x[0], reverse=True)
    keys = []
    for _, key in ranked:
        if key not in keys:
            keys.append(key)
    return keys


def pick_trailer_url(full: dict, original_language: str = "") -> str:
    """Best YouTube trailer of a TMDB movie / show (fetched with append_to_response=videos)."""
    keys = ranked_trailer_keys(full, original_language)
    return f"https://www.youtube.com/watch?v={keys[0]}" if keys else ""


def _published(video: dict) -> float:
    # "2019-07-11T16:00:01.000Z": comparing the digits is enough
    digits = re.sub(r"\D", "", video.get("published_at") or "")[:14]
    return float(digits) if digits else 99999999999999.0  # undated: after the dated ones


REV_RE = re.compile(r"^[a-z0-9]{1,8}$")


def preview_path(title_type: str, tmdb_id: int, key: str, rev: str = "") -> str:
    """
    Where a title's preview clip goes in the storage zone (and on the CDN). rev: a clip made
    again from the same trailer (trailer-worker's audio re-check) gets "-{rev}" in its name: the
    CDN and browsers keep a file 30 days, so the same name would go on serving the old clip.
    """
    kind = "tv" if str(title_type).lower() == "tv" else "movie"
    suffix = f"-{rev}" if rev and REV_RE.match(rev) else ""
    return f"previews/{kind}/{int(tmdb_id)}-{key}{suffix}.mp4"


def is_clip_of(clip_url: str, title_type: str, tmdb_id: int, key: str) -> bool:
    """clip_url is a preview clip of this trailer (any rev of it)."""
    base = preview_path(title_type, tmdb_id, key)[: -len(".mp4")]
    return bool(re.search(r"/" + re.escape(base) + r"(-[a-z0-9]{1,8})?\.mp4$", clip_url or ""))


CLIP_KEY_RE = re.compile(r"/previews/(?:movie|tv)/\d+-([A-Za-z0-9_-]{11})(?:-[a-z0-9]{1,8})?\.mp4$")


def clip_youtube_key(clip_url: str) -> str:
    """The YouTube key a previews/ clip was made from, '' for anything else."""
    m = CLIP_KEY_RE.search(clip_url or "")
    return m.group(1) if m else ""


def clip_answers(clip_url: str, clip_for: str, title_type: str, tmdb_id: int, trailer_url: str) -> bool:
    """The title's clip is the one for its current trailer: made from that trailer, or made from
    another video because that trailer couldn't be used (gone, blocked, not the title's; clip_for
    = the trailer's key then, "-" for a title TMDB has no trailer for)."""
    key = youtube_key(trailer_url)
    if key and is_clip_of(clip_url, title_type, tmdb_id, key):
        return True
    return bool(clip_url and clip_for and clip_youtube_key(clip_url) and clip_for == (key or "-"))


def shown_trailer_url(trailer_url: str, clip_url: str, clip_for: str) -> str:
    """The trailer the title page plays: TMDB's, unless the worker found it couldn't be used and
    made the clip from another video (then that video)."""
    if clip_for and clip_for == (youtube_key(trailer_url) or "-"):
        key = clip_youtube_key(clip_url)
        if key:
            return f"https://www.youtube.com/watch?v={key}"
    return trailer_url
