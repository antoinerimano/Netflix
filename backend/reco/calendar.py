# reco/calendar.py
"""
Upcoming episodes of "your shows" (/calendar in the app).

  GET /api/calendar/?profileId=..  ->
    {
      "today": "2026-11-06",
      "tracked": 5,                              # how many shows the profile follows / lists / watches
      "recent":   [episode, ...],                # aired in the RECENT_DAYS days before today, newest first
      "upcoming": [episode, ...],                # today and the next CALENDAR_DAYS days, soonest first
      "suggestions": [show, ...],                # popular shows with an episode coming, not tracked yet
    }
    episode = {"id", "episode_number", "season", "name", "air_date", "still", "show": {...}, "reason"}
    show    = {"id", "type", "title", "poster", "landscape_image", "following", "next": {season, episode, air_date}}

"Your shows": the ones it follows ("Notify me"), has in My List, or watched lately. Their episodes
come from the 3-hourly sync (sync_tmdb_daily_episodes also refreshes these shows: see
tracked_tmdb_ids). The age limit of the profile applies. Names are translated by the API's renderer.
"""
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.maturity import allowed_titles_q
from users.models import Episode, Profile, Title

from .models import MyListItem, ShowFollow, WatchProgress

CALENDAR_DAYS = 30
RECENT_DAYS = 7
WATCHING_DAYS = 180          # a show watched in the last 6 months is still "yours"
SUGGESTIONS = 12
STILL_BASE = "https://image.tmdb.org/t/p/original"

REASONS = ("follow", "list", "watching")  # strongest first


def tracked_shows(profile_ids):
    """{profile id: {show id: reason}} for the given profiles (one query per source)."""
    out = {pid: {} for pid in profile_ids}
    since = timezone.now() - timedelta(days=WATCHING_DAYS)
    sources = (
        ("follow", ShowFollow.objects.filter(profile_id__in=profile_ids)),
        ("list", MyListItem.objects.filter(profile_id__in=profile_ids, title__type="tv")),
        ("watching", WatchProgress.objects.filter(profile_id__in=profile_ids, title__type="tv", updated_at__gte=since)),
    )
    for reason, qs in sources:
        for pid, tid in qs.values_list("profile_id", "title_id"):
            out[pid].setdefault(tid, reason)  # sources are in strength order: the first one wins
    return out


def tracked_tmdb_ids():
    """TMDB ids of every show someone tracks and that may still air (for the episode sync)."""
    show_ids = set()
    for shows in tracked_shows(list(Profile.objects.values_list("id", flat=True))).values():
        show_ids.update(shows)
    return list(
        Title.objects.filter(id__in=show_ids, type="tv").exclude(tmdb_id__isnull=True)
        .exclude(status__in=["Ended", "Canceled"]).values_list("tmdb_id", flat=True)
    )


def _show(t):
    return {"id": t.id, "type": "tv", "title": t.title, "poster": t.poster, "landscape_image": t.landscape_image}


def _episodes(show_ids, start, end, newest_first=False):
    qs = (
        Episode.objects.filter(season__tv_id__in=show_ids, air_date__gte=start, air_date__lte=end)
        .exclude(season__season_number=0)  # specials: often placeholder dates
        .select_related("season", "season__tv")
        .order_by(*(("-air_date", "-season__season_number", "-episode_number") if newest_first
                    else ("air_date", "season__season_number", "episode_number")))
    )
    return list(qs[:300])


def _episode(e, reason):
    return {
        "id": e.id,
        "episode_number": e.episode_number,
        "season": e.season.season_number,
        "name": e.name,
        "air_date": e.air_date.isoformat(),
        "still": f"{STILL_BASE}{e.still_path}" if e.still_path else "",
        "show": _show(e.season.tv),
        "reason": reason,
    }


def suggestions(profile, exclude, today, k=SUGGESTIONS):
    """Popular shows with an episode in the coming days that the profile doesn't track yet."""
    nexts = {}
    for tv_id, season, number, air in (
        Episode.objects.filter(air_date__gt=today, air_date__lte=today + timedelta(days=CALENDAR_DAYS))
        .exclude(season__season_number=0).exclude(season__tv_id__in=exclude)
        .order_by("air_date", "season__season_number", "episode_number")
        .values_list("season__tv_id", "season__season_number", "episode_number", "air_date")
    ):
        nexts.setdefault(tv_id, (season, number, air))
    shows = (
        Title.objects.filter(id__in=list(nexts), type="tv").filter(allowed_titles_q(profile))
        .only("id", "title", "poster", "landscape_image", "popularity").order_by("-popularity")[:k]
    )
    out = []
    for t in shows:
        season, number, air = nexts[t.id]
        out.append({**_show(t), "following": False, "next": {"season": season, "episode": number, "air_date": air.isoformat()}})
    return out


class CalendarView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        today = timezone.localdate()
        tracked = tracked_shows([profile.id])[profile.id]
        allowed = set(Title.objects.filter(id__in=list(tracked)).filter(allowed_titles_q(profile)).values_list("id", flat=True))
        tracked = {tid: why for tid, why in tracked.items() if tid in allowed}

        recent = _episodes(tracked, today - timedelta(days=RECENT_DAYS), today - timedelta(days=1), newest_first=True)
        upcoming = _episodes(tracked, today, today + timedelta(days=CALENDAR_DAYS))
        return Response({
            "today": today.isoformat(),
            "tracked": len(tracked),
            "recent": [_episode(e, tracked[e.season.tv_id]) for e in recent],
            "upcoming": [_episode(e, tracked[e.season.tv_id]) for e in upcoming],
            "suggestions": suggestions(profile, set(tracked), today),
        })
