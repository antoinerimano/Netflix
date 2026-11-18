"""
manage.py daily_checkup: is anything wrong with the site's jobs and server? (users/checkup.py)
Nothing wrong: prints "All OK", no email, no AI. Something wrong: one email to staff, explained by
Claude when the background jobs' AI budget allows (~US$0.001), the plain facts otherwise.
Every morning from cron (ops/crontab), after the night's jobs.
  --dry-run   print what would be sent, send nothing (no AI either)
  --no-ai     the email with the plain facts only
"""
from django.core.management.base import BaseCommand

from users import checkup
from users.jobs import tracked


class Command(BaseCommand):
    help = "Check the site's jobs and server; email staff only when something is wrong."

    def add_arguments(self, p):
        p.add_argument("--dry-run", action="store_true", help="print the problems, send nothing")
        p.add_argument("--no-ai", action="store_true", help="no AI summary, the facts only")

    @tracked("daily_checkup")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        clips = checkup.preview_clip_counts()
        problems = checkup.find_problems(clips=clips)
        try:
            if not problems:
                self.stdout.write("All OK: nothing to report.")
                return
            self.stdout.write(f"{len(problems)} problem(s):\n{checkup.facts_text(problems)}")
            if o["dry_run"]:
                return
            summary = "" if o["no_ai"] else checkup.ai_summary(problems)
            sent = checkup.send_report(problems, summary)
            self.stdout.write(f"Emailed {sent} staff account(s){' with the AI summary' if summary else ' (facts only)'}.")
        finally:
            # the last line, so the run's JobRun keeps it: tomorrow's check-up compares with it.
            # Not a dry run's (prefixed): it reported nothing, the rise must still be emailed.
            self.stdout.write(("(dry run) " if o["dry_run"] else "") + checkup.clips_line(clips))
