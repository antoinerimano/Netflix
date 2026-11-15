"""'Catch me up' (reco/recap.py): where the profile is, what Claude is told (nothing after that
point), kept recaps, failures. A fake Claude client: nothing is sent to the real API."""
from types import SimpleNamespace as NS
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import Episode, Profile, Season, Title, User

from . import recap
from .models import ShowRecap, WatchEvent, WatchProgress


def reply(text="Walter starts cooking.", stop_reason="end_turn"):
    return NS(stop_reason=stop_reason, content=[NS(type="thinking", thinking=""), NS(type="text", text=text)])


class RecapTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="fr")
        self.kid = Profile.objects.create(user=self.user, name="K", age_restriction="G", is_kids=True, language_preference="en")
        other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.bob = Profile.objects.create(user=other, name="B", age_restriction="NC-17", language_preference="en")
        self.api.force_authenticate(self.user)

        self.show = Title.objects.create(type="tv", title="Chem", description="A teacher turns to crime.", maturity=4,
                                         release_year=2008)
        for s in (1, 2):
            season = Season.objects.create(tv=self.show, season_number=s, overview=f"Season {s} in short.")
            for e in (1, 2, 3):
                Episode.objects.create(season=season, episode_number=e, name=f"Ep {s}.{e}", overview=f"Plot {s}.{e}.")
        specials = Season.objects.create(tv=self.show, season_number=0)
        Episode.objects.create(season=specials, episode_number=1, name="Special", overview="Plot special.")

        self.claude = mock.MagicMock()
        self.claude.messages.create.return_value = reply()
        patcher = mock.patch("reco.recap._client", return_value=self.claude)
        patcher.start()
        self.addCleanup(patcher.stop)

    def at(self, season, episode, profile=None):
        WatchProgress.objects.update_or_create(
            profile=profile or self.profile, title=self.show,
            defaults={"season_number": season, "episode_number": episode},
        )

    def get(self, peek=False, profile=None):
        params = {"profileId": (profile or self.profile).id, "titleId": self.show.id}
        if peek:
            params["peek"] = 1
        return self.api.get("/api/recap/", params)

    def sent(self):
        return self.claude.messages.create.call_args.kwargs

    def test_nothing_to_recap(self):
        self.assertEqual(self.get(peek=True).data, {"available": False})  # never watched
        self.at(1, 1)
        self.assertEqual(self.get(peek=True).data, {"available": False})  # nothing before S1E1
        self.claude.messages.create.assert_not_called()

    def test_peek_does_not_call_claude(self):
        self.at(2, 2)
        r = self.get(peek=True)
        self.assertEqual(r.data, {"available": True, "season": 2, "episode": 2})
        self.claude.messages.create.assert_not_called()

    def test_recap_covers_only_what_was_seen(self):
        self.at(2, 2)
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["text"], "Walter starts cooking.")
        self.assertFalse(r.data["cached"])
        prompt = self.sent()["messages"][0]["content"]
        for seen in ("Plot 1.1.", "Plot 1.3.", "Plot 2.1."):
            self.assertIn(seen, prompt)
        for unseen in ("Plot 2.2.", "Plot 2.3.", "Plot special."):  # where they resume, after, specials
            self.assertNotIn(unseen, prompt)
        self.assertIn("French", self.sent()["system"])  # the profile's language
        self.assertEqual(self.sent()["model"], recap.MODEL)

    def test_furthest_point_of_progress_and_history(self):
        self.at(1, 2)
        WatchEvent.objects.create(profile=self.profile, title=self.show, season_number=2, episode_number=3,
                                  watched_on="2026-01-01", watched_at="2026-01-01T20:00:00Z")
        self.assertEqual(self.get(peek=True).data["episode"], 3)
        self.assertEqual(self.get(peek=True).data["season"], 2)

    def test_kept_and_shared_by_language(self):
        self.at(2, 2)
        self.get()
        other = Profile.objects.create(user=self.user, name="C", age_restriction="NC-17", language_preference="fr")
        self.at(2, 2, profile=other)
        r = self.get(profile=other)
        self.assertTrue(r.data["cached"])
        self.assertEqual(self.claude.messages.create.call_count, 1)  # written once
        self.assertEqual(ShowRecap.objects.get().language, "fr")

    def test_failures_are_not_kept(self):
        self.at(2, 2)
        self.claude.messages.create.return_value = reply("", stop_reason="refusal")
        r = self.get()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data["code"], "recap_unavailable")
        self.assertFalse(ShowRecap.objects.exists())

        import anthropic
        self.claude.messages.create.side_effect = anthropic.APIConnectionError(request=mock.MagicMock())
        self.assertEqual(self.get().status_code, 503)

    def test_throttled_only_when_writing(self):
        self.at(2, 2)
        with mock.patch.object(recap.RecapThrottle, "allow_request", return_value=False):
            self.assertEqual(self.get().status_code, 429)
        ShowRecap.objects.create(title=self.show, season=2, episode=2, language="fr", text="Kept.")
        with mock.patch.object(recap.RecapThrottle, "allow_request", return_value=False):
            self.assertEqual(self.get().data["text"], "Kept.")

    def test_access(self):
        self.at(2, 2, profile=self.kid)
        self.assertEqual(self.get(peek=True, profile=self.kid).status_code, 404)  # above the age limit
        self.assertEqual(self.get(peek=True, profile=self.bob).status_code, 404)  # someone else's profile
        movie = Title.objects.create(type="movie", title="Film")
        r = self.api.get("/api/recap/", {"profileId": self.profile.id, "titleId": movie.id, "peek": 1})
        self.assertEqual(r.status_code, 404)

    def test_older_seasons_in_brief(self):
        for s in (3, 4):
            season = Season.objects.create(tv=self.show, season_number=s, overview="")
            Episode.objects.create(season=season, episode_number=1, name=f"Ep {s}.1", overview=f"Plot {s}.1.")
        text = recap.prompt_text(self.show, 4, 2)
        self.assertIn("Season 1 (in brief): Season 1 in short.", text)
        self.assertIn("Season 2 (in brief): Season 2 in short.", text)
        self.assertIn("S3E1 Ep 3.1: Plot 3.1.", text)
        self.assertIn("S4E1 Ep 4.1: Plot 4.1.", text)
        self.assertNotIn("S1E1", text)
