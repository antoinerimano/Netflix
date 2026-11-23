# The "Appearance" page saves {font, accent, background} ids on the profile (PATCH): ids only,
# anything else is refused, and the owner alone can change it.
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Profile, User


class ProfileAppearanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.bob = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.alice, name="Alice", language_preference="en")
        self.url = f"/api/users/{self.alice.id}/profiles/{self.profile.id}/"

    def test_default_is_empty(self):
        self.client.force_authenticate(self.alice)
        self.assertEqual(self.client.get(self.url).data["appearance"], {})

    def test_save_and_read_back(self):
        self.client.force_authenticate(self.alice)
        look = {"font": "cinema", "accent": "blue", "background": "midnight"}
        res = self.client.patch(self.url, {"appearance": look}, format="json")
        self.assertEqual(res.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.appearance, look)
        self.assertEqual(self.profile.name, "Alice")  # a partial update: the rest is untouched

    def test_refuses_unknown_keys_and_free_values(self):
        self.client.force_authenticate(self.alice)
        for bad in ({"css": "red"}, {"accent": "#ff0000"}, {"font": "x" * 40}, {"accent": 3}, ["blue"]):
            res = self.client.patch(self.url, {"appearance": bad}, format="json")
            self.assertEqual(res.status_code, 400, bad)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.appearance, {})

    def test_reset(self):
        self.profile.appearance = {"accent": "green"}
        self.profile.save()
        self.client.force_authenticate(self.alice)
        res = self.client.patch(self.url, {"appearance": {}}, format="json")
        self.assertEqual(res.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.appearance, {})

    def test_someone_else_cannot_change_it(self):
        self.client.force_authenticate(self.bob)
        res = self.client.patch(self.url, {"appearance": {"accent": "green"}}, format="json")
        self.assertEqual(res.status_code, 403)
