# users/i18n.py
"""
The app's languages on the server side.

- The client sends its language as Accept-Language (frontend api/http.js); Django's LocaleMiddleware
  activates it for the request: gettext messages, emails, and catalog texts (localize.py).
- Codes are the frontend's ("en", "fr", "zh"...); Django names Simplified Chinese "zh-hans"
  (settings.LANGUAGES), to_app_language() maps any code back.
- Jobs without a request (new episode emails) use the profile's language_preference:
  with language_of(profile): ...
"""
from contextlib import contextmanager

from django.conf import settings
from django.utils import translation

APP_LANGUAGES = ("en", "fr", "es", "de", "it", "ja", "zh", "hi", "pt", "ru", "bn")
DEFAULT_LANGUAGE = "en"

# older profiles / other conventions -> ours
_ALIASES = {"jp": "ja", "pt-br": "pt", "pt-pt": "pt", "cn": "zh", "zh-hans": "zh", "zh-cn": "zh", "zh-sg": "zh", "zh-hant": "zh", "zh-tw": "zh", "zh-hk": "zh"}
# ours -> Django's (settings.LANGUAGES / locale/<dir>)
_DJANGO_CODES = {"zh": "zh-hans", "pt": "pt-br"}  # Brazilian Portuguese: most speakers
# ours -> TMDB's language parameter / translation iso codes
TMDB_CODES = {"en": "en-US", "fr": "fr-FR", "es": "es-ES", "de": "de-DE", "it": "it-IT", "ja": "ja-JP", "zh": "zh-CN",
              "hi": "hi-IN", "pt": "pt-BR", "ru": "ru-RU", "bn": "bn-BD"}


def to_app_language(code, default=None):
    """'fr-CA' -> 'fr', 'zh-hans' -> 'zh', 'jp' -> 'ja', unknown -> default."""
    if not code:
        return default
    c = str(code).strip().lower().replace("_", "-")
    c = _ALIASES.get(c, c)
    if c in APP_LANGUAGES:
        return c
    base = _ALIASES.get(c.split("-")[0], c.split("-")[0])
    return base if base in APP_LANGUAGES else default


def to_django_language(code):
    lang = to_app_language(code, DEFAULT_LANGUAGE)
    return _DJANGO_CODES.get(lang, lang)


def current_language():
    """The language of the request being served (LocaleMiddleware), as an app code."""
    return to_app_language(translation.get_language(), DEFAULT_LANGUAGE)


@contextmanager
def language_of(code):
    """Render gettext / templates in this language (emails sent outside a request)."""
    with translation.override(to_django_language(code or settings.LANGUAGE_CODE)):
        yield
