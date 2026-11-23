# users/checkup.py
"""
The daily check-up (manage.py daily_checkup, roadmap 8.2): is anything wrong with the site's own
jobs and server? An email to staff only when something is.

1. find_problems(): plain checks, no AI, nothing paid:
   - a scheduled job (dashboard JOBS) that failed (reported the day it failed, not every day after),
     is late, or has been "running" for hours. Also the server's shell scripts (the database
     backup, the weekly cleanup: manage.py record_job) and the mini PC's trailer clips (seen when
     it imports them): a backup that fails, or a machine that stops, is reported like a job;
   - the site's HTTPS certificate expiring within 14 days (certbot renews it at 30: it failed);
   - home pages that failed to build, or none rebuilt for 12 hours;
   - an AI tag batch still not collected after 26 hours (batches end within 24);
   - the disk under 10 % or 5 GB free;
   - the AI budget (reco/ai_budget.py) at 80 % or more of the month;
   - settings (users/config_check.py, docs/CONFIG.md): one missing, the debug mode on in
     production, or a key TMDB / Anthropic / the mail server now refuses;
   - more trailer preview clips that may be the wrong video than at the last check-up: old
     trailers/{tmdb_id}.mp4 clips (the show / movie sharing the TMDB id could have overwritten
     them), or clips that aren't the clip of the title's current trailer (users/trailers.py).
     Counted every morning (the line "Preview clips: ..." of the run, kept on its JobRun), reported
     only when a count goes up, so a known backlog doesn't send an email every day.
2. Nothing found: no email, no AI ("All OK").
3. Something found: Claude Haiku 5.5 turns the facts into a short email (what broke, the likely
   cause from the error text, the command to fix it, picked only from FIX_COMMANDS), within the
   background jobs' AI budget (feature "checkup", ~US$0.001 a time). Budget used up, no key, or an
   API error: the same email without the AI part. The alert never depends on the AI.
"""
import logging
import re
import shutil
import socket
import ssl
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import urlparse

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"
STUCK_AFTER = timedelta(hours=6)          # a job "running" this long was killed or hangs
FAILED_REPORTED_FOR = timedelta(hours=26) # a failure is reported once (the morning after), not every
                                          # day until the job's next run (weekly jobs: a week of alerts)
SNAPSHOTS_STALE = timedelta(hours=12)     # home pages are rebuilt every 2 hours
TAG_BATCH_LATE = timedelta(hours=26)      # a Message Batch ends within 24 hours
DISK_MIN_FREE_PCT = 10
DISK_MIN_FREE_GB = 5
CERT_MIN_DAYS = 14                        # certbot renews at 30 days left (weekly): it failed twice
AI_COST_CAP = 0.01                        # US$: one check-up email never costs more than this

# What to run on the server for each job (from ops/crontab / scripts/): the only commands the AI
# may suggest
_EXEC = "cd /opt/taurus && docker compose exec -T backend python manage.py"
FIX_COMMANDS = {
    "check_providers": "/opt/taurus/scripts/cron_check_providers.sh",
    "sync_tmdb_daily_episodes": "/opt/taurus/scripts/cron_sync_episodes.sh",
    "notify_new_episodes": "/opt/taurus/scripts/cron_sync_episodes.sh",
    "build_home_snapshots": "/opt/taurus/scripts/cron_build_home.sh",
    "sync_tmdb_monthly": f"{_EXEC} sync_tmdb_monthly --pages 20 --min-votes 500 --verbose-adds --only-created",
    "train_ranker": f"{_EXEC} train_ranker",
    "build_embeddings": f"{_EXEC} build_embeddings --missing   (all titles: --type all --topk 80 --model-name all-MiniLM-L6-v2)",
    "sync_tmdb_new_releases": f"{_EXEC} sync_tmdb_new_releases   (log: /var/log/taurus_new_releases.log)",
    "rebuild_title_indexes": f"{_EXEC} rebuild_title_indexes   (log: /var/log/taurus_index.log)",
    "backup_restore_test": "/opt/taurus/scripts/test_backup_restore.sh   (log: /var/log/taurus_restore_test.log)",
    "backfill_ratings": f"{_EXEC} backfill_ratings",
    "clean_db": f"{_EXEC} clean_db --dedupe --backfill-tmdb --tv-sync-episodes --tv-max-seasons 2 --stale-days 30 --max-minutes 150",
    "fix_actor_duplicates": f"{_EXEC} fix_actor_duplicates",
    "backup_db": "/opt/taurus/scripts/backup_db.sh   (log: /var/log/taurus_backup.log)",
    "weekly_cleanup": "/usr/local/bin/weekly-cleanup.sh   (log: /var/log/weekly-cleanup.log)",
    "import_trailer_results": "on the mini PC: tail -50 ~/taurus/trailer-worker/run.log   (then: crontab -l, ~/taurus/trailer-worker/run.sh)",
    "import_providers": "on the mini PC: tail -50 ~/taurus/provider_scraper/run.log   (then: crontab -l, ~/taurus/provider_scraper/run.sh)",
    "tag_titles": f"{_EXEC} tag_titles",
    "sync_tmdb_related": f"{_EXEC} sync_tmdb_related",
    "translate_titles": f"{_EXEC} translate_titles",
"_previews": f"{_EXEC} export_trailer_jobs > jobs.json   (then trailer-worker/, then: "
                 f"{_EXEC} import_trailer_results --clear-rejected - < results.json)",
    "_logs": "cd /opt/taurus && docker compose logs --tail 200 backend",
    "_restart": "cd /opt/taurus && docker compose restart backend",
    "_disk": "df -h / && docker system df && docker image prune -f",
    "_cert": "cd /opt/taurus && docker compose run --rm certbot renew && docker compose exec -T nginx nginx -s reload",
}

SYSTEM = """You are the on-call assistant of a small streaming website (Django + MySQL in docker
compose, on one server, app in /opt/taurus). Every morning a script checks the site and sends you
the problems it found. Write the email the site's owner will read on their phone.
- One short section per problem: what is wrong (plain words), the likely cause (read the error
  text given; say "unknown" when it doesn't tell), and what to do.
- Only suggest commands from the "Commands" list you are given, copied exactly. Never invent one.
- Plain text, no Markdown, no greeting or sign-off, under 250 words. The most serious problem first."""


def every(delta):
    """timedelta -> "hour", "8 hours", "35 days" (for "It normally runs at least every ...")."""
    hours = round(delta.total_seconds() / 3600)
    if hours % 24 == 0 and hours >= 24:
        days = hours // 24
        return "day" if days == 1 else f"{days} days"
    return "hour" if hours == 1 else f"{hours} hours"


_CLIPS_LINE_RE = re.compile(r"^Preview clips: (\d+) old-format, (\d+) not their trailer's clip$", re.MULTILINE)


def preview_clip_counts():
    """{"legacy", "mismatch"}: titles whose preview clip may not be the right video.
    legacy: an old trailers/{tmdb_id}.mp4 clip. mismatch: any other clip that isn't
    previews/{type}/{tmdb_id}-{key of the current trailer}.mp4 (made from an older trailer, the
    trailer is gone, or another type's folder)."""
    from .models import Title
    from .trailers import clip_answers

    legacy = mismatch = 0
    rows = Title.objects.exclude(trailer_clip_url="").values_list(
        "type", "tmdb_id", "trailer_url", "trailer_clip_url", "trailer_clip_for")
    for kind, tmdb_id, trailer, clip, clip_for in rows.iterator(chunk_size=2000):
        if "/trailers/" in clip:
            legacy += 1
            continue
        # a clip made from another video because TMDB's couldn't be used is the right one
        if tmdb_id is None or not clip_answers(clip, clip_for, kind, tmdb_id, trailer):
            mismatch += 1
    return {"legacy": legacy, "mismatch": mismatch}


def clips_line(counts):
    """The line the command prints (and its JobRun keeps): the next check-up compares with it."""
    return f"Preview clips: {counts['legacy']} old-format, {counts['mismatch']} not their trailer's clip"


def previous_clip_counts():
    """The counts of the last finished check-up that printed them, None if none did."""
    from .models import JobRun

    for summary in (JobRun.objects.filter(name="daily_checkup", ok=True).exclude(finished_at=None)
                    .order_by("-started_at").values_list("summary", flat=True)[:5]):
        m = _CLIPS_LINE_RE.search(summary or "")
        if m:
            return {"legacy": int(m.group(1)), "mismatch": int(m.group(2))}
    return None


def clip_problem(counts, previous):
    """A problem when a count went up since the last check-up (or the first time, when not 0)."""
    previous = previous or {"legacy": 0, "mismatch": 0}
    up = [k for k in ("legacy", "mismatch") if counts[k] > previous[k]]
    if not up:
        return None
    return {"kind": "preview_clips", "what": f"Trailer preview clips that may be the wrong video: "
            f"{counts['legacy']} old-format (was {previous['legacy']}), {counts['mismatch']} not the clip "
            f"of the title's trailer (was {previous['mismatch']})",
            "detail": "Old trailers/{tmdb_id}.mp4 clips can be another title's (a show and a movie share "
                      "TMDB ids); the others were made from an older trailer, or the trailer is gone. "
                      "trailer-worker/ remakes them; --clear-rejected removes the old ones it turns down.",
            "fix": FIX_COMMANDS["_previews"]}


def cert_days_left(url=None):
    """Days before the HTTPS certificate of SITE_URL expires, None when it can't be read (not
    https, a local address, the site unreachable: other checks see a site that is down)."""
    parts = urlparse(url if url is not None else settings.SITE_URL)
    host = parts.hostname or ""
    if parts.scheme != "https" or host in ("", "localhost", "127.0.0.1") or host.endswith(".local"):
        return None
    try:
        with socket.create_connection((host, parts.port or 443), timeout=10) as sock:
            with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as tls:
                not_after = tls.getpeercert()["notAfter"]
    except (OSError, KeyError, ValueError) as exc:  # ssl.SSLError (expired...) is an OSError
        log.warning("check-up: can't read the HTTPS certificate of %s: %s", host, exc)
        return None
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=dt_timezone.utc)
    return (expires - datetime.now(dt_timezone.utc)).days


def find_problems(now=None, clips=None):
    """[{"kind", "what", "detail", "fix"}]: everything wrong right now (no AI, nothing paid).
    clips: preview_clip_counts(), when the caller already has them."""
    from reco import ai_budget
    from reco.models import RecoHomeSnapshot, TagBatch

    from .dashboard import JOBS, _jobs

    now = now or timezone.now()
    problems = []

    labels = {name: label for name, label, _ in JOBS}
    for j in _jobs(now):
        last, name = j["last"], j["name"]
        fix = FIX_COMMANDS.get(name, f"{_EXEC} {name}")
        if j["state"] == "failed" and now - (last.finished_at or last.started_at) <= FAILED_REPORTED_FOR:
            problems.append({"kind": "job_failed", "what": f"{labels[name]} ({name}) failed",
                             "detail": (last.error or last.summary or "")[-800:], "fix": fix})
        elif j["state"] == "running" and now - last.started_at > STUCK_AFTER:
            problems.append({"kind": "job_stuck", "what": f"{labels[name]} ({name}) has been running "
                             f"since {timezone.localtime(last.started_at):%Y-%m-%d %H:%M}",
                             "detail": "Killed, or hanging (no end recorded).", "fix": fix})
        elif j["state"] == "late" or (j["state"] == "never" and j["late_after"]):
            when = f"last run {timezone.localtime(last.started_at):%Y-%m-%d %H:%M}" if last else "never ran"
            problems.append({"kind": "job_late", "what": f"{labels[name]} ({name}) is late: {when}",
                             "detail": f"It normally runs at least every {every(j['late_after'])}. The cron may "
                                       f"be off, or the server was down.", "fix": fix})

    failed = RecoHomeSnapshot.objects.exclude(last_error="")
    if failed.exists():
        sample = failed.order_by("-built_at").values_list("last_error", flat=True).first()
        problems.append({"kind": "snapshots_failed", "what": f"{failed.count()} home pages failed to build",
                         "detail": (sample or "")[-500:], "fix": FIX_COMMANDS["build_home_snapshots"]})
    newest = RecoHomeSnapshot.objects.order_by("-built_at").values_list("built_at", flat=True).first()
    if newest and now - newest > SNAPSHOTS_STALE:
        problems.append({"kind": "snapshots_stale", "what": "No home page rebuilt for "
                         f"{int((now - newest).total_seconds() // 3600)} hours",
                         "detail": "They are rebuilt every 2 hours.", "fix": FIX_COMMANDS["build_home_snapshots"]})

    late_batches = TagBatch.objects.filter(collected_at__isnull=True, created_at__lt=now - TAG_BATCH_LATE)
    if late_batches.exists():
        problems.append({"kind": "tag_batch_late", "what": f"{late_batches.count()} AI tag batch(es) not "
                         "collected after 26 hours", "detail": ", ".join(late_batches.values_list("batch_id", flat=True)),
                         "fix": FIX_COMMANDS["tag_titles"]})

    try:
        disk = shutil.disk_usage("/")
        free_pct, free_gb = 100 * disk.free / disk.total, disk.free / 1e9
        if free_pct < DISK_MIN_FREE_PCT or free_gb < DISK_MIN_FREE_GB:
            problems.append({"kind": "disk", "what": f"Disk almost full: {free_gb:.1f} GB free ({free_pct:.0f} %)",
                             "detail": "Docker images, logs and database backups grow over time.",
                             "fix": FIX_COMMANDS["_disk"]})
    except OSError:
        pass

    days = cert_days_left()
    if days is not None and days < CERT_MIN_DAYS:
        problems.append({"kind": "cert", "what": f"The HTTPS certificate expires in {max(days, 0)} days",
                         "detail": "certbot renews it every Monday once 30 days are left: the renewals failed "
                                   "(log: /var/log/certbot-renew.log). Expired, browsers block the site.",
                         "fix": FIX_COMMANDS["_cert"]})

    budget, spent = ai_budget.monthly_budget(), ai_budget.spent_this_month()
    if budget and spent >= 0.8 * budget:
        problems.append({"kind": "ai_budget", "what": f"AI budget: US${spent:.2f} of US${budget:.2f} used "
                         "this month", "detail": "At 100 % every AI feature pauses until next month (the site "
                         "keeps working).", "fix": "Nothing to run: see the dashboard's AI spend card."})

    problem = clip_problem(clips if clips is not None else preview_clip_counts(), previous_clip_counts())
    if problem:
        problems.append(problem)

    # settings: missing ones, debug mode on, keys a service now refuses (users/config_check.py)
    from .config_check import config_problems
    problems += config_problems()
    return problems


def facts_text(problems):
    lines = []
    for i, p in enumerate(problems, 1):
        lines.append(f"{i}. {p['what']}")
        if p["detail"]:
            lines.append(f"   Details: {p['detail']}")
        lines.append(f"   Fix: {p['fix']}")
    return "\n".join(lines)


def _client():
    import anthropic

    return anthropic.Anthropic(timeout=60.0, max_retries=1)


def ai_summary(problems):
    """Claude's short email about the problems, or "" (no budget left, no key, error, refusal)."""
    from reco import ai_budget

    if ai_budget.jobs_budget_left() < AI_COST_CAP:
        return ""
    commands = "\n".join(sorted(set(FIX_COMMANDS.values())))
    prompt = f"Problems found this morning:\n{facts_text(problems)}\n\nCommands:\n{commands}"
    try:
        msg = _client().messages.create(
            model=MODEL, max_tokens=2048, system=SYSTEM, output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # anthropic.APIError, no key...: the email goes without it
        log.warning("check-up AI summary failed: %s", exc)
        return ""
    ai_budget.record("checkup", msg.usage, MODEL)
    if msg.stop_reason != "end_turn":
        return ""
    return "\n\n".join(b.text.strip() for b in msg.content if b.type == "text" and b.text.strip())


def staff_emails():
    from .models import User

    return list(User.objects.filter(is_staff=True, is_active=True).exclude(email="").values_list("email", flat=True))


def dashboard_url():
    return f"{settings.SITE_URL.rstrip('/')}/{settings.ADMINADMIN_URL.strip('/')}/dashboard/"


def send_report(problems, summary):
    """The email to staff: the AI's summary when there is one, then the facts. Returns how many got it."""
    to = staff_emails()
    if not to:
        return 0
    n = len(problems)
    subject = f"Check-up: {n} problem{'s' if n > 1 else ''} on the site"
    parts = [summary] if summary else []
    parts.append(("The facts:\n" if summary else "") + facts_text(problems))
    parts.append(f"Dashboard: {dashboard_url()}")
    send_mail(subject, "\n\n".join(parts), None, to)
    return len(to)
