# reco/history.py
"""
Watch history of a profile (/history in the app).

  GET    /api/history/?profileId=..&page=1   -> {"paused", "items": [entry], "next": page | null}
  DELETE /api/history/<id>/?profileId=..     remove one entry
  DELETE /api/history/?profileId=..          clear it all
  POST   /api/history/pause/?profileId=..    {"paused": bool}
  GET    /api/history/export/?profileId=..   CSV file
    entry = {"id", "watched_at", "season", "episode", "episode_name", "title": {id, type, title, poster, ...}}

Entries are written when the watch page opens (record_watch, from WatchProgressView): one per
title + episode + day. Removing the last entry of a title forgets it: Continue watching, the
Play / open signals and sources that fed recommendations, and its "Because you watched" row.
While history is paused, nothing about what the profile watches is saved (paused()).
"""
import csv

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.maturity import allowed_titles_q
from users.models import Episode, Profile

from .models import PlaybackOutcome, RecoHomeSnapshot, TitleAction, WatchEvent, WatchProgress

PAGE_SIZE = 50
# signals that only say "this profile watched / opened it" (likes, My List... are choices: they stay)
WATCH_SIGNALS = ("outbound", "click", "search_click")


def paused(profile_id):
    return Profile.objects.filter(id=profile_id, history_paused=True).exists()


def record_watch(profile, title, season=None, episode=None):
    """The watch page opened this movie / episode: today's history entry (once per day)."""
    now = timezone.now()
    WatchEvent.objects.update_or_create(
        profile=profile, title=title, season_number=season or 0, episode_number=episode or 0,
        watched_on=timezone.localdate(), defaults={"watched_at": now},
    )


def forget_titles(profile, title_ids):
    """Everything watching these titles left behind (history removed): not choices like thumbs."""
    title_ids = list(title_ids)
    if not title_ids:
        return
    TitleAction.objects.filter(profile=profile, title_id__in=title_ids, action__in=WATCH_SIGNALS).delete()
    WatchProgress.objects.filter(profile=profile, title_id__in=title_ids).delete()
    PlaybackOutcome.objects.filter(profile=profile, title_id__in=title_ids).delete()
    # the home page snapshot may hold "Because you watched <title>": drop those rows now
    snap = RecoHomeSnapshot.objects.filter(profile=profile).first()
    if snap and snap.payload:
        gone = {f"because:{tid}" for tid in title_ids}
        rows = [r for r in snap.payload.get("rows") or [] if r.get("row_type") not in gone]
        if len(rows) != len(snap.payload.get("rows") or []):
            snap.payload = {**snap.payload, "rows": rows}
            snap.save(update_fields=["payload"])


def _profile(request):
    return get_object_or_404(Profile, id=request.query_params.get("profileId"), user=request.user)


def _episode_names(events):
    keys = {(e.title_id, e.season_number, e.episode_number) for e in events if e.episode_number}
    if not keys:
        return {}
    q = Q()
    for tid, s, n in keys:
        q |= Q(season__tv_id=tid, season__season_number=s, episode_number=n)
    return {
        (tid, s, n): (eid, name)
        for eid, tid, s, n, name in Episode.objects.filter(q).values_list(
            "id", "season__tv_id", "season__season_number", "episode_number", "name")
    }


def _entry(e, names):
    ep_id, ep_name = names.get((e.title_id, e.season_number, e.episode_number), (None, ""))
    t = e.title
    return {
        "id": e.id,
        "watched_at": e.watched_at.isoformat(),
        "season": e.season_number or None,
        "episode": e.episode_number or None,
        # an episode-like object: the API's renderer translates its name ({id, episode_number, name})
        "episode_info": {"id": ep_id, "episode_number": e.episode_number, "name": ep_name} if ep_id else None,
        "title": {"id": t.id, "type": t.type, "title": t.title, "poster": t.poster, "landscape_image": t.landscape_image},
    }


class HistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _profile(request)
        try:
            page = max(1, int(request.query_params.get("page") or 1))
        except ValueError:
            page = 1
        qs = (
            WatchEvent.objects.filter(profile=profile).filter(allowed_titles_q(profile, prefix="title__"))
            .select_related("title").order_by("-watched_at", "-id")
        )
        events = list(qs[(page - 1) * PAGE_SIZE: page * PAGE_SIZE + 1])
        more = len(events) > PAGE_SIZE
        events = events[:PAGE_SIZE]
        names = _episode_names(events)
        return Response({
            "paused": profile.history_paused,
            "items": [_entry(e, names) for e in events],
            "next": page + 1 if more else None,
        })

    def delete(self, request):
        """Clear the whole history (and what it fed)."""
        profile = _profile(request)
        title_ids = set(WatchEvent.objects.filter(profile=profile).values_list("title_id", flat=True))
        title_ids |= set(WatchProgress.objects.filter(profile=profile).values_list("title_id", flat=True))
        WatchEvent.objects.filter(profile=profile).delete()
        forget_titles(profile, title_ids)
        return Response({"cleared": len(title_ids)})


class HistoryItemView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, event_id):
        profile = _profile(request)
        event = get_object_or_404(WatchEvent, id=event_id, profile=profile)
        title_id = event.title_id
        event.delete()
        forgotten = not WatchEvent.objects.filter(profile=profile, title_id=title_id).exists()
        if forgotten:
            forget_titles(profile, [title_id])
        return Response({"ok": True, "title_forgotten": forgotten})


class HistoryPauseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile = _profile(request)
        profile.history_paused = bool(request.data.get("paused"))
        profile.save(update_fields=["history_paused"])
        return Response({"paused": profile.history_paused})


class HistoryExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = _profile(request)
        events = list(WatchEvent.objects.filter(profile=profile).select_related("title").order_by("-watched_at", "-id"))
        names = _episode_names(events)
        res = HttpResponse(content_type="text/csv; charset=utf-8")
        stamp = timezone.localdate().isoformat()
        res["Content-Disposition"] = f'attachment; filename="watch-history-{stamp}.csv"'
        res.write("﻿")  # Excel opens it as UTF-8
        out = csv.writer(res)
        out.writerow(["Date", "Time", "Type", "Title", "Season", "Episode", "Episode title"])
        for e in events:
            when = timezone.localtime(e.watched_at)
            _, ep_name = names.get((e.title_id, e.season_number, e.episode_number), (None, ""))
            out.writerow([
                when.date().isoformat(), when.strftime("%H:%M"), "Show" if e.title.type == "tv" else "Movie",
                e.title.title, e.season_number or "", e.episode_number or "", ep_name,
            ])
        return res

