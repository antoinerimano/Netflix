"""Watch history (reco/history.py): what's recorded, what removing forgets, what pausing stops."""
import importlib
from datetime import timedelta

from django.apps import apps
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import Episode, Profile, Provider, Season, Title, User
from .models import (
    PlaybackOutcome, RecoHomeSnapshot, TitleAction, TitleImpression, TitleRating, WatchEvent, WatchProgress,
)


class HistoryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="en")
        self.kid = Profile.objects.create(user=self.user, name="K", age_restriction="PG", is_kids=True, language_preference="en")
        self.bob = Profile.objects.create(user=self.other, name="B", age_restriction="NC-17", language_preference="en")
        self.client.force_authenticate(self.user)
        self.movie = Title.objects.create(type="movie", title="Heat", maturity=3)
        self.show = Title.objects.create(type="tv", title="Night Shift", maturity=1)
        season = Season.objects.create(tv=self.show, season_number=1)
        for n in (1, 2):
            Episode.objects.create(season=season, episode_number=n, name=f"Shift {n}")
        Provider.objects.create(key="p1", label="P1", domain="https://p1.test", enabled=True)

    def watch(self, title, season=None, episode=None, profile=None):
        return self.client.post("/api/watch-progress/", {
            "profile_id": (profile or self.profile).id, "title_id": title.id, "season": season, "episode": episode,
        }, format="json")

    def history(self, profile=None, page=1):
        return self.client.get(f"/api/history/?profileId={(profile or self.profile).id}&page={page}").data

    def test_opening_the_player_writes_one_entry_per_episode_and_day(self):
        self.watch(self.show, 1, 1)
        self.watch(self.show, 1, 1)  # again today: same entry
        self.watch(self.show, 1, 2)
        self.watch(self.movie)
        items = self.history()["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["title"]["title"], "Heat")  # newest first
        self.assertIsNone(items[0]["season"])
        self.assertEqual((items[1]["season"], items[1]["episode"], items[1]["episode_info"]["name"]), (1, 2, "Shift 2"))

    def test_pages_of_fifty(self):
        today = timezone.now()
        WatchEvent.objects.bulk_create([
            WatchEvent(profile=self.profile, title=self.movie, watched_on=(today - timedelta(days=i)).date(),
                       watched_at=today - timedelta(days=i))
            for i in range(55)
        ])
        first = self.history()
        self.assertEqual((len(first["items"]), first["next"]), (50, 2))
        second = self.history(page=2)
        self.assertEqual((len(second["items"]), second["next"]), (5, None))

    def test_removing_the_last_entry_of_a_title_forgets_it(self):
        self.watch(self.show, 1, 1)
        self.watch(self.show, 1, 2)
        TitleAction.objects.create(profile=self.profile, title=self.show, action="outbound", session_id="s")
        TitleRating.objects.create(profile=self.profile, title=self.show, value=TitleRating.LIKE)  # a choice: stays
        PlaybackOutcome.objects.create(profile=self.profile, title=self.show, provider_key="p1", worked=True)
        RecoHomeSnapshot.objects.update_or_create(profile=self.profile, defaults={  # one per profile (made with it)
            "expires_at": timezone.now() + timedelta(hours=1),
            "payload": {"rows": [{"row_type": f"because:{self.show.id}", "items": [{"id": 1}]}, {"row_type": "popular", "items": [{"id": 1}]}]},
        })
        first, second = self.history()["items"]

        res = self.client.delete(f"/api/history/{first['id']}/?profileId={self.profile.id}")
        self.assertFalse(res.data["title_forgotten"])  # another entry of the show is left
        self.assertTrue(WatchProgress.objects.filter(profile=self.profile, title=self.show).exists())

        res = self.client.delete(f"/api/history/{second['id']}/?profileId={self.profile.id}")
        self.assertTrue(res.data["title_forgotten"])
        self.assertFalse(WatchProgress.objects.filter(profile=self.profile, title=self.show).exists())
        self.assertFalse(TitleAction.objects.filter(profile=self.profile, title=self.show, action="outbound").exists())
        self.assertFalse(PlaybackOutcome.objects.filter(profile=self.profile, title=self.show).exists())
        self.assertTrue(TitleRating.objects.filter(profile=self.profile, title=self.show).exists())
        rows = RecoHomeSnapshot.objects.get(profile=self.profile).payload["rows"]
        self.assertEqual([r["row_type"] for r in rows], ["popular"])  # "Because you watched" is gone

    def test_clear_all(self):
        self.watch(self.show, 1, 1)
        self.watch(self.movie)
        self.client.delete(f"/api/history/?profileId={self.profile.id}")
        self.assertEqual(self.history()["items"], [])
        self.assertFalse(WatchProgress.objects.filter(profile=self.profile).exists())

    def test_paused_history_saves_nothing_about_watching(self):
        res = self.client.post(f"/api/history/pause/?profileId={self.profile.id}", {"paused": True}, format="json")
        self.assertTrue(res.data["paused"])
        self.assertTrue(self.history()["paused"])
        self.watch(self.show, 1, 1)
        for action in ("outbound", "click", "like"):
            self.client.post("/api/events/action/", {
                "profile_id": self.profile.id, "title_id": self.show.id, "action": action, "session_id": "s",
            }, format="json")
        self.client.post("/api/events/impressions/", {"items": [
            {"profile_id": self.profile.id, "title_id": self.show.id, "session_id": "s"},
        ]}, format="json")
        self.client.post("/api/playback/", {"profile_id": self.profile.id, "title_id": self.show.id, "provider": "p1", "worked": True}, format="json")

        self.assertFalse(WatchEvent.objects.exists())
        self.assertFalse(WatchProgress.objects.exists())
        self.assertFalse(TitleImpression.objects.exists())
        self.assertFalse(PlaybackOutcome.objects.exists())
        self.assertEqual(list(TitleAction.objects.values_list("action", flat=True)), ["like"])  # a choice, not watching

        self.client.post(f"/api/history/pause/?profileId={self.profile.id}", {"paused": False}, format="json")
        self.watch(self.show, 1, 1)
        self.assertEqual(WatchEvent.objects.count(), 1)

    def test_export_csv(self):
        self.watch(self.show, 1, 2)
        self.watch(self.movie)
        res = self.client.get(f"/api/history/export/?profileId={self.profile.id}")
        self.assertEqual(res["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", res["Content-Disposition"])
        lines = res.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(lines[0], "Date,Time,Type,Title,Season,Episode,Episode title")
        self.assertTrue(lines[1].endswith(",Movie,Heat,,,"))
        self.assertTrue(lines[2].endswith(",Show,Night Shift,1,2,Shift 2"))

    def test_kids_profile_list_respects_its_age_and_others_are_refused(self):
        self.watch(self.movie, profile=self.kid)  # an R movie opened by the kid profile
        self.watch(self.show, 1, 1, profile=self.kid)
        self.assertEqual([i["title"]["title"] for i in self.history(self.kid)["items"]], ["Night Shift"])
        self.assertEqual(self.client.get(f"/api/history/?profileId={self.bob.id}").status_code, 404)
        event = WatchEvent.objects.filter(profile=self.kid).first()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.delete(f"/api/history/{event.id}/?profileId={self.bob.id}").status_code, 404)

    def test_backfill_from_what_was_recorded_before(self):
        WatchProgress.objects.create(profile=self.profile, title=self.show, season_number=1, episode_number=2)
        TitleAction.objects.create(profile=self.profile, title=self.movie, action="outbound", session_id="s")
        TitleAction.objects.create(profile=self.profile, title=self.movie, action="outbound", session_id="s")  # same day
        TitleAction.objects.create(profile=self.profile, title=self.show, action="outbound", session_id="s")  # episode known
        migration = importlib.import_module("reco.migrations.0017_watch_event_backfill")
        migration.backfill(apps, None)
        got = sorted(WatchEvent.objects.values_list("title__title", "season_number", "episode_number"))
        self.assertEqual(got, [("Heat", 0, 0), ("Night Shift", 1, 2)])
