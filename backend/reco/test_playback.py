"""Smart playback (2.1 / 9.2): the order the watch page tries sources in, and what it remembers per title."""
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import Profile, Provider, Title, User
from .models import PlaybackOutcome
from .views import PLAYBACK_MIN_SAMPLES


class ProviderOrderTests(TestCase):
    def setUp(self):
        cache.clear()
        Provider.objects.all().delete()  # migration 0012 seeds the original ones
        self.client = APIClient()

    def make(self, key, priority, **kw):
        return Provider.objects.create(key=key, label=key.upper(), domain=f"https://{key}.test",
                                       movie_path="/movie/{tmdb_id}", priority=priority, **kw)

    def order(self):
        cache.clear()
        return [p["key"] for p in self.client.get("/api/providers/").json()]

    def test_the_scout_ranks_sources_without_a_success_rate(self):
        self.make("first", 1)                      # never checked: an average source
        self.make("weak", 2, scout_score=0.2)      # played 1 test film out of 5
        self.make("strong", 3, scout_score=1.0)    # played them all
        self.make("gone", 0, scout_score=1.0, status=Provider.DOWN)
        self.assertEqual(self.order(), ["strong", "first", "weak", "gone"])

    def test_what_viewers_play_counts_before_the_scout(self):
        self.make("liked", 1, scout_score=0.2)
        self.make("tested", 2, scout_score=0.9)
        user = User.objects.create_user("a@example.com", "A", "pw-a-12345!")
        profile = Profile.objects.create(user=user, name="A", age_restriction="NC-17", language_preference="en")
        title = Title.objects.create(type="movie", title="Heat")
        PlaybackOutcome.objects.bulk_create(
            [PlaybackOutcome(profile=profile, title=title, provider_key="liked", worked=True)] * PLAYBACK_MIN_SAMPLES
        )
        self.assertEqual(self.order(), ["liked", "tested"])  # plays for 100 % of the viewers
        PlaybackOutcome.objects.filter(provider_key="liked").update(worked=False)
        self.assertEqual(self.order(), ["tested", "liked"])

    def test_same_score_keeps_the_admin_priority(self):
        self.make("b", 2, scout_score=0.8)
        self.make("a", 1, scout_score=0.8)
        self.assertEqual(self.order(), ["a", "b"])


class PreferredSourceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("b@example.com", "B", "pw-b-12345!")
        self.profile = Profile.objects.create(user=self.user, name="B", age_restriction="NC-17", language_preference="en")
        self.client.force_authenticate(self.user)
        self.title = Title.objects.create(type="movie", title="Heat")
        self.other = Title.objects.create(type="movie", title="Ronin")
        for key in ("p1", "p2", "p3"):
            Provider.objects.create(key=key, label=key, domain=f"https://{key}.test", enabled=True)

    def played(self, key, worked, title=None):
        self.client.post("/api/playback/", {"profile_id": self.profile.id, "title_id": (title or self.title).id,
                                            "provider": key, "worked": worked}, format="json")

    def prefs(self):
        return self.client.get(f"/api/playback/?profileId={self.profile.id}&titleId={self.title.id}").json()

    def test_sources_that_failed_on_this_title_are_listed(self):
        self.played("p1", False)
        self.played("p2", False)
        self.played("p3", True)
        self.played("p3", False, title=self.other)  # another title: not this one's business
        prefs = self.prefs()
        self.assertEqual(prefs["title"], "p3")
        self.assertEqual(sorted(prefs["failed"]), ["p1", "p2"])

    def test_a_source_that_played_again_is_no_longer_failed(self):
        self.played("p1", False)
        self.played("p1", True)
        self.assertEqual(self.prefs()["failed"], [])
        self.assertEqual(self.prefs()["title"], "p1")

    def test_disabled_sources_are_left_out(self):
        self.played("p2", False)
        Provider.objects.filter(key="p2").update(enabled=False)
        self.assertEqual(self.prefs()["failed"], [])
