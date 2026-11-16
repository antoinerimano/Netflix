# users/ai_translate.py
"""
Overviews TMDB doesn't have in a language the site's profiles use (roadmap 8.6, the lean way):
Claude translates the English overview, as Message Batches (manage.py translate_titles).

- TMDB first: sync_tmdb_translations (every 3 hours) is the source; this only fills the gaps it
  leaves, and TMDB's own text replaces Claude's as soon as TMDB has one (machine_translated).
- Only languages at least one profile uses (languages_in_use): on 2026-11-16 that meant Spanish,
  French, German and Chinese (~540 gaps among well-known titles, ~US$0.07 once), not the ~48,000
  gaps in Japanese / Hindi / Arabic / Bengali / Urdu that no profile reads. A profile switching
  to a language makes the job start on it by itself.
- Well-known titles only (MIN_VOTES), most popular first, within tonight's share of the
  background jobs' AI budget.
"""
from django.db.models import Exists, OuterRef

from .i18n import to_app_language

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 2048
DEFAULT_LANGUAGE = "en"
LANGUAGE_NAMES = {
    "fr": "French", "es": "Spanish", "de": "German", "it": "Italian", "ja": "Japanese", "zh": "Simplified Chinese",
    "hi": "Hindi", "pt": "Brazilian Portuguese", "ru": "Russian", "bn": "Bengali", "ar": "Arabic", "ur": "Urdu",
}
MAX_GROWTH = 4  # a "translation" more than 4x the English one's length is not one: dropped
MIN_VOTES = 300  # well-known titles only (the "What to watch?" bar): the ones people actually open;
                 # the whole catalog would be ~45,000 overviews a language, mostly never read

SYSTEM = """You translate movie and TV show synopses for a streaming site into {language}.
- Translate the synopsis faithfully: the same meaning, the same length, natural {language}.
- Add nothing: no notes, no comments, no quotes around it, no title line.
- Keep the names of people and places as they are, or in their usual {language} form.
Answer with the translated synopsis only."""


def languages_in_use():
    """App languages (not English) at least one profile uses, most used first."""
    from .models import Profile

    counts = {}
    for raw in Profile.objects.values_list("language_preference", flat=True):
        lang = to_app_language(raw, DEFAULT_LANGUAGE)
        if lang != DEFAULT_LANGUAGE and lang in LANGUAGE_NAMES:
            counts[lang] = counts.get(lang, 0) + 1
    return sorted(counts, key=lambda lang: -counts[lang])


def gaps(languages, limit):
    """[(Title, language)]: well-known titles with an English overview and none in that language
    (TMDB's or ours), most popular first, at most limit."""
    from .models import Title, TitleTranslation

    found = []
    for lang in languages:
        has_one = TitleTranslation.objects.filter(title=OuterRef("pk"), language=lang).exclude(overview="")
        for t in (
            Title.objects.filter(vote_count__gte=MIN_VOTES).exclude(description="").filter(~Exists(has_one))
            .order_by("-popularity", "id").only("id", "type", "title", "release_year", "description", "popularity")[:limit]
        ):
            found.append((t, lang))
    found.sort(key=lambda pair: (-(pair[0].popularity or 0), pair[0].id, pair[1]))
    return found[:limit]


def custom_id(title_id, language):
    return f"t{title_id}-{language}"


def request_params(title, language):
    kind = "TV show" if title.type == "tv" else "Movie"
    year = f" ({title.release_year})" if title.release_year else ""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM.format(language=LANGUAGE_NAMES[language]),
        "output_config": {"effort": "low"},
        "messages": [{"role": "user", "content": f'{kind} "{title.title}"{year}\n\nSynopsis:\n{title.description}'}],
    }


def translation(message, english):
    """The translated overview in Claude's answer, "" when it declined, was cut off or doesn't look
    like a translation of `english` (empty, or far longer)."""
    if message.stop_reason != "end_turn":
        return ""
    text = "\n\n".join(b.text.strip() for b in message.content if b.type == "text" and b.text.strip()).strip()
    if not text or len(text) > MAX_GROWTH * max(len(english), 50):
        return ""
    return text
