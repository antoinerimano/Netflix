# reco/recap.py
"""
"Catch me up" on a show page: a short, spoiler-free recap of what the profile has already seen,
written by Claude from the episodes' TMDB summaries.

  GET /api/recap/?profileId=..&titleId=..&peek=1
      -> {"available": bool, "season", "episode"}      no Claude call: is there anything to recap?
  GET /api/recap/?profileId=..&titleId=..
      -> {"available": true, "season", "episode", "text", "cached"}

Spoiler-free: the recap covers every episode BEFORE the one the profile is at (where Continue
watching would resume, or the furthest episode in its history), never that one or later. On
season 1 episode 1 there is nothing to recap: available false.
Written in the profile's language, once per show + episode + language and kept (ShowRecap): every
profile at the same point gets the same text. Writing one takes a few seconds and costs about
US$0.001 (Claude Haiku 5.5); only those count toward the "recap" throttle, kept ones don't.
"""
import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from users.maturity import allowed_titles_q
from users.models import Episode, Profile, Season, Title

from .models import ShowRecap, WatchEvent, WatchProgress

log = logging.getLogger(__name__)

MODEL = getattr(settings, "RECAP_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 4096                # thinking counts toward it; a recap is ~300 words
DETAILED_SEASONS = 2             # the last seasons seen are told episode by episode, older ones in brief
MAX_EPISODES = 40                # at most this many episode summaries are sent
OVERVIEW_CHARS = 600
LANGUAGE_NAMES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German", "it": "Italian", "ja": "Japanese",
    "zh": "Simplified Chinese", "hi": "Hindi", "pt": "Brazilian Portuguese", "ru": "Russian", "bn": "Bengali",
    "ar": "Arabic", "ur": "Urdu",
}

SYSTEM = """You write "previously on" recaps for a streaming site, so a viewer can pick a show back up.
You get the summaries of the episodes the viewer has ALREADY watched, oldest first. Write the recap
from them only: never mention anything that happens after the last one, never guess what comes
next, and don't use what you may know about later episodes.
- 120 to 300 words, in short paragraphs (one per season, the most recent one in the most detail),
  separated by a blank line. Plain text: no headings, lists, bold or emoji.
- Say where the main characters stand at the end of the last episode: that is where the viewer resumes.
- Write in {language}. Keep the names of characters, places and the show as they are."""


class RecapThrottle(UserRateThrottle):
    scope = "recap"


def resume_point(profile, title):
    """(season, episode) the profile is at in this show, or None: the furthest of Continue
    watching and the watch history (specials, season 0, don't count)."""
    points = []
    wp = WatchProgress.objects.filter(profile=profile, title=title).first()
    if wp and wp.season_number and wp.episode_number:
        points.append((wp.season_number, wp.episode_number))
    points += [
        (s, e) for s, e in WatchEvent.objects.filter(profile=profile, title=title, season_number__gt=0, episode_number__gt=0)
        .values_list("season_number", "episode_number")
    ]
    return max(points) if points else None


def seen_episodes(title, season, episode):
    """Episodes before (season, episode), oldest first, as (season, number, name, overview)."""
    eps = (
        Episode.objects.filter(season__tv=title, season__season_number__gt=0, season__season_number__lte=season)
        .exclude(season__season_number=season, episode_number__gte=episode)
        .order_by("season__season_number", "episode_number")
        .values_list("season__season_number", "episode_number", "name", "overview")
    )
    return [e for e in eps if (e[3] or "").strip()]


def prompt_text(title, season, episode):
    """What Claude is told, or "" when there is nothing to tell."""
    eps = seen_episodes(title, season, episode)
    if not eps:
        return ""
    seasons_seen = sorted({s for s, *_ in eps})
    detailed = set(seasons_seen[-DETAILED_SEASONS:])
    lines = [f"Show: {title.title}" + (f" ({title.release_year})" if title.release_year else "")]
    if title.description:
        lines.append(f"About the show: {title.description[:OVERVIEW_CHARS]}")

    # older seasons: TMDB's season summary when there is one, else their first episodes, briefly
    season_overviews = dict(
        Season.objects.filter(tv=title, season_number__in=seasons_seen).values_list("season_number", "overview")
    )
    for s in seasons_seen:
        if s in detailed:
            continue
        brief = (season_overviews.get(s) or "").strip()
        if not brief:
            brief = " ".join(o.strip() for ss, _, _, o in eps if ss == s)
        lines.append(f"\nSeason {s} (in brief): {brief[:OVERVIEW_CHARS * 2]}")

    recent = [e for e in eps if e[0] in detailed][-MAX_EPISODES:]
    current = None
    for s, n, name, overview in recent:
        if s != current:
            lines.append(f"\nSeason {s}:")
            current = s
        lines.append(f"S{s}E{n} {name}: {overview.strip()[:OVERVIEW_CHARS]}")
    lines.append(f"\nThe viewer resumes at season {season}, episode {episode}: recap everything above, nothing after.")
    return "\n".join(lines)


def _client():
    import anthropic

    return anthropic.Anthropic(timeout=60.0, max_retries=1)


def write_recap(title, season, episode, language):
    """Claude's recap text, "" when it declined or can't be reached."""
    text = prompt_text(title, season, episode)
    if not text:
        return ""
    import anthropic

    try:
        msg = _client().messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM.format(language=LANGUAGE_NAMES.get(language, "English")),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": text}],
        )
    except anthropic.APIError as exc:  # no key, rate limited, down...: the page says try again later
        log.warning("recap for title %s failed: %s", title.id, exc)
        return ""
    if msg.stop_reason != "end_turn":  # refusal, or cut off
        return ""
    return "\n\n".join(b.text.strip() for b in msg.content if b.type == "text" and b.text.strip())


class RecapView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        title = get_object_or_404(
            Title.objects.filter(allowed_titles_q(profile), type="tv"), id=request.query_params.get("titleId")
        )
        point = resume_point(profile, title)
        if point is None or point <= (1, 1):
            return Response({"available": False})
        season, episode = point
        if not seen_episodes(title, season, episode):  # no summaries to go on
            return Response({"available": False})
        out = {"available": True, "season": season, "episode": episode}
        if request.query_params.get("peek"):
            return Response(out)

        language = (profile.language_preference or "en").split("-")[0].lower()
        if language not in LANGUAGE_NAMES:
            language = "en"
        kept = ShowRecap.objects.filter(title=title, season=season, episode=episode, language=language).first()
        if kept:
            return Response({**out, "text": kept.text, "cached": True})

        throttle = RecapThrottle()
        if not throttle.allow_request(request, self):
            return Response({"detail": "Too many recaps, try again later.", "code": "recap_throttled"}, status=429)
        text = write_recap(title, season, episode, language)
        if not text:
            return Response({"detail": "The recap can't be written right now.", "code": "recap_unavailable"}, status=503)
        ShowRecap.objects.update_or_create(
            title=title, season=season, episode=episode, language=language,
            defaults={"text": text, "model_name": MODEL},
        )
        return Response({**out, "text": text, "cached": False})
