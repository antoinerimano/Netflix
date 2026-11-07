# reco/pick.py
"""
"What to watch?" (/pick in the app): a few titles that fit the time you have and your mood, or
one at random ("Surprise me").

  GET /api/pick/?profileId=..&time=90|120|episode|any&mood=funny|exciting|scary|feelgood|thoughtful|romantic|any
                 &count=6&exclude=1,2,3
  -> {"items": [{...title, "minutes": 98}], "candidates": 412}

time: "90" movies up to 95 min, "120" movies up to 130 min, "episode" shows whose episodes last
up to 60 min, "any" both without a limit. mood: a set of genres (and some left out: no horror in
"feel-good"). Only titles people liked (enough votes, a decent rating), released, with a poster,
within the profile's age limit, not watched / rated / turned down by it, not in `exclude` (what
the app already showed: "Show me" again, "Another one").
Ranked like the home page (taste profile + ranker, reco/views.py), then drawn at random among the
best ones, weighted by rank: every press gives a different set, all of them good fits.
"""
import random

from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.maturity import allowed_titles_q, profile_max_level
from users.models import Profile, TVShowExtras

from .models import TitleAction, TitleRating, WatchEvent, WatchProgress

MOODS = {
    "funny": (["Comedy"], ["Horror"]),
    "exciting": (["Action", "Adventure", "Thriller", "Action & Adventure"], []),
    "scary": (["Horror"], []),
    "feelgood": (["Family", "Animation", "Comedy", "Romance", "Music"], ["Horror", "War", "Thriller", "Crime"]),
    "thoughtful": (["Drama", "Documentary", "History", "Mystery"], ["Animation", "Family"]),
    "romantic": (["Romance"], ["Horror"]),
}
TIMES = {  # (kinds, max minutes or None)
    "90": (["movie"], 95),
    "120": (["movie"], 130),
    "episode": (["tv"], 60),
    "any": (["movie", "tv"], None),
}
MIN_VOTES = 300
MIN_RATING = 6.3
MIN_MOVIE = 60          # shorter "movies" are mostly shorts / specials
POOL = 400              # most popular matching titles scored (the picks come from the best 60)
DRAW_FROM = 60          # the best ranked ones the picks are drawn from
MAX_COUNT = 12
MAX_EXCLUDE = 300
EPISODE_MINUTES = 45
CANDIDATES_TTL = 3600   # the same for every profile with that age limit: one query an hour


def _seen(profile_id):
    """Titles the profile watched, rated or turned down: not picked again."""
    ids = set(WatchEvent.objects.filter(profile_id=profile_id).values_list("title_id", flat=True))
    ids |= set(WatchProgress.objects.filter(profile_id=profile_id).values_list("title_id", flat=True))
    ids |= set(TitleRating.objects.filter(profile_id=profile_id).values_list("title_id", flat=True))
    ids |= set(TitleAction.objects.filter(
        profile_id=profile_id, action__in=["outbound", "watched", "not_interested"]).values_list("title_id", flat=True))
    return ids


def candidates(profile, time_key, mood_key):
    """[(Title, minutes)] that fit, most popular first (cached per age limit, time and mood: the
    genre filter can't use an index, ~0.5 s a query)."""
    key = f"pick:v1:{profile_max_level(profile)}:{time_key}:{mood_key}"
    out = cache.get(key)
    if out is None:
        out = _candidates(profile, time_key, mood_key)
        cache.set(key, out, CANDIDATES_TTL)
    return out


def _candidates(profile, time_key, mood_key):
    from .views import _released_titles

    kinds, limit = TIMES[time_key]
    qs = (
        _released_titles().filter(type__in=kinds, vote_count__gte=MIN_VOTES, vote_average__gte=MIN_RATING)
        .exclude(poster="").filter(allowed_titles_q(profile))
    )
    if mood_key in MOODS:
        wanted, unwanted = MOODS[mood_key]
        q = Q()
        for g in wanted:
            q |= Q(genre__icontains=g)
        qs = qs.filter(q)
        for g in unwanted:
            qs = qs.exclude(genre__icontains=g)
    if kinds == ["movie"]:
        qs = qs.filter(runtime_minutes__gte=MIN_MOVIE, runtime_minutes__lte=limit)
    titles = list(qs.only("id", "type", "title", "poster", "landscape_image", "release_year", "rating", "description",
                          "runtime_minutes", "popularity").order_by("-popularity")[:POOL])

    episode = dict(
        TVShowExtras.objects.filter(title_id__in=[t.id for t in titles if t.type == "tv"])
        .values_list("title_id", "episode_run_time")
    )
    out = []
    for t in titles:
        if t.type == "movie":
            minutes = t.runtime_minutes
            if limit is None and minutes is not None and minutes < MIN_MOVIE:
                continue
        else:
            rts = episode.get(t.id) or []
            minutes = int(rts[0]) if rts and rts[0] else EPISODE_MINUTES
            if limit is not None and minutes > limit:
                continue
        out.append((t, minutes))
    return out


def ranked(profile, items):
    """The same items, best first for this profile (home page scoring; popularity when it can't)."""
    from .views import _build_profile_vector, _get_latest_ranker, _rank_titles_for, _score_candidates

    ids = [t.id for t, _ in items]
    scores = {}
    try:
        rank_model, _schema = _get_latest_ranker()
        scores = _score_candidates(profile, _build_profile_vector(profile.id), rank_model, ids, _rank_titles_for(profile, ids))
    except Exception:  # no embeddings / ranker yet: popularity
        scores = {}
    if not scores:
        return items
    return sorted(items, key=lambda it: -scores.get(it[0].id, float("-inf")))


def draw(items, count, rng=random):
    """count items from the best DRAW_FROM, weighted by rank (the best more likely), no repeats."""
    pool = list(items[:DRAW_FROM])
    weights = [1.0 / (1 + i * 0.12) for i in range(len(pool))]
    picked = []
    while pool and len(picked) < count:
        i = rng.choices(range(len(pool)), weights=weights)[0]
        picked.append(pool.pop(i))
        weights.pop(i)
    return picked


class PickView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        time_key = request.query_params.get("time") or "any"
        mood_key = request.query_params.get("mood") or "any"
        if time_key not in TIMES or (mood_key != "any" and mood_key not in MOODS):
            return Response({"detail": "unknown time or mood"}, status=400)
        try:
            count = max(1, min(MAX_COUNT, int(request.query_params.get("count") or 6)))
        except ValueError:
            count = 6
        exclude = {int(x) for x in str(request.query_params.get("exclude") or "").split(",")[:MAX_EXCLUDE] if x.strip().isdigit()}

        skip = _seen(profile.id) | exclude
        items = [(t, m) for t, m in candidates(profile, time_key, mood_key) if t.id not in skip]
        picks = draw(ranked(profile, items), count)
        return Response({
            "items": [
                {
                    "id": t.id, "type": t.type, "title": t.title, "poster": t.poster,
                    "landscape_image": t.landscape_image, "release_year": t.release_year, "rating": t.rating,
                    "description": t.description, "minutes": m,
                }
                for t, m in picks
            ],
            "candidates": len(items),
        })
