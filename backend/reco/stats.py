# reco/stats.py
"""
"Your year" (/stats in the app): a profile's watching, for one year, from its watch history.

  GET /api/stats/?profileId=..&year=2026 ->
    {
      "year": 2026, "years": [2026, 2025],          # years with history, newest first
      "minutes": 5230,                              # estimated: each movie / episode at its runtime
      "titles": 41, "movies": 17, "shows": 24, "episodes": 160, "days": 63,
      "longest_streak": {"days": 9, "from": "2026-03-02", "to": "2026-03-10"} | null,
      "current_streak": 3,                          # days in a row up to today (or yesterday)
      "months": [minutes per month, 12 of them],
      "top_genres": [{"genre": "Drama", "minutes": 900, "share": 0.31}],   # shares of the time: they add up to 1
      "top_titles": [{"title": {...}, "minutes": 600, "episodes": 12}],
      "top_actors": [{"name", "tmdb_id", "photo", "titles", "minutes"}],
      "first": {"title": {...}, "date": "2026-01-03"} | null,
    }

Minutes are estimates: an entry is "watched this movie / episode that day" (reco/history.py), so
it counts as the runtime (movie runtime, episode runtime, else the show's usual length, else
EPISODE_MINUTES / MOVIE_MINUTES). Actors: the five first-billed of each title.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.maturity import allowed_titles_q
from users.models import Actor, Episode, Profile, TVShowExtras

from .models import WatchEvent

MOVIE_MINUTES = 100
EPISODE_MINUTES = 45
TOP = 6
LEADS = 5          # first-billed actors of a title that count
PHOTO_BASE = "https://image.tmdb.org/t/p/original"


def _runtimes(events):
    """{event id: minutes}"""
    ep_keys = {(e.title_id, e.season_number, e.episode_number) for e in events if e.title.type == "tv" and e.episode_number}
    ep_minutes = {}
    if ep_keys:
        tv_ids = {k[0] for k in ep_keys}
        for tid, s, n, rt in Episode.objects.filter(season__tv_id__in=tv_ids).values_list(
            "season__tv_id", "season__season_number", "episode_number", "runtime"
        ):
            if (tid, s, n) in ep_keys and rt:
                ep_minutes[(tid, s, n)] = rt
    usual = {}
    for tid, rts in TVShowExtras.objects.filter(title_id__in={e.title_id for e in events if e.title.type == "tv"}).values_list(
        "title_id", "episode_run_time"
    ):
        if rts:
            usual[tid] = int(rts[0]) or EPISODE_MINUTES
    out = {}
    for e in events:
        if e.title.type == "movie":
            out[e.id] = e.title.runtime_minutes or MOVIE_MINUTES
        else:
            out[e.id] = ep_minutes.get((e.title_id, e.season_number, e.episode_number)) or usual.get(e.title_id) or EPISODE_MINUTES
    return out


def _streaks(days, today):
    """(longest run of consecutive days as (n, first, last) or None, current run ending today / yesterday)"""
    days = sorted(set(days))
    best, run_start, prev = None, None, None
    for d in days:
        if prev is not None and d == prev + timedelta(days=1):
            pass
        else:
            run_start = d
        n = (d - run_start).days + 1
        if best is None or n > best[0]:
            best = (n, run_start, d)
        prev = d
    current = 0
    if days and days[-1] >= today - timedelta(days=1):
        d = days[-1]
        s = set(days)
        while d in s:
            current += 1
            d -= timedelta(days=1)
    return best, current


def _show(t):
    return {"id": t.id, "type": t.type, "title": t.title, "poster": t.poster, "landscape_image": t.landscape_image}


def year_stats(profile, year):
    events = list(
        WatchEvent.objects.filter(profile=profile, watched_on__year=year)
        .filter(allowed_titles_q(profile, prefix="title__"))
        .select_related("title").order_by("watched_at")
    )
    minutes = _runtimes(events)
    by_title = defaultdict(int)
    episodes = defaultdict(set)
    months = [0] * 12
    for e in events:
        by_title[e.title_id] += minutes[e.id]
        months[e.watched_on.month - 1] += minutes[e.id]
        if e.title.type == "tv" and e.episode_number:
            episodes[e.title_id].add((e.season_number, e.episode_number))
    titles = {e.title_id: e.title for e in events}
    total = sum(minutes.values())

    # a title's time is split between its genres: the shares add up to 100%
    genres = Counter()
    for tid, m in by_title.items():
        names = [g.strip() for g in (titles[tid].genre or "").split(",") if g.strip()]
        for g in names:
            genres[g] += m / len(names)

    leads = {tid: list(t.cast or [])[:LEADS] for tid, t in titles.items()}
    actor_minutes, actor_titles, actor_info = Counter(), Counter(), {}
    wanted = {name for names in leads.values() for name in names if isinstance(name, str)}
    for tid, name, tmdb_id, photo in Actor.objects.filter(title_id__in=list(titles), name__in=wanted).values_list(
        "title_id", "name", "tmdb_id", "profile_path"
    ):
        if name not in leads.get(tid, []):
            continue
        key = tmdb_id or name
        actor_minutes[key] += by_title[tid]
        actor_titles[key] += 1
        if key not in actor_info or (photo and not actor_info[key]["photo"]):
            actor_info[key] = {"name": name, "tmdb_id": tmdb_id, "photo": f"{PHOTO_BASE}{photo}" if photo else ""}

    best, current = _streaks([e.watched_on for e in events], timezone.localdate())
    return {
        "year": year,
        "minutes": total,
        "titles": len(titles),
        "movies": sum(1 for t in titles.values() if t.type == "movie"),
        "shows": sum(1 for t in titles.values() if t.type == "tv"),
        "episodes": sum(len(v) for v in episodes.values()),
        "days": len({e.watched_on for e in events}),
        "longest_streak": {"days": best[0], "from": best[1].isoformat(), "to": best[2].isoformat()} if best else None,
        "current_streak": current if year == timezone.localdate().year else 0,
        "months": months,
        "top_genres": [
            {"genre": g, "minutes": round(m), "share": round(m / total, 3) if total else 0} for g, m in genres.most_common(5)
        ],
        "top_titles": [
            {"title": _show(titles[tid]), "minutes": m, "episodes": len(episodes.get(tid, ()))}
            for tid, m in sorted(by_title.items(), key=lambda kv: -kv[1])[:TOP]
        ],
        "top_actors": [
            # most titles first (a favourite actor is someone you keep watching), then time
            {**actor_info[k], "titles": actor_titles[k], "minutes": actor_minutes[k]}
            for k in sorted(actor_titles, key=lambda k: (-actor_titles[k], -actor_minutes[k]))[:TOP]
        ],
        "first": {"title": _show(events[0].title), "date": events[0].watched_on.isoformat()} if events else None,
    }


class StatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        years = sorted(
            {d.year for d in WatchEvent.objects.filter(profile=profile).dates("watched_on", "year")}, reverse=True
        )
        try:
            year = int(request.query_params.get("year") or (years[0] if years else timezone.localdate().year))
        except ValueError:
            year = timezone.localdate().year
        return Response({**year_stats(profile, year), "years": years})
