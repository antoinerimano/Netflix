"""manage.py clean_db --backfill-tmdb, nightly: which titles a run takes (--stale-days), that it
marks the ones TMDB answered for, and that a run stopped by --max-minutes leaves the rest for the
next. A fake TMDB client: nothing goes to the network."""
from datetime import timedelta
from io import StringIO
from unittest import mock

import requests
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .models import JobRun, Title

CMD = "users.management.commands.clean_db"


def http_error(status):
    return requests.HTTPError(response=mock.Mock(status_code=status))


class FakeTMDb:
    """Answers /movie/{id} with a description; the ids in `errors` raise that HTTP status."""

    def __init__(self, errors=None):
        self.errors = errors or {}
        self.asked = []

    def get(self, path, params=None):
        tmdb_id = int(path.split("/")[2])
        if path.endswith("/external_ids"):
            return {"imdb_id": f"tt{tmdb_id}"}
        self.asked.append(tmdb_id)
        if tmdb_id in self.errors:
            raise http_error(self.errors[tmdb_id])
        return {"title": f"Film {tmdb_id}", "overview": f"About film {tmdb_id}.", "popularity": 1.0}


class CleanDbNightlyTests(TestCase):
    def setUp(self):
        old = timezone.now() - timedelta(days=40)
        recent = timezone.now() - timedelta(days=3)
        self.never_popular = Title.objects.create(type="movie", title="A", tmdb_id=1, popularity=90)
        self.never = Title.objects.create(type="movie", title="B", tmdb_id=2, popularity=10)
        self.old = Title.objects.create(type="movie", title="C", tmdb_id=3, popularity=99, tmdb_checked_at=old)
        self.recent = Title.objects.create(type="movie", title="D", tmdb_id=4, popularity=99, tmdb_checked_at=recent)

    def run_cmd(self, tmdb, *args):
        out = StringIO()
        with mock.patch(f"{CMD}.TMDbClient", return_value=tmdb), mock.patch(f"{CMD}.time.sleep"):
            call_command("clean_db", "--backfill-tmdb", *args, stdout=out)
        return out.getvalue()

    def test_stale_days_takes_never_read_then_oldest_most_popular_first(self):
        tmdb = FakeTMDb()
        self.run_cmd(tmdb, "--stale-days", "30")
        self.assertEqual(tmdb.asked, [1, 2, 3])  # never read (popular first), then read 40 days ago; not D
        for t in (self.never_popular, self.never, self.old):
            t.refresh_from_db()
            self.assertGreater(t.tmdb_checked_at, timezone.now() - timedelta(minutes=1))
        self.never.refresh_from_db()
        self.assertEqual(self.never.description, "About film 2.")  # the empty field filled

    def test_popularity_and_votes_refreshed_the_rest_only_filled(self):
        self.run_cmd(FakeTMDb(), "--stale-days", "30")
        self.never_popular.refresh_from_db()
        self.assertEqual(self.never_popular.popularity, 1.0)  # TMDB's value of today, not the day it was added
        self.assertEqual(self.never_popular.title, "A")      # set already: kept (no --overwrite)

    def test_without_stale_days_every_title(self):
        tmdb = FakeTMDb()
        self.run_cmd(tmdb)
        self.assertEqual(sorted(tmdb.asked), [1, 2, 3, 4])

    def test_not_on_tmdb_is_marked_other_errors_are_tried_again(self):
        self.run_cmd(FakeTMDb(errors={1: 404, 2: 503}), "--stale-days", "30")
        self.never_popular.refresh_from_db()
        self.never.refresh_from_db()
        self.assertIsNotNone(self.never_popular.tmdb_checked_at)  # TMDB doesn't know it: not every night
        self.assertIsNone(self.never.tmdb_checked_at)             # TMDB down: next run

        tmdb = FakeTMDb()
        self.run_cmd(tmdb, "--stale-days", "30")
        self.assertEqual(tmdb.asked, [2])

    def test_max_minutes_stops_and_the_next_run_carries_on(self):
        clock = iter([0, 0, 0, 61 * 60, 61 * 60, 61 * 60])  # the 2nd title is past the hour
        tmdb = FakeTMDb()
        with mock.patch(f"{CMD}.now_s", side_effect=lambda: next(clock, 61 * 60)):
            out = self.run_cmd(tmdb, "--stale-days", "30", "--max-minutes", "60")
        self.assertEqual(tmdb.asked, [1])
        self.assertIn("stopped after 60 minutes, 2 titles left for the next run", out)

        tmdb = FakeTMDb()
        self.run_cmd(tmdb, "--stale-days", "30")
        self.assertEqual(tmdb.asked, [2, 3])  # where it stopped

    def test_dry_run_marks_nothing(self):
        self.run_cmd(FakeTMDb(), "--stale-days", "30", "--dry-run")
        self.assertFalse(Title.objects.filter(tmdb_id__in=[1, 2], tmdb_checked_at__isnull=False).exists())

    def test_the_run_is_on_the_dashboard(self):
        self.run_cmd(FakeTMDb(), "--stale-days", "30")
        run = JobRun.objects.get(name="clean_db")
        self.assertTrue(run.ok)
        self.assertIn("DONE", run.summary)
