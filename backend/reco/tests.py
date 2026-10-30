from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import User, Profile, Title
from .models import TitleImpression, TitleAction


class EventOwnershipTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.alice = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.bob = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.alice_profile = Profile.objects.create(
            user=self.alice, name="A", age_restriction="18", language_preference="en")
        self.bob_profile = Profile.objects.create(
            user=self.bob, name="B", age_restriction="18", language_preference="en")
        self.title = Title.objects.create(type="movie", title="Test movie")
        self.client.force_authenticate(self.alice)

    def _impression(self, profile):
        return {"profile_id": profile.id, "title_id": self.title.id, "session_id": "s"}

    def test_impressions_only_logged_for_own_profiles(self):
        res = self.client.post("/api/events/impressions/", {
            "items": [self._impression(self.alice_profile), self._impression(self.bob_profile)],
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 1)
        self.assertEqual(
            list(TitleImpression.objects.values_list("profile_id", flat=True)), [self.alice_profile.id])

    def test_impressions_batch_size_is_capped(self):
        res = self.client.post("/api/events/impressions/", {
            "items": [self._impression(self.alice_profile)] * 501,
        }, format="json")
        self.assertEqual(res.status_code, 400)

    def test_action_on_other_users_profile_rejected(self):
        res = self.client.post("/api/events/action/", {
            "profile_id": self.bob_profile.id, "title_id": self.title.id,
            "action": "like", "session_id": "s",
        }, format="json")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(TitleAction.objects.exists())

    def test_action_on_own_profile_logged(self):
        res = self.client.post("/api/events/action/", {
            "profile_id": self.alice_profile.id, "title_id": self.title.id,
            "action": "like", "session_id": "s",
        }, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(TitleAction.objects.count(), 1)


class PublicEndpointsSmokeTests(TestCase):
    """Every public list endpoint should at least answer 200 (catches broken imports etc.)."""
    def test_public_endpoints(self):
        client = APIClient()
        for url in ("/api/titles/", "/api/titles/genres/", "/api/titles/search/?q=a", "/api/actors/"):
            self.assertEqual(client.get(url).status_code, 200, url)
