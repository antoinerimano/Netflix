from django.test import TestCase
from rest_framework.test import APIClient

from .models import User, Profile, Subscription, PaymentHistory


class PermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.alice = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.bob = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.admin = User.objects.create_superuser("admin@example.com", "Admin", "pw-admin-123!")
        self.bob_profile = Profile.objects.create(
            user=self.bob, name="Bob", age_restriction="18", language_preference="en"
        )

    def test_register_cannot_grant_admin(self):
        res = self.client.post("/api/users/register/", {
            "name": "Mallory", "email": "m@example.com", "password": "pw-m-123!",
            "is_staff": True, "is_superuser": True,
        }, format="json")
        self.assertEqual(res.status_code, 201)
        u = User.objects.get(email="m@example.com")
        self.assertFalse(u.is_staff)
        self.assertFalse(u.is_superuser)
        self.assertTrue(u.check_password("pw-m-123!"))
        self.assertNotIn("password", res.data["user"])

    def test_login_still_works(self):
        res = self.client.post("/api/users/login/",
                               {"email": "alice@example.com", "password": "pw-alice-123!"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("password", res.data["user"])

    def test_user_list_scoped_to_self(self):
        self.client.force_authenticate(self.alice)
        res = self.client.get("/api/users/")
        self.assertEqual(res.status_code, 200)
        ids = [u["id"] for u in res.data.get("results", res.data)]
        self.assertEqual(ids, [str(self.alice.id)])
        self.assertEqual(self.client.get(f"/api/users/{self.bob.id}/").status_code, 404)

    def test_admin_sees_all_users(self):
        self.client.force_authenticate(self.admin)
        res = self.client.get("/api/users/")
        self.assertEqual(len(res.data.get("results", res.data)), 3)

    def test_user_cannot_edit_own_privileges(self):
        self.client.force_authenticate(self.alice)
        self.client.patch(f"/api/users/{self.alice.id}/", {"is_staff": True}, format="json")
        self.alice.refresh_from_db()
        self.assertFalse(self.alice.is_staff)

    def test_nested_routes_require_auth(self):
        for path in ("profiles", "subscriptions", "payment_history"):
            res = self.client.get(f"/api/users/{self.bob.id}/{path}/")
            self.assertEqual(res.status_code, 401, path)

    def test_nested_routes_blocked_for_other_users(self):
        self.client.force_authenticate(self.alice)
        for path in ("profiles", "subscriptions", "payment_history"):
            res = self.client.get(f"/api/users/{self.bob.id}/{path}/")
            self.assertEqual(res.status_code, 403, path)
        res = self.client.delete(f"/api/users/{self.bob.id}/profiles/{self.bob_profile.id}/")
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Profile.objects.filter(id=self.bob_profile.id).exists())

    def test_owner_can_use_nested_routes(self):
        self.client.force_authenticate(self.alice)
        res = self.client.post(f"/api/users/{self.alice.id}/profiles/", {
            "name": "Kid", "age_restriction": "7", "language_preference": "en",
            "user": str(self.bob.id),  # ignored: owner comes from the URL
        }, format="json")
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(Profile.objects.get(id=res.data["id"]).user_id, self.alice.id)
        res = self.client.post(f"/api/users/{self.alice.id}/subscriptions/",
                               {"plan_id": "0", "plan_type": "Basic"}, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(self.client.get(f"/api/users/{self.alice.id}/payment_history/").status_code, 200)

    def test_payment_history_is_read_only(self):
        self.client.force_authenticate(self.alice)
        res = self.client.post(f"/api/users/{self.alice.id}/payment_history/", {
            "id": "x", "date": "2026-01-01T00:00:00Z", "amount": "1.00", "currency": "USD",
            "plan_type": "Premium", "transaction_id": "t", "status": "Succeeded",
        }, format="json")
        self.assertEqual(res.status_code, 405)
        self.assertFalse(PaymentHistory.objects.exists())

    def test_subscribe_other_user_blocked(self):
        self.client.force_authenticate(self.alice)
        res = self.client.post(f"/api/users/{self.bob.id}/subscribe/", {"plan_type": "Basic"}, format="json")
        self.assertEqual(res.status_code, 404)
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())

    def test_logout_without_access_token(self):
        res = self.client.post("/api/logout/", {"refresh": "garbage"}, format="json")
        self.assertEqual(res.status_code, 400)  # reaches the view, not 401

    def test_titles_public_read(self):
        self.assertEqual(self.client.get("/api/titles/").status_code, 200)
