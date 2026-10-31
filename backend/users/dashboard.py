# users/dashboard.py
# Admin dashboard (<ADMINADMIN_URL>dashboard/): activity, providers, scheduled jobs, home pages,
# catalog. Staff only (admin_view in urls.py).
import datetime as dt
from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.template.response import TemplateResponse
from django.utils import timezone

from reco.models import Notification, PlaybackOutcome, RecoHomeSnapshot, TitleAction
from .models import Episode, JobRun, Profile, Provider, ProviderCheck, Title, User

PLAYS_DAYS = 14

# Scheduled commands, with how often they normally run: past "late_after" without a run, the
# dashboard flags them (cron stopped, server down...). None = no fixed schedule.
JOBS = [
    ("check_providers", "Provider health check", timedelta(hours=1)),
    ("sync_tmdb_daily_episodes", "New episodes sync", timedelta(hours=8)),
    ("notify_new_episodes", "New episode alerts", timedelta(hours=8)),
    ("build_home_snapshots", "Home pages build", timedelta(hours=6)),
    ("sync_tmdb_monthly", "Catalog sync (monthly)", timedelta(days=35)),
    ("train_ranker", "Ranker training", None),
    ("build_embeddings", "Embeddings build", None),
    ("backfill_ratings", "Age ratings backfill", None),
    ("clean_db", "Database cleanup", None),
]


def _pct(part, whole):
    return round(100 * part / whole) if whole else None


def _plays_per_day(now):
    start = (now - timedelta(days=PLAYS_DAYS - 1)).date()
    counts = dict(
        TitleAction.objects
        .filter(action="outbound", created_at__date__gte=start)
        # UTC days: MySQL can't convert time zones without its tz tables
        .annotate(day=TruncDate("created_at", tzinfo=dt.timezone.utc))
        .values("day")
        .annotate(n=Count("id"))
        .values_list("day", "n")
    )
    days = [start + timedelta(days=i) for i in range(PLAYS_DAYS)]
    top = max([counts.get(d, 0) for d in days] + [1])
    return [
        {"day": d, "n": counts.get(d, 0), "height": round(100 * counts.get(d, 0) / top, 1)}
        for d in days
    ], top


def _providers(now):
    since7, since24 = now - timedelta(days=7), now - timedelta(hours=24)
    plays = {
        r["provider_key"]: r
        for r in PlaybackOutcome.objects.filter(created_at__gte=since7)
        .values("provider_key")
        .annotate(n=Count("id"), ok=Count("id", filter=Q(worked=True)))
    }
    checks = {
        r["provider_key"]: r
        for r in ProviderCheck.objects.filter(checked_at__gte=since24)
        .values("provider_key")
        .annotate(n=Count("id"), up=Count("id", filter=Q(status=Provider.UP)))
    }
    rows = []
    for p in Provider.objects.all():
        pl, ch = plays.get(p.key, {}), checks.get(p.key, {})
        rows.append({
            "p": p,
            "plays": pl.get("n", 0),
            "success": _pct(pl.get("ok", 0), pl.get("n", 0)),
            "uptime": _pct(ch.get("up", 0), ch.get("n", 0)),
            "checks": ch.get("n", 0),
        })
    most_plays = max([r["plays"] for r in rows] + [1])
    for r in rows:
        r["plays_width"] = round(100 * r["plays"] / most_plays, 1)
    return sorted(rows, key=lambda r: (-r["plays"], r["p"].priority))


def _jobs(now):
    since7 = now - timedelta(days=7)
    rows = []
    for name, label, late_after in JOBS:
        last = JobRun.objects.filter(name=name).order_by("-started_at").first()
        failures = JobRun.objects.filter(name=name, ok=False, started_at__gte=since7).count()
        runs = JobRun.objects.filter(name=name, started_at__gte=since7).count()
        late = bool(late_after and (last is None or now - last.started_at > late_after))
        if last is None:
            state = "never"
        elif last.ok is None:
            state = "running"
        elif not last.ok:
            state = "failed"
        else:
            state = "late" if late else "ok"
        rows.append({"name": name, "label": label, "last": last, "runs": runs, "failures": failures,
                     "state": state, "late_after": late_after})
    return rows


def dashboard_view(request):
    now = timezone.now()
    since24, since7 = now - timedelta(hours=24), now - timedelta(days=7)

    plays, plays_top = _plays_per_day(now)
    snapshots = RecoHomeSnapshot.objects.all()
    failed_snapshots = list(
        snapshots.exclude(last_error="").select_related("profile").order_by("-built_at")[:10]
    )
    titles_total = Title.objects.count()
    top_titles = list(
        TitleAction.objects.filter(action="outbound", created_at__gte=since7)
        .values("title_id", "title__title", "title__type")
        .annotate(viewers=Count("profile", distinct=True))
        .order_by("-viewers")[:10]
    )
    most_viewers = max([t["viewers"] for t in top_titles] + [1])
    for t in top_titles:
        t["width"] = round(100 * t["viewers"] / most_viewers, 1)

    context = {
        **admin.site.each_context(request),
        "title": "Dashboard",
        "now": now,
        "tiles": [
            ("Plays, last 24 h", TitleAction.objects.filter(action="outbound", created_at__gte=since24).count()),
            ("Active profiles, 7 days", TitleAction.objects.filter(created_at__gte=since7)
             .values("profile").distinct().count()),
            ("New accounts, 7 days", User.objects.filter(created_at__gte=since7).count()),
            ("Alert emails sent, 7 days", Notification.objects.filter(emailed_at__gte=since7).count()),
        ],
        "plays": plays,
        "plays_top": plays_top,
        "plays_total": sum(d["n"] for d in plays),
        "providers": _providers(now),
        "jobs": _jobs(now),
        "snapshots_total": snapshots.count(),
        "snapshots_failed": snapshots.exclude(last_error="").count(),
        "snapshots_oldest": snapshots.order_by("built_at").values_list("built_at", flat=True).first(),
        "profiles_without_snapshot": Profile.objects.filter(home_snapshot__isnull=True).count(),
        "failed_snapshots": failed_snapshots,
        "top_titles": top_titles,
        "catalog": [
            ("Titles", titles_total),
            ("Episodes", Episode.objects.count()),
            ("With an age rating", f"{_pct(Title.objects.exclude(maturity=None).count(), titles_total) or 0} %"),
            ("Accounts / profiles", f"{User.objects.count()} / {Profile.objects.count()}"),
        ],
    }
    return TemplateResponse(request, "admin/dashboard.html", context)
