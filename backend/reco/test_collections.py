"""Franchises in watch order (reco/collections.py) and Title.collection_id kept in sync."""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import Profile, Title, User
from .models import TitleAction, WatchEvent, WatchProgress

GODFATHER = {"id": 230, "name": "The Godfather Collection", "poster_path": "/p.jpg", "backdrop_path": "/b.jpg"}
BOURNE = {"id": 31562, "name": "The Bourne Collection"}


class CollectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="en")
        self.kid = Profile.objects.create(user=self.user, name="K", age_restriction="PG", is_kids=True, language_preference="en")
        self.bob = Profile.objects.create(user=self.other, name="B", age_restriction="NC-17", language_preference="en")
        self.client.force_authenticate(self.user)
        future = (timezone.localdate() + timedelta(days=200)).isoformat()

        def movie(name, date, bc, maturity=3):
            return Title.objects.create(type="movie", title=name, release_date=date, belongs_to_collection=bc, maturity=maturity)

        self.gf2 = movie("The Godfather Part II", "1974-12-20", GODFATHER)
        self.gf1 = movie("The Godfather", "1972-03-14", GODFATHER)
        self.gf3 = movie("The Godfather Part III", "1990-12-25", GODFATHER)
        self.gf4 = movie("The Godfather Part IV", future, GODFATHER)          # announced
        self.b1 = movie("The Bourne Identity", "2002-06-14", BOURNE, maturity=2)
        self.b2 = movie("The Bourne Supremacy", "2004-07-23", BOURNE, maturity=2)
        self.alone = movie("Heat", "1995-12-15", None)

    def get(self, cid, profile=None):
        return self.client.get(f"/api/collections/{cid}/?profileId={(profile or self.profile).id}")

    def watch(self, title, days_ago=0):
        when = timezone.now() - timedelta(days=days_ago)
        WatchEvent.objects.create(profile=self.profile, title=title, watched_on=when.date(), watched_at=when)

    def test_collection_id_follows_the_json(self):
        self.assertEqual(self.gf1.collection_id, 230)
        self.assertIsNone(self.alone.collection_id)
        self.alone.belongs_to_collection = {"id": 999, "name": "X"}
        self.alone.save(update_fields=["belongs_to_collection"])
        self.alone.refresh_from_db()
        self.assertEqual(self.alone.collection_id, 999)

    def test_parts_in_release_order_with_what_was_watched_and_whats_next(self):
        self.watch(self.gf1)
        res = self.get(230)
        self.assertEqual(res.status_code, 200)
        d = res.data
        self.assertEqual((d["name"], d["poster"]), ("The Godfather Collection", "https://image.tmdb.org/t/p/original/p.jpg"))
        self.assertEqual([p["title"]["title"] for p in d["parts"]],
                         ["The Godfather", "The Godfather Part II", "The Godfather Part III", "The Godfather Part IV"])
        self.assertEqual([p["position"] for p in d["parts"]], [1, 2, 3, 4])
        self.assertEqual([p["watched"] for p in d["parts"]], [True, False, False, False])
        self.assertEqual([p["upcoming"] for p in d["parts"]], [False, False, False, True])
        self.assertEqual((d["watched"], d["total"]), (1, 4))
        self.assertEqual(d["next"]["title"], "The Godfather Part II")

    def test_played_or_imported_counts_as_watched(self):
        TitleAction.objects.create(profile=self.profile, title=self.gf1, action="watched", session_id="")
        WatchProgress.objects.create(profile=self.profile, title=self.gf2)
        d = self.get(230).data
        self.assertEqual(d["next"]["title"], "The Godfather Part III")
        TitleAction.objects.create(profile=self.profile, title=self.gf3, action="outbound", session_id="")
        self.assertIsNone(self.get(230).data["next"])  # Part IV isn't out: nothing to watch next

    def test_unknown_collection_age_limit_and_other_accounts(self):
        self.assertEqual(self.get(1).status_code, 404)
        self.assertEqual(self.get(230, self.kid).status_code, 404)  # all R: a kids profile sees none
        self.assertEqual(self.get(230, self.bob).status_code, 404)

    def test_home_row_offers_the_next_part_of_started_franchises(self):
        self.watch(self.b1, days_ago=5)
        self.watch(self.gf1, days_ago=1)
        self.watch(self.gf2, days_ago=1)
        rows = self.client.get(f"/api/reco/home/?profileId={self.profile.id}").data["rows"]
        row = next(r for r in rows if r["row_type"] == "collections_next")
        self.assertEqual([i["title"] for i in row["items"]], ["The Godfather Part III", "The Bourne Supremacy"])  # recent first
        self.assertEqual(row["items"][0]["why_key"], {"key": "collectionPart", "position": 3, "collection": "The Godfather Collection"})
        self.assertEqual(rows[0]["row_type"], "collections_next")  # first (no Continue watching here)

    def test_no_row_when_nothing_started_or_everything_seen(self):
        rows = self.client.get(f"/api/reco/home/?profileId={self.profile.id}").data["rows"]
        self.assertFalse(any(r["row_type"] == "collections_next" for r in rows))
        for t in (self.b1, self.b2):
            self.watch(t)
        rows = self.client.get(f"/api/reco/home/?profileId={self.profile.id}").data["rows"]
        self.assertFalse(any(r["row_type"] == "collections_next" for r in rows))

