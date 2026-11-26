# reco/imports.py
"""
Bring a profile's history from elsewhere: Letterboxd / IMDb export files, anime lists (ROADMAP 9.5).

  POST /api/import/files/?profileId=..     multipart "files": .zip (Letterboxd) / .csv (Letterboxd,
                                           IMDb) / .xml or .xml.gz (MyAnimeList export)  -> summary
  POST /api/import/anilist/?profileId=..   {"username": "..."}: a public AniList list, read from
                                           AniList's public API (no key, no sign-in)      -> summary

What becomes what (an imported signal never overrides what the profile did here):
  high rating / Letterboxd heart -> like (TitleRating)     low rating -> dislike
  watched                        -> TitleAction "watched"  (seeds "Because you watched ...")
  watchlist                      -> My List
Dates are kept (rated / watched / listed), so an old history doesn't push this week's activity out
of the recommendations. Titles are matched by IMDb id, else name + year (Letterboxd).
Anime lists (MyAnimeList / AniList) have no IMDb id and list every season on its own ("Shingeki no
Kyojin Season 3"): matched by any of their names (English, romaji, Japanese) against the title, its
original title and TMDB's other names (TitleAltName), then without the season part for shows, the
catalog's anime first (Title.section). Their statuses: completed / watching / on hold -> watched,
plan to watch -> My List, dropped -> only its score if it has one.
The home page is rebuilt right after.
"""
import csv
import gzip
import io
import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone

from django.db.models import Case, DateTimeField, Max, Q, Value, When
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

import requests

from users.models import Profile, Title, TitleAltName
from users.search import _name as name_key

from .models import MyListItem, TitleAction, TitleRating

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024      # what the user sends (a Letterboxd zip is ~1 MB)
MAX_UNZIPPED_BYTES = 40 * 1024 * 1024    # what we agree to read out of a zip (zip bombs)
MAX_ROWS = 30000
NOT_FOUND_SHOWN = 20                     # names of unmatched titles sent back (to show a few)

LIKE_AT, DISLIKE_AT = 7.0, 4.0           # on a 1-10 scale: >= like, <= dislike, between: watched only



class ImportThrottle(UserRateThrottle):
    scope = "import"


# ------------------------------------------------------------------ entries

@dataclass
class Entry:
    kind: str                  # "rating" | "watched" | "watchlist" | "like"
    source: str                # "letterboxd" | "imdb"
    rating: float | None = None   # 1-10
    imdb: str = ""
    media: str = ""            # "movie" | "tv" | "" (unknown)
    name: str = ""
    year: int | None = None
    when: datetime | None = None
    names: tuple = ()          # other names of the same title (anime lists: English, romaji, Japanese)
    anime: bool = False        # from an anime list: matched with match_anime()


def _int(v):
    try:
        return int(str(v).strip()[:4]) if str(v).strip() else None
    except ValueError:
        return None


def _float(v):
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _date(v):
    """'2023-04-01' / '2023-04-01T20:15:00.000Z' -> aware datetime (None if unreadable)"""
    s = str(v or "").strip()
    if not s:
        return None
    for fmt, size in (("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:size], fmt).replace(tzinfo=dt_timezone.utc)
        except ValueError:
            continue
    return None


IMDB_TYPES = {"movie": "movie", "tvmovie": "movie", "short": "movie", "video": "movie",
              "tvseries": "tv", "tvminiseries": "tv"}


def _imdb_media(title_type):
    key = str(title_type or "").replace(" ", "").replace("_", "").lower()
    return IMDB_TYPES.get(key)  # None: episode, video game, ... (skipped)


def parse_csv(name, text):
    """Entries of one export file, recognised from its columns (and its name for Letterboxd)."""
    reader = csv.DictReader(io.StringIO(text))
    cols = {c.strip() for c in (reader.fieldnames or [])}
    base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    out = []

    if "Const" in cols:  # IMDb: ratings.csv ("Your Rating") or a list / watchlist
        rated = "Your Rating" in cols
        for row in reader:
            media = _imdb_media(row.get("Title Type"))
            if not media or not str(row.get("Const", "")).startswith("tt"):
                continue
            entry = Entry(
                kind="rating" if rated else "watchlist", source="imdb", imdb=row["Const"].strip(), media=media,
                name=(row.get("Title") or "").strip(), year=_int(row.get("Year")),
                rating=_float(row.get("Your Rating")) if rated else None,
                when=_date(row.get("Date Rated") or row.get("Created")),
            )
            if rated and entry.rating is None:
                entry.kind = "watched"
            out.append(entry)
            if len(out) >= MAX_ROWS:
                break
        return out

    if "Letterboxd URI" in cols and "Name" in cols:
        if "watchlist" in base:
            kind = "watchlist"
        elif base.startswith("films") or "/likes/" in name.replace("\\", "/").lower():
            kind = "like"  # likes/films.csv: the films with a heart
        else:
            kind = "rating" if "Rating" in cols else "watched"  # ratings / diary / reviews / watched
        for row in reader:
            rating = _float(row.get("Rating")) if "Rating" in cols else None
            entry = Entry(
                kind=kind, source="letterboxd", media="movie",
                name=(row.get("Name") or "").strip(), year=_int(row.get("Year")),
                rating=rating * 2 if rating else None,  # 0.5-5 stars -> 1-10
                when=_date(row.get("Watched Date") or row.get("Date")),
            )
            if entry.kind == "rating" and entry.rating is None:
                entry.kind = "watched"  # a diary line without stars
            if entry.name:
                out.append(entry)
            if len(out) >= MAX_ROWS:
                break
        return out

    return None  # not a format we know


# ------------------------------------------------------------------ anime lists (ROADMAP 9.5)

# MyAnimeList's my_status / AniList's status -> what it becomes (None: skipped, unless scored)
ANIME_STATUS = {
    "completed": "watched", "watching": "watched", "on-hold": "watched", "dropped": None,
    "plan to watch": "watchlist",
    "current": "watched", "repeating": "watched", "paused": "watched", "planning": "watchlist",
}
# their formats -> our type ("" = either: an OVA / special is a movie or an episode on TMDB)
ANIME_MEDIA = {"tv": "tv", "tv_short": "tv", "ona": "tv", "movie": "movie", "ova": "", "special": "",
               "tv special": "", "tv_special": "", "": "", "unknown": ""}


def anime_entry(source, status, score, media, names, year=None, when=None):
    """One anime list line -> Entry (None: skipped: music video, dropped without a score...)."""
    status = str(status or "").strip().lower()
    media = ANIME_MEDIA.get(str(media or "").strip().lower().replace(" ", "_"),
                            ANIME_MEDIA.get(str(media or "").strip().lower()))
    names = [n.strip() for n in dict.fromkeys(str(n or "") for n in names) if n and n.strip()]
    if media is None or not names or status not in ANIME_STATUS:
        return None
    rating = score if score and score > 0 else None
    kind = ANIME_STATUS[status]
    if kind == "watched" and rating is not None:
        kind = "rating"
    if kind is None:  # dropped: only what its score says
        if rating is None:
            return None
        kind = "rating"
    return Entry(kind=kind, source=source, rating=rating if kind == "rating" else None, media=media,
                 name=names[0], names=tuple(names[1:]), year=year, when=when, anime=True)


def parse_mal_xml(data):
    """A MyAnimeList export (Profile > Export, animelist_*.xml): entries, None if it isn't one."""
    if b"<myanimelist" not in data[:4096]:
        return None
    if b"<!ENTITY" in data[:4096]:
        return None  # no entities in a real export: refused (entity expansion)
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    out = []
    for node in root.iter("anime"):
        get = lambda tag: (node.findtext(tag) or "").strip()
        entry = anime_entry(
            "myanimelist", get("my_status"), _float(get("my_score")), get("series_type"), [get("series_title")],
            when=_date(get("my_finish_date")) or _date(get("my_start_date")),
        )
        if entry:
            out.append(entry)
        if len(out) >= MAX_ROWS:
            break
    return out


ANILIST_URL = "https://graphql.anilist.co"
ANILIST_QUERY = """
query ($name: String) {
  MediaListCollection(userName: $name, type: ANIME) {
    lists { entries {
      status score(format: POINT_10_DECIMAL) updatedAt
      completedAt { year month day }
      media { format startDate { year } title { english romaji native } }
    } }
  }
}"""
ANILIST_USERNAME = re.compile(r"^[A-Za-z0-9_-]{2,30}$")


class AniListError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code  # "not_found" (no such user / private list) | "unavailable"


def anilist_entries(username, timeout=15):
    """The public anime list of an AniList user -> entries. AniListError when it can't be read."""
    try:
        res = requests.post(ANILIST_URL, json={"query": ANILIST_QUERY, "variables": {"name": username}},
                            headers={"Accept": "application/json"}, timeout=timeout)
    except requests.RequestException:
        raise AniListError("unavailable")
    try:
        body = res.json()
    except ValueError:
        body = {}
    if res.status_code == 404 or any((e or {}).get("status") == 404 for e in body.get("errors") or []):
        raise AniListError("not_found")
    collection = (body.get("data") or {}).get("MediaListCollection")
    if res.status_code != 200 or not collection:
        raise AniListError("not_found" if res.status_code in (400, 403) else "unavailable")
    out = []
    for lst in collection.get("lists") or []:
        for e in lst.get("entries") or []:
            media = e.get("media") or {}
            title = media.get("title") or {}
            done = e.get("completedAt") or {}
            when = None
            if done.get("year") and done.get("month") and done.get("day"):
                when = _date(f"{done['year']:04d}-{done['month']:02d}-{done['day']:02d}")
            elif e.get("updatedAt"):
                when = datetime.fromtimestamp(int(e["updatedAt"]), tz=dt_timezone.utc)
            entry = anime_entry(
                "anilist", e.get("status"), _float(e.get("score")), media.get("format"),
                [title.get("english"), title.get("romaji"), title.get("native")],
                year=(media.get("startDate") or {}).get("year"), when=when,
            )
            if entry:
                out.append(entry)
            if len(out) >= MAX_ROWS:
                return out
    return out


def parse_upload(name, data):
    """Entries in one uploaded file (.zip from Letterboxd, a .csv, a MyAnimeList .xml / .xml.gz).
    None: nothing we can read."""
    if data[:2] == b"\x1f\x8b":  # gzip (MyAnimeList hands out animelist_*.xml.gz)
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                data = gz.read(MAX_UNZIPPED_BYTES + 1)
        except (OSError, EOFError):
            return None
        if len(data) > MAX_UNZIPPED_BYTES:
            return None
    if data.lstrip()[:1] == b"<" or data[:3] == b"\xef\xbb\xbf":
        parsed = parse_mal_xml(data)
        if parsed is not None:
            return parsed
    if zipfile.is_zipfile(io.BytesIO(data)):
        entries, known, budget = [], False, MAX_UNZIPPED_BYTES
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".csv"):
                    continue
                low = info.filename.lower()
                # deleted/ and orphaned/ hold what the member removed; lists/ are custom lists
                if low.startswith(("deleted/", "orphaned/", "lists/")):
                    continue
                if info.file_size > budget:
                    break
                budget -= info.file_size
                with zf.open(info) as fh:
                    text = fh.read(info.file_size + 1).decode("utf-8-sig", errors="replace")
                parsed = parse_csv(info.filename, text)
                if parsed is not None:
                    known = True
                    entries += parsed
        return entries if known else None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return parse_csv(name, text)


# ------------------------------------------------------------------ matching

def _norm(s):
    return " ".join(str(s or "").lower().split())


# "Season 2", "2nd Season", "Part 2", "Cour 2", "Final Season", "II": the same show on TMDB
_SEASON_PART = re.compile(
    r"(\s*[:\-]?\s*((the\s+)?final\s+season|(season|saison|part|cour)\s*\d+|\d+(st|nd|rd|th)\s+season)\b.*$)"
    r"|(\s+(ii|iii|iv|v|vi)$)", re.I,
)


def _show_names(name):
    """Shorter forms of an anime season's name: without the season part, then before a colon."""
    out = []
    base = _SEASON_PART.sub("", name).strip(" :-")
    if base and base != name:
        out.append(base)
    for n in (name, base):
        if ":" in n:
            head = n.split(":", 1)[0].strip()
            if len(head) >= 3:
                out.append(head)
    return [n for n in dict.fromkeys(out) if n]


def _title_year(t):
    return t["release_year"] or _int((t.get("first_air_date") or "")[:4])


def match_anime(entries):
    """match() for anime list entries: {id(entry): title_id} of the ones found."""
    exact, shorter = {}, {}  # entry index -> [name keys]
    raw = set()
    for i, e in enumerate(entries):
        names = [e.name, *e.names]
        exact[i] = {name_key(n) for n in names} - {""}
        raw.update(names)
        if e.media != "movie":
            short = [s for n in names for s in _show_names(n)]
            shorter[i] = {name_key(n) for n in short} - {""} - exact[i]
            raw.update(short)

    fields = ("id", "type", "title", "original_title", "release_year", "first_air_date", "popularity", "section")
    candidates = {}
    raw = list(raw)
    keys = list({k for ks in (*exact.values(), *shorter.values()) for k in ks})
    by_id = {}
    for i in range(0, len(raw), 500):
        batch = raw[i:i + 500]
        for t in Title.objects.filter(Q(title__in=batch) | Q(original_title__in=batch)).values(*fields):
            by_id[t["id"]] = t
            for key in {name_key(t["title"]), name_key(t["original_title"])} - {""}:
                candidates.setdefault(key, {})[t["id"]] = t
    for i in range(0, len(keys), 500):
        for alt in TitleAltName.objects.filter(name_norm__in=keys[i:i + 500]).values("name_norm", "title_id"):
            candidates.setdefault(alt["name_norm"], {})[alt["title_id"]] = None
    missing = {tid for c in candidates.values() for tid, t in c.items() if t is None and tid not in by_id}
    if missing:
        by_id.update({t["id"]: t for t in Title.objects.filter(id__in=missing).values(*fields)})

    def best(e, keys, later_season):
        best_id, best_score = None, None
        for key in keys:
            for tid in candidates.get(key, {}):
                t = by_id.get(tid)
                if not t or (e.media and t["type"] != e.media):
                    continue
                year = _title_year(t)
                gap = abs(year - e.year) if (e.year and year) else 0
                if t["type"] == "tv" and e.year and year:
                    gap = 0 if e.year >= year - 1 else 9  # a later season started after the show
                if gap > 1 and not later_season:
                    continue
                score = (t["section"] != "anime", gap, -(t["popularity"] or 0))
                if best_score is None or score < best_score:
                    best_id, best_score = tid, score
        return best_id

    found = {}
    for i, e in enumerate(entries):
        tid = best(e, exact[i], False) or (best(e, shorter.get(i, ()), True) if shorter.get(i) else None)
        if tid:
            found[i] = tid
    return found


def match(entries):
    """[(entry, title_id)] for the entries found in the catalog, [entry] for the others."""
    anime = [e for e in entries if e.anime]
    anime_found = match_anime(anime) if anime else {}
    anime_ids = {id(e): anime_found.get(i) for i, e in enumerate(anime)}
    entries_rest = [e for e in entries if not e.anime]
    imdb_ids = {e.imdb for e in entries_rest if e.imdb}
    by_imdb = dict(Title.objects.filter(imdb_code__in=imdb_ids).values_list("imdb_code", "id"))

    # by name + year: one query per batch of names (MySQL compares them case-insensitively)
    named = [e for e in entries_rest if not by_imdb.get(e.imdb) and e.name]
    candidates = {}
    names = list({e.name for e in named})
    for i in range(0, len(names), 500):
        batch = names[i:i + 500]
        for t in (
            Title.objects.filter(Q(title__in=batch) | Q(original_title__in=batch))
            .values("id", "type", "title", "original_title", "release_year", "popularity")
        ):
            for key in {_norm(t["title"]), _norm(t["original_title"])} - {""}:
                candidates.setdefault(key, []).append(t)

    def by_name(e):
        best, best_score = None, None
        for t in candidates.get(_norm(e.name), []):
            if e.media and t["type"] != e.media:
                continue
            gap = abs((t["release_year"] or 0) - e.year) if e.year and t["release_year"] else (0 if not e.year else 9)
            if gap > 1:
                continue
            score = (gap, -(t["popularity"] or 0))
            if best_score is None or score < best_score:
                best, best_score = t["id"], score
        return best

    found, missing = [], []
    for e in entries:
        if e.anime:
            tid = anime_ids.get(id(e))
        else:
            tid = by_imdb.get(e.imdb) or (by_name(e) if e.name else None)
        if tid:
            found.append((e, tid))
        else:
            missing.append(e)
    return found, missing


# ------------------------------------------------------------------ saving

def _set_dates(model, field, dates):
    """{pk: datetime}: auto_now(_add) fields can't be given on create, so set after (500 per query)."""
    items = [(pk, when) for pk, when in dates.items() if when]
    for i in range(0, len(items), 500):
        chunk = items[i:i + 500]
        model.objects.filter(pk__in=[pk for pk, _ in chunk]).update(**{
            field: Case(*[When(pk=pk, then=Value(when)) for pk, when in chunk], output_field=DateTimeField())
        })


def apply(profile, found, source):
    """Save the matched entries for the profile; counts of what was added."""
    now = timezone.now()
    per_title = {}  # title id -> what the history says about it, merged over files
    for e, tid in found:
        cur = per_title.setdefault(tid, {"rating": None, "liked": False, "watched": False, "listed": False, "when": None})
        if e.kind == "like":
            cur["liked"] = True
        elif e.kind == "watchlist":
            cur["listed"] = True
        else:
            cur["watched"] = True
            if e.rating is not None:
                cur["rating"] = e.rating
        if e.when and (cur["when"] is None or e.when > cur["when"]):
            cur["when"] = e.when
    # undated (rare): a year ago, in file order (exports list the newest first); never in the future
    for i, info in enumerate(per_title.values()):
        info["when"] = min(info["when"] or now - timedelta(days=365, seconds=i), now)

    rated_here = set(TitleRating.objects.filter(profile=profile).values_list("title_id", flat=True))
    watched_here = set(
        TitleAction.objects.filter(profile=profile, action__in=["watched", "outbound"]).values_list("title_id", flat=True)
    )
    listed_here = set(MyListItem.objects.filter(profile=profile).values_list("title_id", flat=True))

    ratings, actions, listed = [], [], []
    counts = {"liked": 0, "disliked": 0, "watched": 0, "listed": 0}
    for tid, info in per_title.items():
        value = None
        if info["liked"] or (info["rating"] is not None and info["rating"] >= LIKE_AT):
            value = TitleRating.LIKE
        elif info["rating"] is not None and info["rating"] <= DISLIKE_AT:
            value = TitleRating.DISLIKE
        if value and tid not in rated_here:
            ratings.append((TitleRating(profile=profile, title_id=tid, value=value), info["when"]))
            counts["liked" if value == TitleRating.LIKE else "disliked"] += 1
        if (info["watched"] or info["liked"]) and tid not in watched_here:
            actions.append((
                TitleAction(profile=profile, title_id=tid, action="watched", session_id="", provider=f"import:{source}"),
                info["when"],
            ))
            counts["watched"] += 1
        # the watchlist: only what wasn't watched since
        if info["listed"] and not info["watched"] and tid not in listed_here:
            listed.append((MyListItem(profile=profile, title_id=tid), info["when"]))
            counts["listed"] += 1

    for model, field, rows in (
        (TitleRating, "updated_at", ratings), (TitleAction, "created_at", actions), (MyListItem, "added_at", listed),
    ):
        if not rows:
            continue
        last_pk = model.objects.aggregate(m=Max("pk"))["m"] or 0
        model.objects.bulk_create([obj for obj, _ in rows], batch_size=1000)
        # MySQL doesn't hand back the new ids: the rows this import just added, by title
        new = model.objects.filter(profile=profile, pk__gt=last_pk)
        if model is TitleAction:
            new = new.filter(action="watched")
        pk_by_title = dict(new.values_list("title_id", "pk"))
        _set_dates(model, field, {pk_by_title.get(obj.title_id): when for obj, when in rows})
    return counts


def run_import(profile, entries, source):
    from .taste import rebuild_home

    found, missing = match(entries)
    counts = apply(profile, found, source)
    home = "rebuilt" if (any(counts.values()) and rebuild_home(profile)) else "unchanged"
    examples = []
    for e in missing:
        label = f"{e.name} ({e.year})" if e.year else e.name
        if label and label not in examples:
            examples.append(label)
        if len(examples) >= NOT_FOUND_SHOWN:
            break
    return {
        **counts,
        "matched": len({tid for _, tid in found}),
        "not_found": len({(e.name, e.year, e.imdb) for e in missing}),
        "not_found_examples": examples,
        "home": home,
    }


# ------------------------------------------------------------------ views

def _profile(request):
    return get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)


class ImportFilesView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]
    throttle_classes = [ImportThrottle]

    def post(self, request):
        profile = _profile(request)
        files = request.FILES.getlist("files")
        if not files:
            return Response({"code": "no_file", "detail": "Send the export file(s) as \"files\"."}, status=400)
        if sum(f.size for f in files) > MAX_UPLOAD_BYTES:
            return Response({"code": "too_big", "detail": "Files over 10 MB are refused."}, status=400)

        entries, sources, unknown = [], set(), []
        for f in files:
            parsed = parse_upload(f.name, f.read())
            if parsed is None:
                unknown.append(f.name)
                continue
            entries += parsed
            sources.update(e.source for e in parsed)
        if not entries:
            return Response({"code": "unknown_format", "detail": "No Letterboxd, IMDb or MyAnimeList export found.",
                             "files": unknown}, status=400)
        summary = run_import(profile, entries[:MAX_ROWS], "+".join(sorted(sources)))
        return Response({**summary, "sources": sorted(sources), "skipped_files": unknown})



class ImportAniListView(APIView):
    """POST {"username": "..."}: the user's public AniList anime list (ROADMAP 9.5)."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [ImportThrottle]

    def post(self, request):
        profile = _profile(request)
        username = str(request.data.get("username") or "").strip().lstrip("@")
        m = re.search(r"anilist\.co/user/([^/?#]+)", username)  # a pasted profile link
        if m:
            username = m.group(1)
        if not ANILIST_USERNAME.match(username):
            return Response({"code": "bad_username", "detail": "An AniList user name: letters, digits, _ or -."},
                            status=400)
        try:
            entries = anilist_entries(username)
        except AniListError as e:
            status_code = 404 if e.code == "not_found" else 502
            return Response({"code": f"anilist_{e.code}", "detail": "That AniList list can't be read."},
                            status=status_code)
        if not entries:
            return Response({"code": "anilist_empty", "detail": "That AniList list is empty."}, status=400)
        summary = run_import(profile, entries[:MAX_ROWS], "anilist")
        return Response({**summary, "sources": ["anilist"], "skipped_files": []})
