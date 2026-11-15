# users/tmdb_related.py
"""
Free TMDB data the catalog didn't use yet (roadmap 8.8), read from one call per title:
  GET /{movie|tv}/{id}?append_to_response=recommendations,similar,alternative_titles
- recommendations + similar: TMDB's own "people who watched this also watched" (recommendations,
  built from real viewing) then "same genres / keywords" (similar). Saved as reco.TitleSimilar rows
  with model_name "tmdb", best first, next to the embeddings' rows (build_embeddings), and mixed
  with them in "More like this" (users/views.py similar).
- alternative_titles: other names (local release titles) -> TitleAltName, so search finds them.
manage.py sync_tmdb_related fetches them (nightly, most popular first, refreshed every 60 days).
"""
from .search import _name

MODEL_NAME = "tmdb"      # reco.TitleSimilar.model_name of these rows
MAX_RELATED = 30         # recommendations first, then similar
MAX_ALT_NAMES = 30


def related_tmdb_ids(data):
    """TMDB ids, best first: recommendations, then similar, no repeats."""
    out = []
    for key in ("recommendations", "similar"):
        for item in ((data.get(key) or {}).get("results") or []):
            tid = item.get("id")
            if isinstance(tid, int) and tid not in out and tid != data.get("id"):
                out.append(tid)
    return out[:MAX_RELATED]


def alt_names(data, title, original_title=""):
    """[(name, name_norm, country)] other than the names the title already has, no repeats.
    Movies send alternative_titles.titles, shows alternative_titles.results."""
    block = data.get("alternative_titles") or {}
    items = block.get("titles") or block.get("results") or []
    known = {_name(title), _name(original_title)}
    out, seen = [], set()
    for item in items:
        name = " ".join(str(item.get("title") or "").split())[:255]
        key = _name(name)[:255]
        if not key or key in known or key in seen:
            continue
        seen.add(key)
        out.append((name, key, str(item.get("iso_3166_1") or "")[:2]))
    return out[:MAX_ALT_NAMES]


def interleave(first, second):
    """first[0], second[0], first[1], second[1]... without repeats (either list may be empty)."""
    out, seen = [], set()
    for i in range(max(len(first), len(second))):
        for ids in (first, second):
            if i < len(ids) and ids[i] not in seen:
                seen.add(ids[i])
                out.append(ids[i])
    return out


def scores(n):
    """Scores for n related titles in order: 1.0 down, so best first (order_by -score)."""
    return [round(1.0 - i / 100, 4) for i in range(n)]
