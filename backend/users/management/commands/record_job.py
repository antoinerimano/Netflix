"""
manage.py record_job NAME [--start | --progress | --failed] [--summary TEXT]: records a run (JobRun)
of a job that isn't a Django command, so the dashboard and the daily check-up see it like the
others (failed, or late when it stops running). Called by the server's shell scripts:
scripts/backup_db.sh (backup_db), ops/weekly-cleanup.sh (weekly_cleanup), and by the mini PC's
trailer-worker/run.sh (trailer_worker), which runs ~21 h a night:

    record_job NAME --start              the run began: the dashboard shows it "Running"
    record_job NAME --progress --summary T   still running: T is shown as its last line
    record_job NAME [--failed] --summary T   the run ended: closes the run --start opened
                                             (or records a new one, for a script that never says --start)
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import JobRun

OPEN_FOR = timedelta(days=2)  # a run --start opened longer ago than this is left alone (killed)


class Command(BaseCommand):
    help = "Record a run of a shell-script job (JobRun) for the dashboard and the check-up."

    def add_arguments(self, p):
        p.add_argument("name", help="the job's name in users/dashboard.py JOBS, e.g. backup_db")
        when = p.add_mutually_exclusive_group()
        when.add_argument("--start", action="store_true", help="the run begins (shown as running)")
        when.add_argument("--progress", action="store_true", help="the run is still going: update its last line")
        when.add_argument("--failed", action="store_true", help="the run failed")
        p.add_argument("--summary", default="", help="what it did / why it failed (last log line)")

    def handle(self, *args, **o):
        name, text, now = o["name"][:60], (o["summary"] or "").strip()[:2000], timezone.now()
        if o["start"]:
            JobRun.objects.create(name=name, summary=text)
            self.stdout.write(f"Recorded {name}: running.")
            return
        run = (JobRun.objects.filter(name=name, ok=None, started_at__gte=now - OPEN_FOR)
               .order_by("-started_at").first())
        if o["progress"]:
            if run is None:  # the --start was missed (server down at that moment)
                run = JobRun.objects.create(name=name)
            run.summary = text
            run.save(update_fields=["summary"])
            self.stdout.write(f"Recorded {name}: {text or 'running'}.")
            return
        if run is None:
            run = JobRun(name=name)
        run.finished_at, run.ok = now, not o["failed"]
        run.summary, run.error = ("", text) if o["failed"] else (text, "")
        run.save()
        self.stdout.write(f"Recorded {name}: {'failed' if o['failed'] else 'ok'}.")
