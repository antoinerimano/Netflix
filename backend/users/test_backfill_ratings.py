"""Age ratings from TMDB (manage.py backfill_ratings, nightly since roadmap 8.3): most popular titles
first, a title TMDB has no rating for is still marked asked, one TMDB keeps failing on is left for
the next run (not fetched again and again now), --limit. TMDB is faked."""
import os
from io import StringIO
from types import SimpleNamespace as NS
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from .models import Title


def movie_answer(cert):
    dates = [{"certification": cert}] if cert else []
    return {"adult": False, "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": dates}]}}


@mock.patch.dict(os.environ, {"TMDB_API_KEY": "test-key"})
class BackfillRatingsTests(TestCase):
    def setUp(self):
        self.popular = Title.objects.create(type="movie", title="Popular", tmdb_id=1, popularity=90)
        self.middle = Title.objects.create(type="movie", title="Middle", tmdb_id=2, popularity=50)
        self.unrated = Title.objects.create(type="movie", title="Unrated", tmdb_id=3, popularity=40)
        # the most popular: without setting it aside it was picked again at every step, pushing others out
        self.broken = Title.objects.create(type="movie", title="Broken", tmdb_id=4, popularity=95)
        self.answers = {1: ("ok", movie_answer("PG-13")), 2: ("ok", movie_answer("R")),
                        3: ("ok", movie_answer("")), 4: ("fail", None)}
        self.asked = []

    def fake_get(self, url, params=None, timeout=None):
        tmdb_id = int(url.rstrip("/").split("/")[-1])
        self.asked.append(tmdb_id)
        kind, data = self.answers[tmdb_id]
        if kind == "fail":
            return NS(status_code=500, ok=False, headers={}, json=lambda: {})
        return NS(status_code=200, ok=True, headers={}, json=lambda: data)

    def run_cmd(self, *args):
        out = StringIO()
        session = mock.MagicMock()
        session.get.side_effect = self.fake_get
        with mock.patch("users.management.commands.backfill_ratings.requests.Session", return_value=session), \
                mock.patch("users.management.commands.backfill_ratings.time.sleep"):
            call_command("backfill_ratings", "--workers", "1", "--batch", "2", *args, stdout=out)
        return out.getvalue()

    def test_rates_most_popular_first(self):
        self.run_cmd()
        for t in (self.popular, self.middle, self.unrated, self.broken):
            t.refresh_from_db()
        self.assertEqual((self.popular.certification, self.popular.maturity), ("PG-13", 2))
        self.assertEqual(self.middle.certification, "R")
        # TMDB has none: still marked asked, so it isn't asked every night
        self.assertEqual((self.unrated.maturity, self.unrated.rating_synced_at is not None), (None, True))
        # TMDB kept failing: left for the next run, asked only once in this one (5 attempts)
        self.assertIsNone(self.broken.rating_synced_at)
        self.assertEqual(self.asked.count(4), 5)
        self.assertEqual(self.asked[:5], [4] * 5)  # the most popular first (it fails: 5 attempts)
        self.assertEqual(self.asked[5:], [1, 2, 3])  # then the others, in popularity order

    def test_limit_takes_the_most_popular(self):
        self.answers[4] = ("ok", movie_answer("G"))
        self.run_cmd("--limit", "1")
        self.assertEqual(self.asked, [4])
        self.assertEqual(Title.objects.exclude(rating_synced_at=None).count(), 1)
