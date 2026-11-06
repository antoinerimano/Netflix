"""Upcoming episodes (reco/calendar.py): which shows, which episodes, in which order."""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import Episode, Profile, Season, Title, User
from .calendar import tracked_tmdb_ids
from .models import MyListItem, ShowFollow, WatchProgress


class CalendarTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="en")
        self.kid = Profile.objects.create(user=self.user, name="K", age_restriction="PG", is_kids=True, language_preference="en")
        self.bob = Profile.objects.create(user=self.other, name="B", age_restriction="NC-17", language_preference="en")
        self.client.force_authenticate(self.user)
        self.today = timezone.localdate()

        self.followed = self.show("Followed", tmdb_id=1, maturity=1)
        self.listed = self.show("Listed", tmdb_id=2, maturity=4)        # adults only
        self.watched = self.show("Watched", tmdb_id=3, maturity=1)
        self.ended = self.show("Ended", tmdb_id=4, status="Ended")
        self.popular = self.show("Popular", tmdb_id=5, popularity=99, maturity=1)  # not tracked: a suggestion
        ShowFollow.objects.create(profile=self.profile, title=self.followed)
        MyListItem.objects.create(profile=self.profile, title=self.listed)
        MyListItem.objects.create(profile=self.profile, title=self.followed)  # follow wins as the reason
        WatchProgress.objects.create(profile=self.profile, title=self.watched, season_number=1, episode_number=1)
        ShowFollow.objects.create(profile=self.kid, title=self.listed)
        ShowFollow.objects.create(profile=self.profile, title=self.ended)

        self.ep(self.followed, 1, 1, -3)       # recent
        self.ep(self.followed, 1, 2, 0)        # today: upcoming, first
        self.ep(self.followed, 1, 3, 7)
        self.ep(self.followed, 0, 1, 2)        # a special: left out
        self.ep(self.listed, 2, 5, 1)
        self.ep(self.watched, 3, 1, -10)       # too old for "recent"
        self.ep(self.watched, 3, 2, 45)        # too far for "upcoming"
        self.ep(self.popular, 1, 1, 4)

    def show(self, name, **kw):
        return Title.objects.create(type="tv", title=name, popularity=kw.pop("popularity", 10), **kw)

    def ep(self, show, season, number, days):
        s, _ = Season.objects.get_or_create(tv=show, season_number=season)
        return Episode.objects.create(season=s, episode_number=number, name=f"{show.title} {season}x{number}",
                                      air_date=self.today + timedelta(days=days), still_path="/still.jpg")

    def get(self, profile):
        return self.client.get(f"/api/calendar/?profileId={profile.id}")

    def test_your_shows_recent_and_upcoming(self):
        res = self.get(self.profile)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["tracked"], 4)
        self.assertEqual([e["name"] for e in res.data["recent"]], ["Followed 1x1"])
        self.assertEqual([e["name"] for e in res.data["upcoming"]], ["Followed 1x2", "Listed 2x5", "Followed 1x3"])
        first = res.data["upcoming"][0]
        self.assertEqual(first["air_date"], self.today.isoformat())
        self.assertEqual(first["reason"], "follow")
        self.assertEqual(first["show"]["id"], self.followed.id)
        self.assertEqual(first["still"], "https://image.tmdb.org/t/p/original/still.jpg")
        self.assertEqual(res.data["upcoming"][1]["reason"], "list")

    def test_suggestions_are_popular_shows_coming_back_that_arent_tracked(self):
        res = self.get(self.profile)
        self.assertEqual([s["title"] for s in res.data["suggestions"]], ["Popular"])
        self.assertEqual(res.data["suggestions"][0]["next"],
                         {"season": 1, "episode": 1, "air_date": (self.today + timedelta(days=4)).isoformat()})

    def test_kids_profile_only_sees_its_age(self):
        res = self.get(self.kid)
        self.assertEqual(res.data["tracked"], 0)  # follows an adults-only show
        self.assertEqual(res.data["upcoming"], [])
        self.assertNotIn("Listed", [s["title"] for s in res.data["suggestions"]])

    def test_someone_elses_profile_is_refused(self):
        self.assertEqual(self.get(self.bob).status_code, 404)

    def test_the_sync_refreshes_tracked_shows_that_still_air(self):
        self.assertEqual(sorted(tracked_tmdb_ids()), [1, 2, 3])  # not the ended one, not the untracked one
