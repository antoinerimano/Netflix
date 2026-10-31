# users/jobs.py
# Records each run of a scheduled command (JobRun) for the admin dashboard: when it ran,
# how long, whether it failed, and the last lines it printed.
from collections import deque
from functools import wraps

from django.utils import timezone

SUMMARY_LINES = 6


def tracked(name):
    """Decorator for a management command's handle(): @tracked("sync_tmdb_daily_episodes")."""

    def decorator(handle):
        @wraps(handle)
        def wrapper(self, *args, **options):
            from .models import JobRun

            run = JobRun.objects.create(name=name)
            last_lines = deque(maxlen=SUMMARY_LINES)
            write = self.stdout.write

            def tee(msg="", *a, **kw):  # keep printing, and remember the last lines
                for line in str(msg).splitlines():
                    if line.strip():
                        last_lines.append(line.strip()[:300])
                return write(msg, *a, **kw)

            self.stdout.write = tee
            try:
                result = handle(self, *args, **options)
                run.ok = True
                return result
            except BaseException as exc:  # includes KeyboardInterrupt / SystemExit
                run.ok = False
                run.error = f"{type(exc).__name__}: {exc}"[:2000]
                raise
            finally:
                self.stdout.write = write
                run.finished_at = timezone.now()
                run.summary = "\n".join(last_lines)
                run.save(update_fields=["finished_at", "ok", "summary", "error"])

        return wrapper

    return decorator
