# reco/imports.py
"""
Bring a profile's history from elsewhere: Letterboxd / IMDb export files.

  POST /api/import/files/?profileId=..   multipart "files": .zip (Letterboxd) / .csv  -> summary

What becomes what (an imported signal never overrides what the profile did here):
  high rating / Letterboxd heart -> like (TitleRating)     low rating -> dislike
  watched                        -> TitleAction "watched"  (seeds "Because you watched ...")
  watchlist                      -> My List
Dates are kept (rated / watched / listed), so an old history doesn't push this week's activity out
of the recommendations. Titles are matched by IMDb id, else name + year (Letterboxd).
The home page is rebuilt right after.
"""
import csv
import io
import logging
import zipfile
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

from users.models import Profile, Title

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


def parse_upload(name, data):
    """Entries in one uploaded file (.zip from Letterboxd, or a .csv). None: nothing we can read."""
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


def match(entries):
    """[(entry, title_id)] for the entries found in the catalog, [entry] for the others."""
    imdb_ids = {e.imdb for e in entries if e.imdb}
    by_imdb = dict(Title.objects.filter(imdb_code__in=imdb_ids).values_list("imdb_code", "id"))

    # by name + year: one query per batch of names (MySQL compares them case-insensitively)
    named = [e for e in entries if not by_imdb.get(e.imdb) and e.name]
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
            return Response({"code": "unknown_format", "detail": "No Letterboxd or IMDb export found.", "files": unknown}, status=400)
        summary = run_import(profile, entries[:MAX_ROWS], "+".join(sorted(sources)))
        return Response({**summary, "sources": sorted(sources), "skipped_files": unknown})

