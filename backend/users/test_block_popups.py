"""Block pop-ups (ROADMAP 9.1): the profile setting, the providers' "plays sandboxed" (sandbox_ok)
in the API the watch page reads, sandboxed plays reported by the watch page, the dashboard card.
(The scout's verdict on import: test_provider_import.py.)"""
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from reco.models import PlaybackOutcome
from users.models import Profile, Provider, Title, User


class BlockPopupsTests(TestCase):
    def setUp(self):
        cache.clear()
        Provider.objects.all().delete()  # migration 0012 seeds the original ones
        self.client = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", language_preference="en")
        self.bob = Profile.objects.create(user=self.other, name="B", language_preference="en")
        self.movie = Title.objects.create(type="movie", title="Heat")
        self.yes = Provider.objects.create(key="calm", label="Calm", domain="https://calm.test", movie_path="/m/{tmdb_id}",
                                           sandbox_ok=Provider.SANDBOX_YES, priority=2)
        self.no = Provider.objects.create(key="noisy", label="Noisy", domain="https://noisy.test", movie_path="/m/{tmdb_id}",
                                          sandbox_ok=Provider.SANDBOX_NO, priority=1)
        self.client.force_authenticate(self.user)

    def profile_url(self, profile, user=None):
        return f"/api/users/{(user or self.user).id}/profiles/{profile.id}/"

    def test_on_by_default_and_sent_with_the_profile(self):
        self.assertTrue(self.profile.block_popups)
        res = self.client.get(self.profile_url(self.profile))
        self.assertEqual(res.status_code, 200)
        self.assertIs(res.data["block_popups"], True)

    def test_the_switch_is_saved_on_the_profile(self):
        res = self.client.patch(self.profile_url(self.profile), {"block_popups": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIs(res.data["block_popups"], False)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.block_popups)
        # the profile form sends everything: the setting comes along
        data = {**self.client.get(self.profile_url(self.profile)).data, "block_popups": True}
        self.assertEqual(self.client.put(self.profile_url(self.profile), data, format="json").status_code, 200)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.block_popups)

    def test_nobody_else_changes_it(self):
        res = self.client.patch(self.profile_url(self.bob, self.other), {"block_popups": False}, format="json")
        self.assertIn(res.status_code, (403, 404))
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.block_popups)

    def test_providers_say_if_they_play_sandboxed(self):
        Provider.objects.create(key="new", label="New", domain="https://new.test", movie_path="/m/{tmdb_id}")
        res = self.client.get("/api/providers/")
        self.assertEqual(res.status_code, 200)
        by_key = {p["key"]: p["sandbox_ok"] for p in res.data}
        self.assertEqual(by_key, {"calm": "yes", "noisy": "no", "new": "unknown"})

    def test_sandboxed_plays_are_recorded(self):
        post = lambda **extra: self.client.post("/api/playback/", {
            "profile_id": self.profile.id, "title_id": self.movie.id, "provider": "noisy", "worked": False, **extra,
        }, format="json")
        self.assertEqual(post(sandboxed=True).status_code, 200)
        self.assertEqual(post(sandboxed=False).status_code, 200)
        self.assertEqual(post().status_code, 200)  # an older app: not said
        self.assertEqual(list(PlaybackOutcome.objects.order_by("id").values_list("sandboxed", flat=True)), [True, False, None])

    def test_dashboard_shows_it(self):
        PlaybackOutcome.objects.create(profile=self.profile, title=self.movie, provider_key="noisy", worked=False, sandboxed=True)
        PlaybackOutcome.objects.create(profile=self.profile, title=self.movie, provider_key="noisy", worked=True, sandboxed=True)
        admin = User.objects.create_superuser("admin@example.com", "Admin", "pw-admin-123!")
        self.client.force_authenticate(None)
        self.client.force_login(admin)
        res = self.client.get("/" + settings.ADMINADMIN_URL.strip("/") + "/dashboard/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn("No pop-ups", html)
        self.assertIn("50 % of 2 sandboxed", html)
