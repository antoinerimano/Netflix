"""Your year (reco/stats.py): time, counts, streaks, months, genres, titles, actors."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import Actor, Episode, Profile, Season, Title, TVShowExtras, User
from .models import WatchEvent
from .stats import _streaks


class StatsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="en")
        self.kid = Profile.objects.create(user=self.user, name="K", age_restriction="PG", is_kids=True, language_preference="en")
        self.bob = Profile.objects.create(user=self.other, name="B", age_restriction="NC-17", language_preference="en")
        self.client.force_authenticate(self.user)

        self.heat = Title.objects.create(type="movie", title="Heat", runtime_minutes=170, genre="Crime, Drama", maturity=3,
                                         cast=["Al Pacino", "Robert De Niro", "Val Kilmer", "Jon Voight", "Tom Sizemore", "Extra Person"])
        self.godfather = Title.objects.create(type="movie", title="The Godfather", genre="Crime", maturity=3,
                                              cast=["Marlon Brando", "Al Pacino"])  # no runtime: 100
        self.show = Title.objects.create(type="tv", title="Night Shift", genre="Drama", maturity=1, cast=["Nurse One"])
        TVShowExtras.objects.create(title=self.show, episode_run_time=[50])
        season = Season.objects.create(tv=self.show, season_number=1)
        Episode.objects.create(season=season, episode_number=1, runtime=40)
        Episode.objects.create(season=season, episode_number=2)  # no runtime: the show's usual 50
        for title, name in ((self.heat, "Al Pacino"), (self.heat, "Extra Person"), (self.godfather, "Al Pacino"),
                            (self.heat, "Robert De Niro")):
            Actor.objects.create(title=title, name=name, name_norm=name.lower(), tmdb_id=hash(name) % 100000,
                                 profile_path="/p.jpg" if name == "Al Pacino" else None)

        self.event(self.heat, date(2025, 3, 1))
        self.event(self.godfather, date(2025, 3, 2))
        self.event(self.show, date(2025, 3, 3), 1, 1)
        self.event(self.show, date(2025, 7, 9), 1, 2)
        self.event(self.show, date(2025, 7, 9), 0, 0)  # an old entry: episode unknown, the show's usual 50 min
        self.event(self.heat, date(2024, 12, 31))       # another year

    def event(self, title, day, season=0, episode=0, profile=None):
        WatchEvent.objects.create(profile=profile or self.profile, title=title, season_number=season, episode_number=episode,
                                  watched_on=day, watched_at=datetime.combine(day, time(20), tzinfo=dt_timezone.utc))

    def stats(self, year=None, profile=None):
        q = f"&year={year}" if year else ""
        return self.client.get(f"/api/stats/?profileId={(profile or self.profile).id}{q}")

    def test_the_year_in_numbers(self):
        res = self.stats(2025)
        self.assertEqual(res.status_code, 200)
        d = res.data
        self.assertEqual(d["years"], [2025, 2024])
        self.assertEqual(d["minutes"], 170 + 100 + 40 + 50 + 50)
        self.assertEqual((d["titles"], d["movies"], d["shows"], d["episodes"], d["days"]), (3, 2, 1, 2, 4))
        self.assertEqual(d["months"][2], 170 + 100 + 40)
        self.assertEqual(d["months"][6], 50 + 50)
        self.assertEqual(d["longest_streak"], {"days": 3, "from": "2025-03-01", "to": "2025-03-03"})
        self.assertEqual(d["first"]["title"]["title"], "Heat")

    def test_genres_share_the_time_and_add_up(self):
        genres = {g["genre"]: g for g in self.stats(2025).data["top_genres"]}
        self.assertEqual(genres["Crime"]["minutes"], 85 + 100)  # half of Heat + The Godfather
        self.assertEqual(genres["Drama"]["minutes"], 85 + 140)  # half of Heat + the show
        self.assertAlmostEqual(sum(g["share"] for g in genres.values()), 1, places=2)

    def test_top_titles_and_lead_actors(self):
        d = self.stats(2025).data
        self.assertEqual([t["title"]["title"] for t in d["top_titles"]], ["Heat", "Night Shift", "The Godfather"])
        self.assertEqual(d["top_titles"][1]["episodes"], 2)
        names = [a["name"] for a in d["top_actors"]]
        self.assertEqual(names[0], "Al Pacino")  # in two titles
        self.assertEqual(d["top_actors"][0]["titles"], 2)
        self.assertTrue(d["top_actors"][0]["photo"].endswith("/p.jpg"))
        self.assertNotIn("Extra Person", names)  # sixth billed: not a lead

    def test_default_year_is_the_latest_with_history(self):
        self.assertEqual(self.stats().data["year"], 2025)

    def test_streaks(self):
        today = date(2026, 5, 10)
        days = [date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3), date(2026, 5, 8), date(2026, 5, 9), date(2026, 5, 10)]
        best, current = _streaks(days, today)
        self.assertEqual((best[0], current), (3, 3))
        self.assertEqual(_streaks(days, today + timedelta(days=3))[1], 0)  # broken: no current streak
        self.assertEqual(_streaks([], today), (None, 0))

    def test_kids_age_and_other_accounts(self):
        self.event(self.heat, date(2025, 1, 1), profile=self.kid)
        self.event(self.show, date(2025, 1, 2), 1, 1, profile=self.kid)
        self.assertEqual(self.stats(2025, self.kid).data["titles"], 1)  # the R movie isn't counted
        self.assertEqual(self.stats(profile=self.bob).status_code, 404)

    def test_no_history(self):
        WatchEvent.objects.all().delete()
        d = self.stats().data
        self.assertEqual((d["years"], d["minutes"], d["first"], d["longest_streak"]), ([], 0, None, None))
        self.assertEqual(d["year"], timezone.localdate().year)
