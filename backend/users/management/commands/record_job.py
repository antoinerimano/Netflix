"""
manage.py record_job NAME [--failed] [--summary TEXT]: records one finished run (JobRun) of a job
that isn't a Django command, so the dashboard and the daily check-up see it like the others
(failed, or late when it stops running). Called at the end of the server's shell scripts:
scripts/backup_db.sh (backup_db), ops/weekly-cleanup.sh (weekly_cleanup).
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import JobRun


class Command(BaseCommand):
    help = "Record a finished run of a shell-script job (JobRun) for the dashboard and the check-up."

    def add_arguments(self, p):
        p.add_argument("name", help="the job's name in users/dashboard.py JOBS, e.g. backup_db")
        p.add_argument("--failed", action="store_true", help="the run failed")
        p.add_argument("--summary", default="", help="what it did / why it failed (last log line)")

    def handle(self, *args, **o):
        text = (o["summary"] or "").strip()[:2000]
        JobRun.objects.create(name=o["name"][:60], finished_at=timezone.now(), ok=not o["failed"],
                              summary="" if o["failed"] else text, error=text if o["failed"] else "")
        self.stdout.write(f"Recorded {o['name']}: {'failed' if o['failed'] else 'ok'}.")
