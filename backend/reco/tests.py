from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import User, Profile, Title
from .models import TitleImpression, TitleAction, TitleRating, RecoHomeSnapshot


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


class TasteOnboardingTests(TestCase):
    """GET /api/taste/: titles to pick from; POST: picks become likes and the home is rebuilt."""

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.alice = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.bob = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(
            user=self.alice, name="A", age_restriction="NC-17", language_preference="fr")
        self.kid = Profile.objects.create(
            user=self.alice, name="K", age_restriction="PG", is_kids=True, language_preference="en")
        self.bob_profile = Profile.objects.create(
            user=self.bob, name="B", age_restriction="NC-17", language_preference="en")
        poster = "https://image.tmdb.org/t/p/original/x.jpg"
        self.titles = []
        for i, (kind, genre, lang, maturity) in enumerate([
            ("movie", "Action", "en", 2), ("movie", "Action", "en", 2), ("movie", "Action", "en", 2),
            ("tv", "Comedy", "en", 1), ("movie", "Drama", "fr", 2), ("movie", "Horror", "en", 4),
            ("movie", "Family", "en", 0),
        ]):
            self.titles.append(Title.objects.create(
                type=kind, title=f"T{i}", poster=poster, genre=genre, primary_genre_norm=genre.lower(),
                original_language=lang, vote_count=5000, popularity=100 - i, maturity=maturity,
                release_date="2000-01-01" if kind == "movie" else "", first_air_date="2000-01-01" if kind == "tv" else "",
            ))
        # unknown titles (few votes) and titles without a poster are never offered
        Title.objects.create(type="movie", title="Obscure", poster=poster, vote_count=3, popularity=500)
        Title.objects.create(type="movie", title="No poster", vote_count=9000, popularity=400)
        self.client.force_authenticate(self.alice)

    def _get(self, profile):
        return self.client.get(f"/api/taste/?profileId={profile.id}")

    def test_choices_are_known_titles_spread_over_genres(self):
        res = self._get(self.profile)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["min_picks"], 3)
        names = [t["title"] for t in res.data["titles"]]
        self.assertNotIn("Obscure", names)
        self.assertNotIn("No poster", names)
        self.assertEqual(len(names), 7)
        # the first screen isn't three action movies in a row
        genres = [Title.objects.get(id=t["id"]).primary_genre_norm for t in res.data["titles"][:4]]
        self.assertEqual(len(set(genres)), 4)
        self.assertIn("T4", names)  # in the profile's language (fr)

    def test_kids_profile_only_gets_titles_for_its_age(self):
        names = {t["title"] for t in self._get(self.kid).data["titles"]}
        self.assertEqual(names, {"T3", "T6"})  # PG at most

    def test_other_users_profile_is_refused(self):
        self.assertEqual(self._get(self.bob_profile).status_code, 404)
        res = self.client.post(f"/api/taste/?profileId={self.bob_profile.id}", {"title_ids": [self.titles[0].id]}, format="json")
        self.assertEqual(res.status_code, 404)

    def test_picks_become_likes_and_the_home_is_rebuilt(self):
        picked = [t.id for t in self.titles[:3]]
        res = self.client.post(
            f"/api/taste/?profileId={self.profile.id}", {"title_ids": picked + [999999]}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["liked"], 3)  # unknown id ignored
        self.assertEqual(res.data["home"], "rebuilt")
        self.assertEqual(
            set(TitleRating.objects.filter(profile=self.profile, value=TitleRating.LIKE).values_list("title_id", flat=True)),
            set(picked))
        self.assertEqual(TitleAction.objects.filter(profile=self.profile, provider="onboarding").count(), 3)
        self.assertTrue(RecoHomeSnapshot.objects.filter(profile=self.profile, algo_version="home_v1").exists())
        # already liked: not offered again
        offered = {t["id"] for t in self._get(self.profile).data["titles"]}
        self.assertFalse(offered & set(picked))

    def test_bad_bodies_are_refused(self):
        url = f"/api/taste/?profileId={self.profile.id}"
        for body in ({}, {"title_ids": []}, {"title_ids": "1,2"}, {"title_ids": ["x"]}, {"title_ids": list(range(51))}):
            self.assertEqual(self.client.post(url, body, format="json").status_code, 400, body)

    def test_home_says_when_the_profile_has_no_taste_yet(self):
        home = f"/api/reco/home/?profileId={self.profile.id}"
        self.assertTrue(self.client.get(home).data["needs_taste"])
        TitleRating.objects.create(profile=self.profile, title=self.titles[0], value=TitleRating.LIKE)
        self.assertFalse(self.client.get(home).data["needs_taste"])
