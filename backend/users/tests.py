from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from .models import User, Profile, Subscription, PaymentHistory


class PermissionTests(TestCase):
    def setUp(self):
        cache.clear()  # reset rate-limit counters between tests
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

    def test_subscribe_ignores_client_billing_fields(self):
        self.client.force_authenticate(self.alice)
        res = self.client.post(f"/api/users/{self.alice.id}/subscribe/", {
            "plan_type": "Premium", "amount": "0.01", "currency": "XXX", "transaction_id": "fake",
        }, format="json")
        self.assertEqual(res.status_code, 201)
        payment = PaymentHistory.objects.get(user=self.alice)
        self.assertEqual(str(payment.amount), "9.99")
        self.assertEqual(payment.currency, "USD")
        self.assertNotEqual(payment.transaction_id, "fake")

    def test_logout_without_access_token(self):
        res = self.client.post("/api/logout/", {"refresh": "garbage"}, format="json")
        self.assertEqual(res.status_code, 400)  # reaches the view, not 401

    def test_titles_public_read(self):
        self.assertEqual(self.client.get("/api/titles/").status_code, 200)


class AuthHardeningTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.alice = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")

    def _login(self, email, password):
        return self.client.post("/api/users/login/", {"email": email, "password": password}, format="json")

    def test_login_same_error_for_unknown_email_and_wrong_password(self):
        unknown = self._login("nobody@example.com", "whatever")
        wrong = self._login("alice@example.com", "wrong")
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertEqual(unknown.data, wrong.data)

    def test_inactive_user_cannot_login(self):
        self.alice.is_active = False
        self.alice.save()
        self.assertEqual(self._login("alice@example.com", "pw-alice-123!").status_code, 400)

    def test_password_reset_same_answer_for_unknown_email(self):
        known = self.client.post("/api/password-reset/", {"email": "alice@example.com"}, format="json")
        unknown = self.client.post("/api/password-reset/", {"email": "nobody@example.com"}, format="json")
        self.assertEqual(known.status_code, 200)
        self.assertEqual(known.data, unknown.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["alice@example.com"])

    def test_password_reset_rejects_weak_password(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        uid = urlsafe_base64_encode(force_bytes(self.alice.pk))
        token = default_token_generator.make_token(self.alice)
        res = self.client.post("/api/password-reset-confirm/",
                               {"uid": uid, "token": token, "new_password": "123"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/password-reset-confirm/",
                               {"uid": uid, "token": token, "new_password": "N3w-strong-pass!"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.check_password("N3w-strong-pass!"))

    def test_login_is_rate_limited(self):
        codes = [self._login("alice@example.com", "wrong").status_code for _ in range(11)]
        self.assertEqual(codes[:10], [400] * 10)
        self.assertEqual(codes[10], 429)

    def test_password_reset_is_rate_limited(self):
        codes = [self.client.post("/api/password-reset/", {"email": "x@example.com"}, format="json").status_code
                 for _ in range(6)]
        self.assertEqual(codes[:5], [200] * 5)
        self.assertEqual(codes[5], 429)


class QueryCountTests(TestCase):
    """Guard against N+1 regressions on the main browse endpoints."""
    def setUp(self):
        from .models import Title, Season, Episode, Actor
        self.show = Title.objects.create(type="tv", title="Show")
        for n in range(1, 4):
            season = Season.objects.create(tv=self.show, season_number=n)
            for e in range(1, 4):
                Episode.objects.create(season=season, episode_number=e)
        for i in range(5):
            Actor.objects.create(title=self.show, name=f"A{i}", name_norm=f"a{i}", tmdb_id=i)
        for i in range(49):
            Title.objects.create(type="movie", title=f"M{i}")
        self.client = APIClient()

    def test_title_list_constant_queries(self):
        with self.assertNumQueries(2):  # count + page
            self.assertEqual(self.client.get("/api/titles/").status_code, 200)

    def test_title_detail_constant_queries(self):
        with self.assertNumQueries(5):  # title+extras, seasons, episodes, actors, appearance counts
            self.assertEqual(self.client.get(f"/api/titles/{self.show.id}/").status_code, 200)
