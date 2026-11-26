"""
Anime and K-drama (ROADMAP 9.5): which titles are in these sections, from the TMDB data the syncs
already store (no new TMDB call, no AI):

  anime   genre Animation, and Japanese (original language "ja"), or TMDB's keyword "anime"
          (id 210024: Japanese-style animation made elsewhere), or made in Japan when TMDB gave
          no original language. Movies and shows.
  kdrama  a show (not a movie) in the Drama genre, Korean (original language "ko", or made in
          South Korea when TMDB gave no original language), not animated.

Title.section keeps the answer (indexed: the browse pages' ?section= filter and the home rows are
one quick query). Title.save() works it out again; manage.py rebuild_title_indexes does it for
the titles the syncs wrote without save() (bulk writes); migration users 0033 filled it once.
"""
import json

from .countries import country_code

ANIME, KDRAMA = "anime", "kdrama"
SECTIONS = (ANIME, KDRAMA)
# the fields title_section() reads (Title.save(update_fields=...) with one of them: section too)
SOURCE_FIELDS = ("type", "genre", "original_language", "production_countries", "keywords")


def _items(value):
    """JSONField-ish (list, JSON text, comma-separated text) -> list."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    text = str(value).strip()
    if text[:1] in "[{":
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else [parsed]
        except ValueError:
            pass
    return [p.strip() for p in text.split(",") if p.strip()]


def _genres(genre):
    return {g.strip().casefold() for g in str(genre or "").split(",") if g.strip()}


def _keywords(keywords):
    out = set()
    for k in _items(keywords):
        name = k.get("name") if isinstance(k, dict) else k
        if name:
            out.add(str(name).strip().casefold())
    return out


def _countries(countries):
    return {c for c in (country_code(x) for x in _items(countries)) if c}


def title_section(kind, genre, original_language, production_countries=(), keywords=()):
    """"anime" / "kdrama" / "" for a title's TMDB data."""
    genres = _genres(genre)
    lang = str(original_language or "").strip().lower()
    animated = "animation" in genres
    if animated:
        if lang == "ja" or "anime" in _keywords(keywords):
            return ANIME
        if not lang and "JP" in _countries(production_countries):
            return ANIME
        return ""
    if kind == "tv" and "drama" in genres:
        if lang == "ko" or (not lang and "KR" in _countries(production_countries)):
            return KDRAMA
    return ""


def section_of(title):
    """title_section() of a Title (or any object with its fields)."""
    return title_section(
        getattr(title, "type", ""), getattr(title, "genre", ""), getattr(title, "original_language", ""),
        getattr(title, "production_countries", None), getattr(title, "keywords", None),
    )
