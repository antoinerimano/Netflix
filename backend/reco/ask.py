# reco/ask.py
"""
"Ask Taurus" (/ask, roadmap 8.10): say what you feel like watching, get 4-6 titles from the
catalog and a few follow-ups to tap.

  POST /api/ask/ {"profileId", "message", "history": [{"message", "reply"}]}
    -> {"reply", "items": [title + minutes], "chips": [3 follow-ups]}
    429 {"code": "ai_budget", "reason"}   a cap is reached (reco/ai_budget.py: US$0.05 a day for
                                          the site, 12 messages a day per user, US$5 a month)
    503 {"code": "ask_unavailable"}       Claude declined, failed, or found nothing usable

How: Claude Haiku 5.5 with ONE read-only tool, find_titles (the catalog, within the profile's age
limit, without what it already watched / rated / turned down, ranked for it like the home page),
up to MAX_ROUNDS searches, then a JSON answer (structured output). Only titles find_titles
returned in this request can be suggested: any other id is dropped, so nothing invented shows.
The viewer's message is just a request: the tool can't change anything.
History: the app sends the last turns back (text only, capped), nothing is stored.
Tests and the end-to-end suite use a scripted fake (settings.AI_FAKE, reco/ask_fake.py).
"""
import json
import logging

from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.maturity import allowed_titles_q, profile_max_level
from users.models import Profile, Title, TVShowExtras

from . import ai_budget
from .recap import LANGUAGE_NAMES
from .tags import MOODS

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"
MAX_TOKENS = 2048
MAX_ROUNDS = 3          # find_titles calls a message may make
MAX_MESSAGE = 300       # characters of the viewer's message
MAX_HISTORY = 4         # earlier turns sent back
TOOL_RESULTS = 12       # titles a search returns to Claude
MIN_SUGGEST, MAX_SUGGEST = 4, 6
MIN_VOTES = 50          # leave out titles almost nobody rated

SYSTEM = """You help one viewer of the streaming site Taurus choose what to watch tonight.
- Search the catalog with find_titles (you may call it up to 3 times, e.g. with other moods or
  genres when the first search is thin). Its results already fit the viewer's age limit and leave
  out what they watched or turned down.
- Suggest {min} to {max} titles, ONLY ids that find_titles returned. Never mention a title it didn't return.
- reply: 1 or 2 short, warm sentences in {language} saying what you picked and why it fits. No list,
  no titles repeated one by one (they are shown as posters), no Markdown.
- chips: 3 short follow-ups in {language} (2 to 4 words) the viewer might tap next, e.g. shorter,
  lighter, a series instead, something newer.
- If nothing fits, say so kindly in reply, give an empty title_ids, and chips that widen the search.
{viewer}"""

TOOL = {
    "name": "find_titles",
    "description": (
        "Search the catalog for movies / TV shows the viewer may watch. Every filter is optional "
        "(null, [] or kind any = no filter). Returns up to 12 titles, best match for this viewer first, with "
        "id, title, type, year, genres, moods, minutes, rating and a short summary."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": ["string", "null"], "description": "free text: a title, actor, director, keyword"},
            "like_title": {"type": ["string", "null"], "description": "titles similar to this one"},
            "kind": {"type": "string", "enum": ["movie", "tv", "any"], "description": "any = both"},
            "moods": {"type": "array", "items": {"type": "string", "enum": MOODS},
                      "description": "any of these moods"},
            "genres": {"type": "array", "items": {"type": "string"},
                       "description": "TMDB genres in English, any of them (Comedy, Drama, Animation...)"},
            "max_minutes": {"type": ["integer", "null"], "description": "movies: longest runtime"},
            "year_from": {"type": ["integer", "null"]},
            "year_to": {"type": ["integer", "null"]},
        },
        "required": ["query", "like_title", "kind", "moods", "genres", "max_minutes", "year_from", "year_to"],
        "additionalProperties": False,
    },
}

ANSWER = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "title_ids": {"type": "array", "items": {"type": "integer"}},
        "chips": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reply", "title_ids", "chips"],
    "additionalProperties": False,
}


def profile_language(profile):
    """The app language the answer is written in ("en" when unknown)."""
    language = (profile.language_preference or "en").split("-")[0].lower()
    return language if language in LANGUAGE_NAMES else "en"


def _client():
    if getattr(settings, "AI_FAKE", False):
        from .ask_fake import FakeClient

        return FakeClient()
    import anthropic

    return anthropic.Anthropic(timeout=60.0, max_retries=1)


# ---------- the tool ----------

def find_titles(profile, args):
    """find_titles for this profile: [{id, title, ...}], best for it first."""
    from users.search import _best_title, search_titles

    from .models import TitleSimilar
    from .pick import _seen, ranked
    from .views import _released_titles

    qs = (
        _released_titles().exclude(poster="").filter(vote_count__gte=MIN_VOTES)
        .filter(allowed_titles_q(profile)).exclude(id__in=_seen(profile.id))
    )
    kind = args.get("kind")
    if kind in ("movie", "tv"):
        qs = qs.filter(type=kind)
    if args.get("query"):
        ids = [t.id for t, *_ in search_titles(args["query"][:100], profile=profile, kind=kind, limit=60)]
        qs = qs.filter(id__in=ids)
    if args.get("like_title"):
        src = _best_title(Title.objects.filter(allowed_titles_q(profile)), args["like_title"][:100])
        sim = list(TitleSimilar.objects.filter(title=src).values_list("similar_id", flat=True)[:200]) if src else []
        qs = qs.filter(id__in=sim)
    moods = [m for m in args.get("moods") or [] if m in MOODS]
    if moods:
        q = Q()
        for m in moods:
            q |= Q(tags__moods__contains=f",{m},")
        qs = qs.filter(q)
    genres = [g for g in args.get("genres") or [] if isinstance(g, str) and g.strip()][:5]
    if genres:
        q = Q()
        for g in genres:
            q |= Q(genre__icontains=g.strip()[:40])
        qs = qs.filter(q)
    if args.get("max_minutes"):
        qs = qs.filter(Q(type="tv") | Q(runtime_minutes__lte=args["max_minutes"], runtime_minutes__gte=40))
    if args.get("year_from"):
        qs = qs.filter(release_year__gte=args["year_from"])
    if args.get("year_to"):
        qs = qs.filter(release_year__lte=args["year_to"])

    titles = list(qs.select_related("tags").order_by("-popularity")[:60])
    best = [t for t, _ in ranked(profile, [(t, None) for t in titles])][:TOOL_RESULTS]
    episode = dict(TVShowExtras.objects.filter(title_id__in=[t.id for t in best if t.type == "tv"])
                   .values_list("title_id", "episode_run_time"))
    out = []
    for t in best:
        rts = episode.get(t.id) or []
        tags = getattr(t, "tags", None)  # untagged: the reverse lookup raises, getattr gives None
        out.append({
            "id": t.id, "title": t.title, "type": t.type, "year": t.release_year, "genres": t.genre,
            "moods": tags.mood_list() if tags else [],
            "minutes": t.runtime_minutes if t.type == "movie" else (int(rts[0]) if rts and rts[0] else None),
            "rating": t.vote_average, "summary": (t.description or "")[:160],
        })
    return out


def _viewer(profile):
    """A few lines about the viewer for the system prompt: age limit, what they watched lately."""
    from .models import WatchEvent

    lines = []
    if profile.is_kids or profile_max_level(profile) is not None:
        lines.append("The viewer is a child or has an age limit: keep it suitable (the search already does).")
    recent = list(
        WatchEvent.objects.filter(profile=profile).order_by("-watched_at")
        .values_list("title__title", flat=True).distinct()[:6]
    )
    if recent:
        lines.append("They watched lately: " + ", ".join(recent) + ".")
    return "\n".join(lines)


# ---------- the conversation ----------

def answer(profile, message, history):
    """{"reply", "title_ids", "chips"} or None. Every API call's cost is recorded."""
    from types import SimpleNamespace

    language = LANGUAGE_NAMES.get(profile_language(profile), "English")
    system = SYSTEM.format(min=MIN_SUGGEST, max=MAX_SUGGEST, language=language, viewer=_viewer(profile))
    messages = []
    for turn in (history or [])[-MAX_HISTORY:]:
        if isinstance(turn, dict) and turn.get("message") and turn.get("reply"):
            messages.append({"role": "user", "content": str(turn["message"])[:MAX_MESSAGE]})
            messages.append({"role": "assistant", "content": str(turn["reply"])[:600]})
    messages.append({"role": "user", "content": message[:MAX_MESSAGE]})

    client = _client()
    offered = set()
    spent = SimpleNamespace(input_tokens=0, output_tokens=0, usd=0.0)
    result = None
    try:
        for round_ in range(MAX_ROUNDS + 1):
            tools_left = round_ < MAX_ROUNDS
            msg = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=messages,
                tools=[TOOL], tool_choice={"type": "auto"} if tools_left else {"type": "none"},
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": ANSWER}},
            )
            spent.input_tokens += msg.usage.input_tokens or 0
            spent.output_tokens += msg.usage.output_tokens or 0
            spent.usd += ai_budget.cost(msg.usage, MODEL)
            if msg.stop_reason == "tool_use" and tools_left:
                messages.append({"role": "assistant", "content": msg.content})
                results = []
                for block in msg.content:
                    if block.type != "tool_use":
                        continue
                    found = find_titles(profile, block.input if isinstance(block.input, dict) else {}) \
                        if block.name == TOOL["name"] else []
                    offered.update(t["id"] for t in found)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(found)})
                messages.append({"role": "user", "content": results})
                continue
            if msg.stop_reason == "end_turn":
                text = next((b.text for b in msg.content if b.type == "text"), "")
                data = json.loads(text) if text else None
                if isinstance(data, dict):
                    result = data
            break
    except Exception as exc:  # API error, no key, bad JSON: the page offers to try again
        log.warning("ask failed: %s", exc)
        result = None
    finally:
        if spent.input_tokens or spent.output_tokens:
            ai_budget.record("ask", spent, MODEL, profile=profile, usd=spent.usd)
    if not result:
        return None
    ids = []
    for tid in result.get("title_ids") or []:
        if isinstance(tid, int) and tid in offered and tid not in ids:  # only what the search returned
            ids.append(tid)
    chips = [str(c).strip()[:40] for c in result.get("chips") or [] if str(c).strip()][:3]
    return {"reply": str(result.get("reply") or "").strip()[:600], "title_ids": ids[:MAX_SUGGEST], "chips": chips}


class AskView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = get_object_or_404(Profile, id=request.data.get("profileId"), user=request.user)
        message = str(request.data.get("message") or "").strip()
        if not message:
            return Response({"detail": "Say what you feel like watching.", "code": "empty"}, status=400)
        ok, reason = ai_budget.allowed("ask", profile)
        if not ok:
            return Response({"detail": "Taurus is resting for today.", "code": "ai_budget", "reason": reason}, status=429)
        result = answer(profile, message, request.data.get("history"))
        if result is None:
            return Response({"detail": "No answer right now.", "code": "ask_unavailable"}, status=503)
        titles = {t.id: t for t in Title.objects.filter(id__in=result["title_ids"]).filter(allowed_titles_q(profile))}
        items = [
            {"id": t.id, "type": t.type, "title": t.title, "poster": t.poster, "release_year": t.release_year,
             "rating": t.rating, "minutes": t.runtime_minutes}
            for t in (titles.get(i) for i in result["title_ids"]) if t
        ]
        return Response({"reply": result["reply"], "items": items, "chips": result["chips"]})
