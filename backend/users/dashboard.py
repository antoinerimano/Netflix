# users/dashboard.py
# Admin dashboard (<ADMINADMIN_URL>dashboard/): visitors (reco/visits.py), activity, providers,
# scheduled jobs, home pages, catalog. Staff only (admin_view in urls.py).
import datetime as dt
from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.utils import timezone

from reco.models import Notification, PlaybackOutcome, RecoHomeSnapshot, TitleAction
from reco.visits import live_stats, visitor_stats
from .models import Episode, JobRun, Profile, Provider, ProviderCheck, Title, User

PLAYS_DAYS = 14

# Scheduled commands, with how often they normally run: past "late_after" without a run, the
# dashboard flags them (cron stopped, server down...). None = no fixed schedule.
JOBS = [
    ("check_providers", "Provider health check", timedelta(hours=1)),
    ("sync_tmdb_daily_episodes", "New episodes sync", timedelta(hours=8)),
    ("notify_new_episodes", "New episode alerts", timedelta(hours=8)),
    ("build_home_snapshots", "Home pages build", timedelta(hours=6)),
    ("sync_tmdb_new_releases", "New movies (just released)", timedelta(hours=30)),
    # the command keeps its old name (its JobRun history, the crontab): it runs every Sunday
    ("sync_tmdb_monthly", "New titles from TMDB (weekly)", timedelta(days=8)),
    ("train_ranker", "Ranker training", None),
    ("build_embeddings", "Embeddings / more like this", timedelta(hours=30)),
    ("backfill_ratings", "Age ratings from TMDB", timedelta(hours=30)),
    ("clean_db", "Database cleanup", timedelta(hours=30)),
    ("rebuild_title_indexes", "Search index (keywords, studios, networks)", timedelta(hours=30)),
    ("tag_titles", "AI title tags", timedelta(hours=30)),
    ("daily_checkup", "Daily check-up", timedelta(hours=30)),
    ("sync_tmdb_related", "TMDB related / other names", timedelta(hours=30)),
    ("translate_titles", "AI translations (missing overviews)", timedelta(hours=30)),
    ("fix_actor_duplicates", "Actor duplicates (monthly)", timedelta(days=32)),
    # shell scripts, recorded by manage.py record_job
    ("backup_db", "Database backup (to Google Drive)", timedelta(hours=30)),
    ("backup_restore_test", "Backup restore test", timedelta(days=8)),
    ("weekly_cleanup", "Server cleanup (Docker, logs)", timedelta(days=8)),
    # the mini PC's nightly trailer-worker/run.sh, seen when it imports its clips
    ("import_trailer_results", "Trailer clips (mini PC)", timedelta(hours=30)),
    # the mini PC's nightly provider_scraper/run.sh: new providers / domains found on streaming sites
    ("import_providers", "Provider scout (mini PC)", timedelta(hours=30)),
]

# For the dashboard's jobs card: the group a job is shown in, when cron runs it (ops/crontab, UTC)
# and what it does for the site, in a few words.
JOB_GROUPS = ["Catalog", "Recommendations & home pages", "AI", "Health & safety"]
JOB_INFO = {
    "sync_tmdb_new_releases": ("Catalog", "Every night 00:30", "Adds the movies just out: trending today, in theatres, new on streaming"),
    "sync_tmdb_monthly": ("Catalog", "Sundays 00:45", "Adds popular movies and shows the catalog lacks (500+ votes)"),
    "sync_tmdb_daily_episodes": ("Catalog", "Every 3 hours", "New shows on the air and their new episodes, plus translations"),
    "clean_db": ("Catalog", "Every night 04:30, 2 h 30 max", "Removes duplicates, refreshes each title from TMDB once a month"),
    "backfill_ratings": ("Catalog", "Every night 02:00", "Age ratings of new titles (what Kids profiles may see)"),
    "sync_tmdb_related": ("Catalog", "Every night 03:00", "TMDB's related titles and other names (search in every language)"),
    "rebuild_title_indexes": ("Catalog", "Every night 07:15", "Makes new and refreshed titles findable by keyword, studio, network"),
    "fix_actor_duplicates": ("Catalog", "1st of the month 02:30", "Merges actors listed twice on a title"),
    "import_trailer_results": ("Catalog", "Every night (mini PC)", "Trailer preview clips cut by the mini PC"),
    "build_embeddings": ("Recommendations & home pages", "Every night 08:00 (new titles), Sundays 09:30 (all)",
                         '"More like this" and the taste vectors the recommendations use'),
    "train_ranker": ("Recommendations & home pages", "Sundays 07:30", "Learns from last month's clicks how to order the rows"),
    "build_home_snapshots": ("Recommendations & home pages", "Every 2 hours", "Builds each profile's home page"),
    "notify_new_episodes": ("Recommendations & home pages", "Every 3 hours", "Alerts for new episodes of followed shows"),
    "tag_titles": ("AI", "Every night 04:00", "Moods / themes / pacing tags by Claude (batch, within the AI budget)"),
    "translate_titles": ("AI", "Every night 03:30", "Overviews TMDB lacks, translated by Claude (within the AI budget)"),
    "check_providers": ("Health & safety", "Every 15 minutes", "Checks streaming providers are up, switches dead domains"),
    "import_providers": ("Health & safety", "Every night 04:30 (mini PC)",
                         "New streaming providers / domains found on streaming sites by the mini PC"),
    "daily_checkup": ("Health & safety", "Every day 07:00", "Emails staff when something on this page goes wrong"),
    "backup_db": ("Health & safety", "Every night 01:30", "Database backup, copied to Google Drive"),
    "backup_restore_test": ("Health & safety", "Wednesdays 02:15", "Restores the newest backup in a test database and counts rows"),
    "weekly_cleanup": ("Health & safety", "Sundays 03:00", "Frees disk space (old Docker images, system logs)"),
}

AI_FEATURES = {  # AiUsage.feature -> label on the AI spend card
    "recap": "Catch me up (users)",
    "ask": "Ask Taurus (users)",
    "tags": "Title tags (job)",
    "tags_setup": "First catalog tagging (not counted)",
    "checkup": "Daily check-up (job)",
    "translate": "Missing translations (job)",
}


def _ai_help(now):
    """"Does the AI help?" (reco/ai_report.py, roadmap 8.7): last 28 days."""
    from reco.ai_report import report

    return report(days=28, now=now)


def _ai_spend(now):
    """This month's Claude spending against the US$5 budget (reco/ai_budget.py)."""
    from reco import ai_budget
    from reco.models import AiUsage

    month = AiUsage.objects.filter(created_at__gte=ai_budget._month_start(now)).exclude(feature=ai_budget.ALERT_FEATURE)
    by_feature = {}
    for feature, usd in month.values_list("feature", "cost_usd"):
        by_feature[feature] = by_feature.get(feature, 0.0) + usd
    budget = ai_budget.monthly_budget()
    total = ai_budget.spent_this_month()
    caps = ai_budget.feature_caps()
    rows = []
    for feature, usd in sorted(by_feature.items(), key=lambda kv: -kv[1]):
        cap = caps.get(feature)
        rows.append({
            "label": AI_FEATURES.get(feature, feature),
            "usd": usd,
            "today": ai_budget.spent_today(feature),
            "cap": f"US${cap[0]:.2f} a day, {cap[1]} per user" if cap else "",
            "exempt": feature in ai_budget.EXEMPT,
        })
    return {
        "total": total, "budget": budget, "pct": min(100, round(100 * total / budget)) if budget else 0,
        "jobs_left": ai_budget.jobs_budget_left(), "rows": rows,
    }


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
        .annotate(n=Count("id"), ok=Count("id", filter=Q(worked=True)),
                  sb_n=Count("id", filter=Q(sandboxed=True)),
                  sb_ok=Count("id", filter=Q(sandboxed=True, worked=True)))
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
            # "Block pop-ups" (9.1): the plays with the player sandboxed, and how often they played
            "sandboxed_plays": pl.get("sb_n", 0),
            "sandboxed_success": _pct(pl.get("sb_ok", 0), pl.get("sb_n", 0)),
        })
    most_plays = max([r["plays"] for r in rows] + [1])
    for r in rows:
        r["plays_width"] = round(100 * r["plays"] / most_plays, 1)
    return sorted(rows, key=lambda r: (-r["plays"], r["p"].priority))


def _duration(d):
    if d is None:
        return ""
    secs = int(d.total_seconds())
    if secs < 60:
        return f"{secs} s"
    if secs < 3600:
        return f"{secs // 60} min"
    return f"{secs // 3600} h {secs % 3600 // 60:02d}"


STATE_ORDER = {"failed": 0, "running": 1, "late": 2, "never": 3, "ok": 4}


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
        group, when, what = JOB_INFO.get(name, ("Other", "", ""))
        lines = [ln for ln in ((last.error or last.summary) if last else "").splitlines() if ln.strip()]
        rows.append({"name": name, "label": label, "last": last, "runs": runs, "failures": failures,
                     "state": state, "late_after": late_after, "group": group, "when": when, "what": what,
                     "result": lines[-1] if lines else "", "details": "\n".join(lines),
                     "duration": _duration(last.duration) if last else ""})
    return rows


def _job_board(jobs):
    """The jobs card: a count per status, then the jobs by group (problems first in each)."""
    counts = {state: sum(1 for j in jobs if j["state"] == state) for state in STATE_ORDER}
    groups = []
    for group in JOB_GROUPS + ["Other"]:
        rows = sorted((j for j in jobs if j["group"] == group), key=lambda j: STATE_ORDER[j["state"]])
        if rows:
            groups.append({"name": group, "jobs": rows,
                           "problems": sum(1 for j in rows if j["state"] in ("failed", "late"))})
    return {"counts": counts, "groups": groups, "all_ok": counts["ok"] == len(jobs)}


def _freshness(titles_total):
    """What the jobs keep up to date, in % of the catalog, and which job fills each line."""
    from django.db.models import Exists, OuterRef

    from reco.models import TitleEmbedding
    from .models import TitleKeyword

    def row(label, done, job, warn_below):
        pct = _pct(done, titles_total)
        return {"label": label, "done": done, "missing": max(titles_total - done, 0), "pct": pct, "job": job,
                "ok": pct is None or pct >= warn_below}

    month_ago = timezone.now() - timedelta(days=30)
    no_index = (Title.objects.exclude(keywords=[])
                .filter(~Exists(TitleKeyword.objects.filter(title_id=OuterRef("pk")))).count())
    with_blob = TitleEmbedding.objects.filter(vector_blob__isnull=False).exclude(vector_blob=b"").count()
    return [
        row("Read on TMDB in the last 30 days", Title.objects.filter(tmdb_checked_at__gte=month_ago).count(),
            "Database cleanup", 90),
        row("Findable by keyword", titles_total - no_index, "Search index", 99),
        row('In "more like this" and recommendations', with_blob, "Embeddings", 99),
        row("With an age rating", Title.objects.exclude(maturity=None).count(), "Age ratings", 90),
        row("With related titles / other names", Title.objects.exclude(related_synced_at=None).count(),
            "TMDB related", 90),
    ]


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
        "visitors": visitor_stats(now),
        "live": live_stats(now),
        "plays": plays,
        "plays_top": plays_top,
        "plays_total": sum(d["n"] for d in plays),
        "providers": _providers(now),
        "jobs": _job_board(_jobs(now)),
        "freshness": _freshness(titles_total),
        "titles_total": titles_total,
        "ai": _ai_spend(now),
        "ai_help": _ai_help(now),
        "snapshots_total": snapshots.count(),
        "snapshots_failed": snapshots.exclude(last_error="").count(),
        "snapshots_oldest": snapshots.order_by("built_at").values_list("built_at", flat=True).first(),
        "profiles_without_snapshot": Profile.objects.filter(home_snapshot__isnull=True).count(),
        "failed_snapshots": failed_snapshots,
        "top_titles": top_titles,
        "catalog": [
            ("Titles", titles_total),
            ("Episodes", Episode.objects.count()),
            ("Accounts / profiles", f"{User.objects.count()} / {Profile.objects.count()}"),
        ],
    }
    return TemplateResponse(request, "admin/dashboard.html", context)


def dashboard_live_view(request):
    """Who is on the site right now: the dashboard's Live card asks every 15 s."""
    return JsonResponse(live_stats(timezone.now()))
