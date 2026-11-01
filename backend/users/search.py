# users/search.py
# Search: titles (anywhere in the name), actors, directors, keywords, typo tolerance, and
# natural-language queries like "90s crime shows like CSI" (decade / genre / type / "like X").
import math
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from django.db.models import Q

from .maturity import allowed_titles_q
from .models import Actor, Title, TitleKeyword

# words -> genre names as stored in Title.genre (movie and TV names differ)
GENRE_WORDS = {
    "crime": ["Crime"], "comedy": ["Comedy"], "comedies": ["Comedy"], "funny": ["Comedy"],
    "sitcom": ["Comedy"], "sitcoms": ["Comedy"],
    "horror": ["Horror"], "scary": ["Horror"], "action": ["Action", "Action & Adventure"],
    "drama": ["Drama"], "dramas": ["Drama"], "romance": ["Romance"], "romantic": ["Romance"],
    "romcom": ["Romance"], "thriller": ["Thriller"], "thrillers": ["Thriller"],
    "scifi": ["Science Fiction", "Sci-Fi & Fantasy"], "sci-fi": ["Science Fiction", "Sci-Fi & Fantasy"],
    "animation": ["Animation"], "animated": ["Animation"], "cartoon": ["Animation"], "cartoons": ["Animation"],
    "anime": ["Animation"],
    "documentary": ["Documentary"], "documentaries": ["Documentary"], "docs": ["Documentary"],
    "family": ["Family"], "kids": ["Kids", "Family"], "fantasy": ["Fantasy", "Sci-Fi & Fantasy"],
    "mystery": ["Mystery"], "mysteries": ["Mystery"], "war": ["War", "War & Politics"],
    "western": ["Western"], "westerns": ["Western"], "musical": ["Music"], "musicals": ["Music"],
    "history": ["History"], "historical": ["History"], "adventure": ["Adventure", "Action & Adventure"],
    "reality": ["Reality"],
}
PHRASES = {"science fiction": "scifi", "sci fi": "scifi", "rom com": "romcom", "true crime": "crime"}
TYPE_WORDS = {
    "movie": "movie", "movies": "movie", "film": "movie", "films": "movie",
    "show": "tv", "shows": "tv", "series": "tv", "tv": "tv", "sitcom": "tv", "sitcoms": "tv",
}
FILLER = {"the", "a", "an", "some", "good", "best", "top", "great", "about", "me", "from", "in", "of", "and", "s"}

# MySQL FULLTEXT (migration 0017): words shorter than this and InnoDB stopwords aren't indexed
FT_MIN_WORD = 3
FT_STOPWORDS = {
    "a", "about", "an", "are", "as", "at", "be", "by", "com", "de", "en", "for", "from", "how", "i", "in",
    "is", "it", "la", "of", "on", "or", "that", "the", "this", "to", "was", "what", "when", "where", "who",
    "will", "with", "und", "www",
}
ARTICLES = ("the ", "a ", "an ")

FUZZY_POOL = 60000        # most popular titles indexed for typo tolerance
FUZZY_TTL = 6 * 3600
FUZZY_MIN_RATIO = 0.72


@dataclass
class ParsedQuery:
    text: str = ""            # what is left to match against names
    kind: str = ""            # "movie" | "tv" | ""
    year_from: int = None
    year_to: int = None
    genres: list = field(default_factory=list)  # one list of genre names per genre word (AND between them)
    genre_words: list = field(default_factory=list)
    like: str = ""            # "like X" / "similar to X"
    starring: str = ""        # "with X" / "starring X"

    @property
    def has_filters(self):
        return bool(self.kind or self.year_from or self.genres)


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s'-]", " ", (s or "").lower())).strip()


def _name(s):
    """norm() without a leading article: "The Office" and "office" are the same name."""
    s = norm(s)
    for article in ARTICLES:
        if s.startswith(article):
            return s[len(article):]
    return s


def _ft_expr(text):
    """FULLTEXT boolean query: every indexable word, as a prefix ("+bryan* +cranst*"), or None."""
    words = [w for w in re.findall(r"\w+", norm(text)) if len(w) >= FT_MIN_WORD and w not in FT_STOPWORDS]
    return " ".join(f"+{w}*" for w in words) or None


def _ft(qs, columns, expr):
    return qs.extra(where=[f"MATCH({columns}) AGAINST (%s IN BOOLEAN MODE)"], params=[expr])


def parse_query(q):
    p = ParsedQuery()
    s = " " + norm(q) + " "

    m = re.search(r"\b(?:like|similar to)\s+(.+)$", s)
    if m:
        p.like = m.group(1).strip()
        s = s[: m.start()] + " "
    m = re.search(r"\b(?:with|starring)\s+(.+)$", s)
    if m:
        p.starring = m.group(1).strip()
        s = s[: m.start()] + " "

    m = re.search(r"\b((?:19|20)\d\d)\s*[-–]\s*((?:19|20)\d\d)\b", s)
    if m:
        p.year_from, p.year_to = sorted((int(m.group(1)), int(m.group(2))))
        s = s.replace(m.group(0), " ")
    else:
        m = re.search(r"\b((?:19|20)?\d0)\s*'?\s*s\b", s)  # 90s, 1990s, 90's, 2010s
        if m:
            d = m.group(1)
            start = int(d) if len(d) == 4 else (1900 + int(d) if int(d) >= 30 else 2000 + int(d))
            p.year_from, p.year_to = start, start + 9
            s = s.replace(m.group(0), " ")
        else:
            m = re.search(r"\b((?:19|20)\d\d)\b", s)
            if m:
                p.year_from = p.year_to = int(m.group(1))
                s = s.replace(m.group(0), " ")

    for phrase, word in PHRASES.items():
        s = s.replace(f" {phrase} ", f" {word} ")

    rest = []
    for w in s.split():
        if w in GENRE_WORDS and w not in p.genre_words:
            p.genre_words.append(w)
            p.genres.append(GENRE_WORDS[w])
            if w in TYPE_WORDS:
                p.kind = TYPE_WORDS[w]
        elif w in TYPE_WORDS:
            p.kind = TYPE_WORDS[w]
        else:
            rest.append(w)
    p.text = " ".join(w for w in rest if w not in FILLER) if (p.has_filters or p.like or p.starring) else " ".join(rest)
    return p


def _filters_q(p):
    q = Q()
    if p.kind:
        q &= Q(type=p.kind)
    if p.year_from:
        movie = Q(type="movie", release_year__gte=p.year_from, release_year__lte=p.year_to)
        tv = Q(type="tv", first_air_date__gte=f"{p.year_from}-01-01", first_air_date__lte=f"{p.year_to}-12-31")
        q &= movie | tv
    for names in p.genres:
        any_of = Q()
        for name in names:
            any_of |= Q(genre__icontains=name)
        q &= any_of
    return q


def _filters_key(p):
    """The filters as data, for the app to word ({"key": "filters", "genres": [...], ...})."""
    key = {"key": "filters", "genres": [GENRE_WORDS[w][0] for w in p.genre_words]}
    if p.year_from:
        key["yearFrom"], key["yearTo"] = p.year_from, p.year_to
    if p.kind:
        key["kind"] = p.kind
    return key


def _describe_filters(p):
    parts = [GENRE_WORDS[w][0] for w in p.genre_words]
    if p.year_from:
        parts.append(f"{p.year_from}s" if p.year_to == p.year_from + 9 and p.year_from % 10 == 0
                     else (str(p.year_from) if p.year_from == p.year_to else f"{p.year_from}-{p.year_to}"))
    if p.kind:
        parts.append("TV show" if p.kind == "tv" else "Movie")
    return " · ".join(parts)


# ---------- typo tolerance: trigram index over popular titles, per process ----------
_fuzzy = {"built": 0.0, "names": {}, "grams": {}}


def _trigrams(s):
    s = f"  {norm(s)} "
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _fuzzy_index():
    if time.time() - _fuzzy["built"] < FUZZY_TTL:
        return _fuzzy
    names, grams = {}, {}
    for tid, title in Title.objects.order_by("-popularity").values_list("id", "title")[:FUZZY_POOL]:
        names[tid] = norm(title)
        for g in _trigrams(title):
            grams.setdefault(g, []).append(tid)
    _fuzzy.update(built=time.time(), names=names, grams=grams)
    return _fuzzy


def fuzzy_title_ids(text, limit=20):
    """Titles whose name is close to text (typos), best first."""
    idx = _fuzzy_index()
    counts = {}
    for g in _trigrams(text):
        for tid in idx["grams"].get(g, ()):
            counts[tid] = counts.get(tid, 0) + 1
    shortlist = sorted(counts, key=counts.get, reverse=True)[:200]
    target = norm(text)
    scored = [(SequenceMatcher(None, target, idx["names"][tid]).ratio(), tid) for tid in shortlist]
    return [tid for ratio, tid in sorted(scored, reverse=True) if ratio >= FUZZY_MIN_RATIO][:limit]


# ---------- search ----------

def search_titles(q, profile=None, kind=None, limit=15, language=None):
    """
    -> [(Title, reason, reason_key)] best first. reason: English sentence ("" for a plain name
    match); reason_key: the same as data for the app to word ({"key": "with", "name": ...}) or None.
    language: app code; titles also match by their translated name in it (TitleTranslation).
    """
    from .models import TitleTranslation
    from reco.models import TitleSimilar  # reco depends on users, not the other way round

    p = parse_query(q)
    if kind in ("movie", "tv"):
        p.kind = kind
    allowed = Title.objects.filter(allowed_titles_q(profile))
    base = allowed.filter(_filters_q(p))
    filters_label = _describe_filters(p)
    filters_key = _filters_key(p) if filters_label else None

    scores = {}  # id -> [score, reason, reason_key]

    def add(ids, score, reason, key=None):
        for rank, tid in enumerate(ids):
            s = score - rank * 0.01  # keep the order of ranked lists
            if tid not in scores or scores[tid][0] < s:
                scores[tid] = [s, reason, key]

    # "like X": titles similar to the best match for X
    if p.like:
        src = _best_title(allowed, p.like)
        if src:
            sim = list(
                TitleSimilar.objects.filter(title=src).order_by("-score").values_list("similar_id", flat=True)[:300]
            )
            keep = set(base.filter(id__in=sim).values_list("id", flat=True))
            add([i for i in sim if i in keep], 70, f"Like {src.title}", {"key": "like", "title_id": src.id, "title": src.title})

    # "with X": actor
    if p.starring:
        _add_actor(add, base, p.starring, 65)

    text = p.text.strip()
    if len(text) >= 2:
        # titles: exact > starts with > contains the phrase > has every word (articles ignored)
        expr = _ft_expr(text)
        name = _name(text)
        if expr:
            matches = _ft(base, "title, original_title", expr)
        else:  # only short words / stopwords ("up", "it"): no FULLTEXT, names starting with it
            matches = base.filter(Q(title__istartswith=text) | Q(original_title__istartswith=text))
        for tid, title, original in matches.order_by("-popularity").values_list("id", "title", "original_title")[:300]:
            t, o = _name(title), _name(original)
            if name in (t, o):
                add([tid], 100, "")
            elif t.startswith(name) or o.startswith(name):
                add([tid], 85, "")
            elif name in t or name in o:
                add([tid], 70, "")
            else:
                add([tid], 50, "")
        # the name in the app's language ("Le Parrain" -> The Godfather)
        if language and language != "en":
            translated = (
                TitleTranslation.objects.filter(language=language, title__in=base)
                .filter(Q(name__istartswith=text) | Q(name__icontains=f" {text}"))
                .values_list("title_id", "name")[:300]
            )
            for tid, tname in translated:
                tn = _name(tname)
                add([tid], 100 if tn == name else (85 if tn.startswith(name) else 70), "")
        if expr:
            # directing outranks appearing in it (documentaries about a director)
            directors = list(_ft(base, "director", expr).order_by("-popularity").values_list("id", "director")[:100])
            for director in dict.fromkeys(d for _, d in directors):
                add([tid for tid, d in directors if d == director], 75, f"Directed by {director}", {"key": "directedBy", "name": director})
            if not p.starring:
                _add_actor(add, base, text, 60)
        kw_ids = list(TitleKeyword.objects.filter(keyword_norm=text).values_list("title_id", flat=True)[:300])
        add(list(base.filter(id__in=kw_ids).values_list("id", flat=True)), 35, f"About {text}", {"key": "about", "text": text})

        # typos: only when the name matches are thin
        if sum(1 for s, *_ in scores.values() if s >= 50) < 3:
            fuzzy = fuzzy_title_ids(text)
            keep = set(base.filter(id__in=fuzzy).values_list("id", flat=True))
            add([i for i in fuzzy if i in keep], 45, "Close match", {"key": "closeMatch"})

    # only filters ("90s crime shows"): best known matching titles. Not when there is text that
    # matched nothing ("qqzzxxw" with the TV Shows filter returned the 60 most popular shows).
    if not scores and not text and p.has_filters and not p.like and not p.starring:
        add(list(base.order_by("-popularity").values_list("id", flat=True)[:limit]), 30, filters_label, filters_key)

    if not scores:
        return []
    titles = {t.id: t for t in Title.objects.filter(id__in=list(scores))}
    ranked = sorted(
        (tid for tid in scores if tid in titles),
        key=lambda tid: scores[tid][0] + math.log1p(titles[tid].popularity or 0),
        reverse=True,
    )
    out = []
    for tid in ranked[:limit]:
        _score, reason, key = scores[tid]
        if not reason and filters_label and text:
            reason, key = filters_label, filters_key
        out.append((titles[tid], reason, key))
    return out


def _best_title(qs, text):
    """Most popular title named text (exact, then starts with, then contains, then typo-tolerant)."""
    text = norm(text)
    for lookup in ("title__iexact", "title__istartswith", "title__icontains"):
        t = qs.filter(**{lookup: text}).order_by("-popularity").first()
        if t:
            return t
    ids = fuzzy_title_ids(text, limit=5)
    return qs.filter(id__in=ids).order_by("-popularity").first() if ids else None


def _add_actor(add, base, name, score, max_actors=3):
    """Titles of the actors matching name (full name or just the last name), best known first."""
    expr = _ft_expr(name)
    if not expr:
        return
    rows = list(_ft(Actor.objects.all(), "name", expr).values_list("title_id", "name")[:1000])
    if not rows:
        return
    keep = set(base.filter(id__in=[tid for tid, _ in rows]).values_list("id", flat=True))
    by_actor = {}
    for tid, actor in rows:
        if tid in keep:
            by_actor.setdefault(actor, []).append(tid)
    # several people share a last name: the one in the most titles is the one people mean
    for actor in sorted(by_actor, key=lambda a: len(by_actor[a]), reverse=True)[:max_actors]:
        add(by_actor[actor], score, f"With {actor}", {"key": "with", "name": actor})
