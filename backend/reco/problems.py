# reco/problems.py
# "Playback problem?" + the public status page (ROADMAP 9.8).
#
#   POST /api/playback/report/  {provider, title_id, season?, episode?, problem, profile_id?}
#        a viewer says what's wrong with a source (signed out too). Saved with the source and the
#        title / episode, on the admin dashboard; "doesn't play" / "wrong film" also count as a
#        failed play for the profile (the source goes last on this title, ROADMAP 9.2).
#   GET  /api/status/  the site is up (database answers) + each source's last checks: the health
#        check (every 15 min), the scout's nightly playback test, the viewers' plays and the
#        problems reported in the last 24 h. Public, cached 60 s: "is it down for me or everyone?"
#        (the page then tests each source from the visitor's own connection).
#
# The scout (provider_scraper/, mini PC): export_providers hands it open_reports() (the sources
# reported lately go first that night, and it plays the reported titles on them); import_providers
# writes its answer back with record_rechecks().
import re
from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import Profile, Provider, Title
from users.throttles import _IPRateThrottle

from .models import PlaybackOutcome, PlaybackReport

PROBLEMS = {key for key, _ in PlaybackReport.PROBLEMS}
FAILED_PLAY = {PlaybackReport.NOT_PLAYING, PlaybackReport.WRONG_TITLE}  # the source didn't play this title
SAME_REPORT_HOURS = 6  # the same profile reporting the same thing again: saved once
SCOUT_REPORT_DAYS = 7  # reports the scout re-checks (not checked yet, at most this old)
SCOUT_MAX_REPORTS = 20
STATUS_CACHE_S = 60
STATUS_MIN_PLAYS = 5  # fewer plays in 24 h: no viewers' share shown
PROBLEMS_FROM_REPORTS = 3  # reports in 24 h that make a source "having problems"


class ReportRateThrottle(_IPRateThrottle):
    scope = "report"


def _int_or_none(value, top=32767):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= top else None


class PlaybackReportView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ReportRateThrottle]

    def post(self, request):
        data = request.data
        problem = str(data.get("problem") or "")
        if problem not in PROBLEMS:
            return Response({"detail": "unknown problem"}, status=400)
        key = str(data.get("provider") or "")
        if not Provider.objects.filter(key=key).exists():
            return Response({"detail": "unknown provider"}, status=400)
        title = get_object_or_404(Title.objects.only("id", "type"), id=_int_or_none(data.get("title_id"), top=2**31))
        profile = None
        if request.user.is_authenticated and data.get("profile_id"):
            profile = get_object_or_404(Profile, id=data.get("profile_id"), user=request.user)
        is_tv = title.type == Title.TV
        season = _int_or_none(data.get("season")) if is_tv else None
        episode = _int_or_none(data.get("episode")) if is_tv else None

        fields = dict(profile=profile, title=title, season_number=season, episode_number=episode,
                      provider_key=key, problem=problem)
        since = timezone.now() - timedelta(hours=SAME_REPORT_HOURS)
        if profile and PlaybackReport.objects.filter(created_at__gte=since, **fields).exists():
            return Response({"ok": True, "again": True})
        PlaybackReport.objects.create(**fields)
        if profile and problem in FAILED_PLAY and not profile.history_paused:
            PlaybackOutcome.objects.create(profile=profile, title=title, provider_key=key, worked=False)
        return Response({"ok": True}, status=201)


# ---------------------------------------------------------------- the scout

def _episode_minutes(title, season, episode):
    from users.models import Episode

    return (Episode.objects.filter(season__tv=title, season__season_number=season, episode_number=episode)
            .values_list("runtime", flat=True).first())


def open_reports(now=None, limit=SCOUT_MAX_REPORTS):
    """
    The reports the scout hasn't re-checked yet (last 7 days), one per source + title / episode,
    the most reported first: [{"provider", "type", "tmdb", "imdb", "season", "episode", "name",
    "minutes", "problems": {problem: n}, "count"}]. Titles without a TMDB id can't be played there.
    """
    now = now or timezone.now()
    sources = Provider.objects.values_list("key", flat=True)  # a source removed since can't be checked
    rows = (PlaybackReport.objects
            .filter(checked_at__isnull=True, provider_key__in=list(sources), created_at__gte=now - timedelta(days=SCOUT_REPORT_DAYS),
                    title__tmdb_id__isnull=False)
            .values("provider_key", "title_id", "season_number", "episode_number", "problem")
            .annotate(n=Count("id")))
    groups = {}
    for r in rows:
        g = groups.setdefault((r["provider_key"], r["title_id"], r["season_number"], r["episode_number"]), {})
        g[r["problem"]] = g.get(r["problem"], 0) + r["n"]
    ranked = sorted(groups.items(), key=lambda kv: -sum(kv[1].values()))[:limit]
    titles = Title.objects.in_bulk({k[1] for k, _ in ranked})
    out = []
    for (key, title_id, season, episode), problems in ranked:
        t = titles.get(title_id)
        if not t:
            continue
        tv = t.type == Title.TV and season and episode
        item = {"provider": key, "type": "tv" if tv else "movie", "tmdb": t.tmdb_id, "imdb": t.imdb_code or "",
                "name": f"{t.title[:50]} {season}x{episode:02d}" if tv else t.title[:60],
                "problems": problems, "count": sum(problems.values())}
        if tv:
            item.update(season=season, episode=episode, minutes=_episode_minutes(t, season, episode) or 0)
        else:
            item["minutes"] = t.runtime_minutes or 0
        out.append(item)
    return out


def _result_text(r):
    state = str(r.get("state") or "")
    detail = str(r.get("detail") or "")[:150]
    if state == "live":
        text = "played in the scout's test"
    elif state in ("protected", "unverified", "untested", ""):
        text = "no verdict from the scout"
    else:
        text = f"didn't play in the scout's test ({state})"
    return f"{text}: {detail}" if detail else text


def record_rechecks(provider_key, results, now=None):
    """
    The scout played the reported titles on this source (catalog health "reports":
    [{"type", "tmdb", "season", "episode", "state", "detail"}]): its answer goes on the open
    reports of that source + title / episode. -> how many reports got an answer.
    """
    now = now or timezone.now()
    marked = 0
    for r in results or []:
        if not isinstance(r, dict):
            continue
        tmdb = _int_or_none(r.get("tmdb"), top=2**31)
        if not tmdb:
            continue
        kind = Title.TV if r.get("type") == "tv" else Title.MOVIE
        qs = PlaybackReport.objects.filter(provider_key=provider_key, checked_at__isnull=True,
                                           title__tmdb_id=tmdb, title__type=kind)
        if kind == Title.TV:
            qs = qs.filter(season_number=_int_or_none(r.get("season")), episode_number=_int_or_none(r.get("episode")))
        marked += qs.update(checked_at=now, check_result=_result_text(r)[:200])
    return marked


# ---------------------------------------------------------------- admin dashboard

def dashboard_reports(now, days=7, latest=15):
    """The dashboard's "Playback problems reported" card: per source and the latest reports."""
    since = now - timedelta(days=days)
    qs = PlaybackReport.objects.filter(created_at__gte=since)
    labels = dict(Provider.objects.values_list("key", "label"))
    names = dict(PlaybackReport.PROBLEMS)
    per_source = []
    rows = qs.values("provider_key").annotate(
        n=Count("id"), checked=Count("id", filter=Q(checked_at__isnull=False)),
        **{p: Count("id", filter=Q(problem=p)) for p in PROBLEMS})
    for r in sorted(rows, key=lambda r: -r["n"]):
        per_source.append({
            "key": r["provider_key"], "label": labels.get(r["provider_key"], r["provider_key"]),
            "n": r["n"], "checked": r["checked"],
            "problems": [(names[p], r[p]) for p, _ in PlaybackReport.PROBLEMS if r[p]],
        })
    last = []
    for rep in qs.select_related("title").order_by("-created_at")[:latest]:
        last.append({
            "r": rep, "source": labels.get(rep.provider_key, rep.provider_key), "problem": names.get(rep.problem, rep.problem),
            "episode": f"S{rep.season_number} E{rep.episode_number}" if rep.season_number and rep.episode_number else "",
        })
    return {"total": qs.count(), "per_source": per_source, "latest": last, "days": days}


# ---------------------------------------------------------------- public status page

_SCOUT_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_SCOUT_PLAYED = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} [a-z_]+ (\d+)/(\d+)\b")


def _scout_summary(p):
    """The scout's last nightly test, from Provider.scout_check ("2026-11-25 04:10 live 9/11 - ..."):
    {"date", "played", "tested"} or None."""
    note = p["scout_check"] or ""
    date = _SCOUT_DATE.match(note)
    if not date:
        return None
    played = _SCOUT_PLAYED.match(note)  # the state, then "verified" (not the "anime 2/3" after it)
    return {"date": date.group(1), "played": int(played.group(1)) if played else None,
            "tested": int(played.group(2)) if played else None}


def source_state(status, plays, ok, reports, scout_score):
    """down / problems / up / unknown: what the status page says about one source."""
    if status == Provider.DOWN:
        return "down"
    if reports >= PROBLEMS_FROM_REPORTS:
        return "problems"
    if plays >= STATUS_MIN_PLAYS and ok / plays < 0.5:
        return "problems"
    if scout_score is not None and scout_score < 0.5:
        return "problems"
    if status == Provider.UP:
        return "up"
    return "unknown"


def _database_ok():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True
    except Exception:  # noqa: BLE001 (any database problem = not up)
        return False


def status_data(now=None):
    now = now or timezone.now()
    since = now - timedelta(hours=24)
    plays = {r["provider_key"]: r for r in PlaybackOutcome.objects.filter(created_at__gte=since)
             .values("provider_key").annotate(n=Count("id"), ok=Count("id", filter=Q(worked=True)))}
    reports = dict(PlaybackReport.objects.filter(created_at__gte=since).values("provider_key")
                   .annotate(n=Count("id")).values_list("provider_key", "n"))
    sources = []
    for p in Provider.objects.filter(enabled=True).values("key", "label", "domain", "status", "checked_at",
                                                          "scout_check", "scout_score", "priority"):
        pl = plays.get(p["key"], {})
        n, ok = pl.get("n", 0), pl.get("ok", 0)
        sources.append({
            "key": p["key"], "label": p["label"], "domain": p["domain"],
            "state": source_state(p["status"], n, ok, reports.get(p["key"], 0), p["scout_score"]),
            "checked_at": p["checked_at"].isoformat() if p["checked_at"] else None,
            "scout": _scout_summary(p),
            "plays_24h": n,
            "played_share_24h": round(ok / n, 2) if n >= STATUS_MIN_PLAYS else None,
            "reports_24h": reports.get(p["key"], 0),
            "_priority": p["priority"],
        })
    order = {"up": 0, "problems": 1, "unknown": 2, "down": 3}
    sources.sort(key=lambda s: (order[s["state"]], s.pop("_priority"), s["label"].lower()))
    return {"ok": True, "generated_at": now.isoformat(), "sources": sources,
            "counts": {state: sum(s["state"] == state for s in sources) for state in order}}


class StatusView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # public, the same for everyone (cached)

    def get(self, request):
        if not _database_ok():
            return Response({"ok": False}, status=503)
        data = cache.get("reco:status:v1")
        if data is None:
            data = status_data()
            cache.set("reco:status:v1", data, STATUS_CACHE_S)
        response = Response(data)
        response["Cache-Control"] = f"public, max-age={STATUS_CACHE_S}"
        return response
