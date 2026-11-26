# "Play next episode automatically" (ROADMAP 9.3): a profile setting, on by default, that the
# watch page reads from the profile; the profile form saves it with the rest (PUT) or alone (PATCH).
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Profile, User


class ProfileAutoplayNextTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.profile = Profile.objects.create(user=self.alice, name="Alice", language_preference="en")
        self.url = f"/api/users/{self.alice.id}/profiles/{self.profile.id}/"
        self.client.force_authenticate(self.alice)

    def test_on_by_default(self):
        self.assertIs(self.client.get(self.url).data["autoplay_next"], True)

    def test_turn_off_and_on(self):
        res = self.client.patch(self.url, {"autoplay_next": False}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertIs(res.data["autoplay_next"], False)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.autoplay_next)
        self.assertEqual(self.profile.name, "Alice")

        data = self.client.get(self.url).data
        data["autoplay_next"] = True
        data.pop("avatar_url", None)  # null: not part of what's tested here
        res = self.client.put(self.url, data, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.autoplay_next)
