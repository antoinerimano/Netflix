# reco/tags.py
"""
AI title tags: Claude reads a title's TMDB data (name, year, genres, keywords, tagline, overview)
and answers with its moods, themes, pacing and content notes, as JSON that must match SCHEMA.

Sent as Message Batches (half price, done within 24 h) by `manage.py tag_titles`; nothing here
runs while a user waits. Used by:
  - "What to watch?" (reco/pick.py): a tagged title fits a mood when Claude gave it that mood,
    instead of guessing from genres (an untagged one still goes by genres);
  - build_embeddings: moods + themes + pacing join the text each title is encoded from, so
    "More like this", "Because you watched" and natural-language search see them too.
"""
import hashlib
import json

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 2048          # thinking counts toward it; the JSON itself is ~150 tokens
PROMPT_VERSION = "1"       # bump to retag everything after changing the prompt / vocabulary

# The six /pick moods come first (reco/pick.py MOODS uses the same keys); the others only feed
# the embeddings.
MOODS = [
    "funny", "exciting", "scary", "feelgood", "thoughtful", "romantic",
    "dark", "tense", "heartwarming", "inspiring", "mindbending", "cozy", "sad", "quirky",
]
PACING = ["slow", "medium", "fast"]
CONTENT_NOTES = [
    "violence", "gore", "sexual_content", "nudity", "strong_language", "drug_use",
    "self_harm", "animal_harm", "frightening_scenes",
]
MAX_MOODS = 4
MAX_THEMES = 6

SYSTEM = f"""You tag movies and TV shows for a streaming site's recommendations.
From the data given, answer with:
- moods: 1 to {MAX_MOODS} of the allowed moods, the ones a viewer would really feel watching it,
  most fitting first. "funny" only if it is mainly a comedy; "scary" only if it is meant to
  frighten; "feelgood" only if a viewer ends it in a good mood (no bleak or grim stories).
- themes: 2 to {MAX_THEMES} short lowercase phrases (1 to 3 words) for what it is about or its
  kind of story, e.g. "heist", "found family", "time loop", "small town", "revenge".
  No names of characters, actors or places.
- pacing: how fast it moves.
- content_notes: the allowed notes that clearly apply, or an empty list.
Use what you know about the title as well as the data. If you don't know it, go by the data."""

SCHEMA = {
    "type": "object",
    "properties": {
        "moods": {"type": "array", "items": {"type": "string", "enum": MOODS}},
        "themes": {"type": "array", "items": {"type": "string"}},
        "pacing": {"type": "string", "enum": PACING},
        "content_notes": {"type": "array", "items": {"type": "string", "enum": CONTENT_NOTES}},
    },
    "required": ["moods", "themes", "pacing", "content_notes"],
    "additionalProperties": False,
}


def _join(x):
    if not x:
        return ""
    if isinstance(x, str):
        return x
    return ", ".join(str(i) for i in x)


def title_text(t):
    """What Claude is told about a title (and what source_hash covers)."""
    year = t.release_year or (t.first_air_date or "")[:4] or "?"
    lines = [
        f"{'TV show' if t.type == 'tv' else 'Movie'}: {t.title} ({year})",
        f"Original title: {t.original_title}" if t.original_title and t.original_title != t.title else "",
        f"Genres: {t.genre}" if t.genre else "",
        f"Keywords: {_join(t.keywords)[:600]}" if t.keywords else "",
        f"Tagline: {t.tagline}" if t.tagline else "",
        f"Overview: {(t.description or '')[:1500]}" if t.description else "",
    ]
    return "\n".join(line for line in lines if line)


def source_hash(t):
    return hashlib.sha1(f"{PROMPT_VERSION}\n{title_text(t)}".encode()).hexdigest()[:16]


def request_params(t, model=MODEL):
    """Messages API params for one title (a Message Batch request's `params`)."""
    return {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        "messages": [{"role": "user", "content": title_text(t)}],
    }


def custom_id(title_id):
    return f"t{title_id}"


def title_id_of(cid):
    return int(cid[1:]) if cid.startswith("t") and cid[1:].isdigit() else None


def parse(message):
    """A succeeded batch result's message -> clean tags dict, {} for a refusal, None when it can't
    be used (cut off, not JSON): None is retried by the next run, {} isn't."""
    if message.stop_reason == "refusal":
        return {}
    if message.stop_reason != "end_turn":
        return None
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return clean(data)


def clean(data):
    """Keep only the allowed values, in order, without repeats, within the limits."""
    def pick(values, allowed, limit):
        out = []
        for v in values if isinstance(values, list) else []:
            if isinstance(v, str) and v in allowed and v not in out:
                out.append(v)
        return out[:limit]

    themes = []
    for th in data.get("themes") if isinstance(data.get("themes"), list) else []:
        if isinstance(th, str):
            th = " ".join(th.lower().split())[:40]
            if th and th not in themes:
                themes.append(th)
    pacing = data.get("pacing")
    return {
        "moods": pick(data.get("moods"), MOODS, MAX_MOODS),
        "themes": themes[:MAX_THEMES],
        "pacing": pacing if pacing in PACING else "",
        "content_notes": pick(data.get("content_notes"), CONTENT_NOTES, len(CONTENT_NOTES)),
    }


def as_fields(tags):
    """Clean tags dict -> TitleTags field values (moods / notes stored ",a,b," for LIKE filters)."""
    def wrap(values):
        return f",{','.join(values)}," if values else ""

    return {
        "moods": wrap(tags.get("moods") or []),
        "themes": tags.get("themes") or [],
        "pacing": tags.get("pacing") or "",
        "content_notes": wrap(tags.get("content_notes") or []),
    }


def embedding_text(tags_obj):
    """The part build_embeddings adds to a title's text ("" when untagged)."""
    if tags_obj is None:
        return ""
    parts = [" ".join(tags_obj.mood_list()), ", ".join(tags_obj.themes or [])]
    if tags_obj.pacing:
        parts.append(f"{tags_obj.pacing} paced")
    return " | ".join(p for p in parts if p)
