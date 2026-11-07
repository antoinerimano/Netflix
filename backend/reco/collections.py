# reco/collections.py
"""
Franchises ("collections" on TMDB: The Godfather Collection, James Bond...) in watch order.

  GET /api/collections/<collection_id>/?profileId=.. ->
    {
      "id", "name", "poster", "backdrop",
      "parts": [{"title": {...}, "position": 1, "watched": bool, "upcoming": bool}],  # release order
      "watched": 2, "total": 3,
      "next": {...title} | null,          # the first released part not watched yet
    }

"Next in your collections" (home row, live): for each franchise the profile started (watched a part)
and didn't finish, its next released part. "Watched" = in the watch history, played here, or
imported as watched.
Watch order is release order (what TMDB's collections follow); the profile's age limit applies.
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.maturity import allowed_titles_q
from users.models import Profile, Title

from .models import TitleAction, WatchEvent, WatchProgress

IMAGE_BASE = "https://image.tmdb.org/t/p/original"
NEXT_ROW_SIZE = 20
PART_FIELDS = ("id", "type", "title", "poster", "landscape_image", "release_date", "release_year",
               "runtime_minutes", "rating", "description", "collection_id", "belongs_to_collection")


def watched_ids(profile_id, among=None):
    """Titles the profile has watched (history, Play pressed, imported "watched")."""
    def scope(qs):
        return qs.filter(title_id__in=among) if among is not None else qs
    ids = set(scope(WatchEvent.objects.filter(profile_id=profile_id)).values_list("title_id", flat=True))
    ids |= set(scope(WatchProgress.objects.filter(profile_id=profile_id)).values_list("title_id", flat=True))
    ids |= set(scope(TitleAction.objects.filter(profile_id=profile_id, action__in=["outbound", "watched"]))
               .values_list("title_id", flat=True))
    return ids


def _released(t, today):
    return bool(t.release_date) and t.release_date <= today


def parts_of(collection_ids, profile):
    """{collection id: [titles in release order]} (movies the profile may see)."""
    out = {}
    qs = (
        Title.objects.filter(collection_id__in=list(collection_ids), type="movie").filter(allowed_titles_q(profile))
        .only(*PART_FIELDS)
    )
    for t in qs:
        out.setdefault(t.collection_id, []).append(t)
    for parts in out.values():
        # undated (announced) parts last
        parts.sort(key=lambda t: (not t.release_date, t.release_date or "", t.id))
    return out


def _card(t):
    return {
        "id": t.id, "type": t.type, "title": t.title, "poster": t.poster, "landscape_image": t.landscape_image,
        "release_year": t.release_year, "rating": t.rating, "description": t.description,
        "runtime_minutes": t.runtime_minutes,
    }


def next_in_collections_row(profile):
    """Home row: the next part of every franchise the profile started, most recently watched first."""
    seen = watched_ids(profile.id)
    if not seen:
        return None
    started = list(
        Title.objects.filter(id__in=seen, type="movie").exclude(collection_id=None).values_list("collection_id", flat=True)
    )
    if not started:
        return None
    # most recent watch first: the franchise you're in the middle of comes first
    recent = {
        tid: when for tid, when in WatchEvent.objects.filter(profile=profile, title_id__in=seen)
        .order_by("watched_at").values_list("title_id", "watched_at")
    }
    today = timezone.localdate().isoformat()
    items, order = [], {}
    for cid, parts in parts_of(set(started), profile).items():
        nxt = next((t for t in parts if t.id not in seen and _released(t, today)), None)
        if not nxt:
            continue
        done = [t for t in parts if t.id in seen]
        last = max((recent.get(t.id) for t in done if recent.get(t.id)), default=None)
        position = parts.index(nxt) + 1
        name = (nxt.belongs_to_collection or {}).get("name") or ""
        items.append({
            **_card(nxt),
            # "Part 2 of The Godfather Collection" under the card (worded by the app)
            "why_key": {"key": "collectionPart", "position": position, "collection": name},
            "collection_id": cid,
        })
        order[nxt.id] = last.timestamp() if last else 0
    if not items:
        return None
    items.sort(key=lambda it: -order[it["id"]])
    return {"row_type": "collections_next", "title": "Next in your collections", "items": items[:NEXT_ROW_SIZE]}


class CollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, collection_id):
        profile = get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)
        parts = parts_of([collection_id], profile).get(collection_id) or []
        if not parts:
            return Response({"detail": "collection not found"}, status=404)
        bc = next((t.belongs_to_collection for t in parts if isinstance(t.belongs_to_collection, dict)), {}) or {}
        seen = watched_ids(profile.id, among=[t.id for t in parts])
        today = timezone.localdate().isoformat()
        nxt = next((t for t in parts if t.id not in seen and _released(t, today)), None)
        return Response({
            "id": collection_id,
            "name": bc.get("name") or "",
            "poster": f"{IMAGE_BASE}{bc['poster_path']}" if bc.get("poster_path") else "",
            "backdrop": f"{IMAGE_BASE}{bc['backdrop_path']}" if bc.get("backdrop_path") else "",
            "parts": [
                {"title": _card(t), "position": i + 1, "watched": t.id in seen, "upcoming": not _released(t, today)}
                for i, t in enumerate(parts)
            ],
            "watched": len(seen),
            "total": len(parts),
            "next": _card(nxt) if nxt else None,
        })
