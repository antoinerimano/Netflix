# users/localize.py
"""
Catalog texts in the language of the request (titles, synopses, taglines, episode names).

The database keeps TMDB's English texts on Title / Episode; other languages are rows of
TitleTranslation / EpisodeTranslation (sync_tmdb_translations). Rather than every view and every
cached payload (home snapshots, search cache) knowing about languages, the API's JSON renderer
(LocalizedJSONRenderer, settings.REST_FRAMEWORK) swaps the translations into the response on the
way out, with two queries at most:

  - title-like objects  {"id", "title", + "type" | "poster" | "landscape_image" | "description"}
        title <- name, description <- overview, tagline <- tagline
  - episode-like objects {"id", "episode_number", "name" | "overview"}
        name, overview
  - notifications       {"title_id", "show"}: show <- name

Anything without a translation stays in English. English requests are untouched (no query).
Editing tools must see the stored texts: they send "X-Original-Content: 1" (and only GET / HEAD
responses are ever localized), so a translated title can't be saved over the English one.
"""
import copy

from rest_framework.renderers import JSONRenderer

from .i18n import DEFAULT_LANGUAGE, current_language

ORIGINAL_HEADER = "HTTP_X_ORIGINAL_CONTENT"
_TITLE_HINTS = ("type", "poster", "landscape_image", "description")


def _is_title(d):
    return "id" in d and "title" in d and isinstance(d.get("title"), str) and any(k in d for k in _TITLE_HINTS)


def _is_episode(d):
    return "id" in d and "episode_number" in d and ("name" in d or "overview" in d)


def _walk(node, titles, episodes, notifs):
    if isinstance(node, dict):
        if _is_title(node):
            titles.append(node)
        elif _is_episode(node):
            episodes.append(node)
        elif "title_id" in node and "show" in node:
            notifs.append(node)
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk(value, titles, episodes, notifs)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, (dict, list)):
                _walk(value, titles, episodes, notifs)


def title_names(ids, lang):
    """{title id: translated name} for the ids that have one in lang."""
    from .models import TitleTranslation

    if not ids or lang == DEFAULT_LANGUAGE:
        return {}
    return dict(
        TitleTranslation.objects.filter(title_id__in=set(ids), language=lang)
        .exclude(name="")
        .values_list("title_id", "name")
    )


def localize_payload(data, lang):
    """data with the catalog texts of lang swapped in (in place; returns data)."""
    from .models import EpisodeTranslation, TitleTranslation

    if lang == DEFAULT_LANGUAGE or not isinstance(data, (dict, list)):
        return data
    titles, episodes, notifs = [], [], []
    _walk(data, titles, episodes, notifs)

    title_ids = {t["id"] for t in titles if isinstance(t["id"], int)} | {n["title_id"] for n in notifs if isinstance(n["title_id"], int)}
    if title_ids:
        rows = {
            r["title_id"]: r
            for r in TitleTranslation.objects.filter(title_id__in=title_ids, language=lang).values(
                "title_id", "name", "overview", "tagline"
            )
        }
        for t in titles:
            r = rows.get(t["id"])
            if not r:
                continue
            if r["name"]:
                t["title"] = r["name"]
            if r["overview"] and "description" in t:
                t["description"] = r["overview"]
            if r["tagline"] and "tagline" in t:
                t["tagline"] = r["tagline"]
        for n in notifs:
            r = rows.get(n["title_id"])
            if r and r["name"]:
                n["show"] = r["name"]

    episode_ids = {e["id"] for e in episodes if isinstance(e["id"], int)}
    if episode_ids:
        rows = {
            r["episode_id"]: r
            for r in EpisodeTranslation.objects.filter(episode_id__in=episode_ids, language=lang).values(
                "episode_id", "name", "overview"
            )
        }
        for e in episodes:
            r = rows.get(e["id"])
            if not r:
                continue
            if r["name"] and "name" in e:
                e["name"] = r["name"]
            if r["overview"] and "overview" in e:
                e["overview"] = r["overview"]
    return data


def wants_localized(request):
    return (
        request is not None
        and request.method in ("GET", "HEAD")
        and request.META.get(ORIGINAL_HEADER) != "1"
        and current_language() != DEFAULT_LANGUAGE
    )


class LocalizedJSONRenderer(JSONRenderer):
    """JSONRenderer + the catalog texts of the request's language (see the module docstring)."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        request = (renderer_context or {}).get("request")
        if data is not None and wants_localized(request):
            # a copy: views may hand out objects that live on (in-process caches)
            data = localize_payload(copy.deepcopy(data), current_language())
        return super().render(data, accepted_media_type, renderer_context)
