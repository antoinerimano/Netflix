# reco/taste.py
"""
Taste onboarding: a new profile picks a few titles it likes before its first home page.

  GET  /api/taste/?profileId=..                     -> {"titles": [...], "min_picks": 3}
  POST /api/taste/?profileId=..  {"title_ids": [..]} -> {"liked": n, "home": "rebuilt" | "pending"}

The picks are saved as likes (TitleRating), the strongest signal a new profile can give: they
become the seeds of "For you", "Because you liked ..." and the genre / studio rows. The home
snapshot is then rebuilt right away, so the first home page is already personal (the cron only
rebuilds every few hours).
"""
import logging
import random
from collections import OrderedDict
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.maturity import allowed_titles_q
from users.models import Profile, Title

from .models import MyListItem, RecoHomeSnapshot, TitleAction, TitleRating, WatchProgress

logger = logging.getLogger(__name__)

MIN_PICKS = 3
MAX_PICKS = 50
CHOICES = 60            # titles offered (the page shows them a screenful at a time)
IN_LANGUAGE = 12        # of which in the profile's language, when it isn't English
MIN_VOTES = 300         # well-known titles only: people recognise them from the poster
SNAPSHOT_HOURS = 6      # same lifetime as the cron's snapshots

CHOICE_FIELDS = ("id", "type", "title", "poster", "release_year", "primary_genre_norm", "original_language")


def has_taste_signal(profile_id):
    """True once a profile told us anything it likes (thumb, My List, played something)."""
    return (
        TitleRating.objects.filter(profile_id=profile_id, value=TitleRating.LIKE).exists()
        or MyListItem.objects.filter(profile_id=profile_id).exists()
        or WatchProgress.objects.filter(profile_id=profile_id).exists()
        or TitleAction.objects.filter(profile_id=profile_id, action="outbound").exists()
    )


def _spread(titles, k):
    """Up to k titles, one genre after another (popular first in each): a varied first screen
    instead of 20 action movies. Movies and shows alternate inside a genre."""
    by_genre = OrderedDict()
    for t in titles:
        by_genre.setdefault(t.primary_genre_norm or "other", {"movie": [], "tv": []})[t.type].append(t)
    queues = []
    for kinds in by_genre.values():
        mixed = []
        movies, shows = kinds["movie"], kinds["tv"]
        for i in range(max(len(movies), len(shows))):
            mixed += movies[i:i + 1] + shows[i:i + 1]
        queues.append(mixed)
    picked = []
    while queues and len(picked) < k:
        for q in list(queues):
            if q:
                picked.append(q.pop(0))
            if not q:
                queues.remove(q)
            if len(picked) >= k:
                break
    return picked


def taste_choices(profile, k=CHOICES):
    # imported here: reco.views imports has_taste_signal from this module
    from .views import _cached_ids, _released_titles

    popular_ids = _cached_ids(
        "popular_seed",
        lambda: _released_titles().order_by("-popularity", "-vote_average").values_list("id", flat=True)[:1200],
    )
    rated = set(TitleRating.objects.filter(profile_id=profile.id).values_list("title_id", flat=True))
    base = (
        Title.objects.filter(vote_count__gte=MIN_VOTES).exclude(poster="")
        .filter(allowed_titles_q(profile)).exclude(id__in=rated).only(*CHOICE_FIELDS)
    )
    order = {tid: i for i, tid in enumerate(popular_ids)}
    popular = sorted(base.filter(id__in=popular_ids), key=lambda t: order[t.id])

    lang = (profile.language_preference or "").split("-")[0].lower()
    local = []
    if lang and lang != "en":
        local = list(
            base.filter(original_language=lang).order_by("-popularity")[:IN_LANGUAGE * 3]
        )
        local = _spread(local, IN_LANGUAGE)

    local_ids = {t.id for t in local}
    rest = _spread([t for t in popular if t.id not in local_ids], k - len(local))
    # the language picks spread through the list, not all at the end
    picked = list(rest)
    for i, t in enumerate(local):
        picked.insert(min(len(picked), 2 + i * 4), t)
    return picked[:k]


def rebuild_home(profile):
    """Personal home snapshot now (False if it failed: the starter page stays until the cron)."""
    from .views import build_home_payload_exact

    try:
        payload = build_home_payload_exact(profile=profile, user_id=profile.user_id, do_logs=False)
    except Exception:
        logger.exception("[taste] home rebuild failed for profile_id=%s", profile.id)
        return False
    # nothing left to show (small catalog, everything already seen / rated): keep the page it has
    # rather than replacing it with an empty one (one snapshot row per profile)
    if not any(row.get("items") for row in payload.get("rows") or []):
        logger.warning("[taste] rebuilt home is empty for profile_id=%s: kept the previous one", profile.id)
        return False
    RecoHomeSnapshot.objects.update_or_create(
        profile_id=profile.id,
        defaults={
            "algo_version": "home_v1",
            "payload": payload,
            "expires_at": timezone.now() + timedelta(hours=SNAPSHOT_HOURS),
            "last_error": "",
        },
    )
    return True


class TasteView(APIView):
    permission_classes = [IsAuthenticated]

    def _profile(self, request):
        return get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)

    def get(self, request):
        profile = self._profile(request)
        titles = taste_choices(profile)
        return Response({
            "min_picks": MIN_PICKS,
            "titles": [
                {"id": t.id, "type": t.type, "title": t.title, "poster": t.poster, "release_year": t.release_year}
                for t in titles
            ],
        })

    def post(self, request):
        profile = self._profile(request)
        raw = request.data.get("title_ids")
        if not isinstance(raw, list) or not raw or len(raw) > MAX_PICKS:
            return Response({"detail": f"title_ids must be a list of 1 to {MAX_PICKS} ids"}, status=400)
        try:
            wanted = {int(x) for x in raw}
        except (TypeError, ValueError):
            return Response({"detail": "title_ids must be numbers"}, status=400)

        ids = list(Title.objects.filter(id__in=wanted).values_list("id", flat=True))
        # the order the cards were picked in is lost: shuffle so no genre always comes "newest"
        random.shuffle(ids)
        session = str(request.data.get("session_id") or "")[:64]
        for tid in ids:
            TitleRating.objects.update_or_create(profile=profile, title_id=tid, defaults={"value": TitleRating.LIKE})
        TitleAction.objects.bulk_create([
            TitleAction(profile=profile, title_id=tid, action="like", session_id=session, provider="onboarding")
            for tid in ids
        ])
        rebuilt = rebuild_home(profile) if ids else False
        return Response({"liked": len(ids), "home": "rebuilt" if rebuilt else "pending"})
