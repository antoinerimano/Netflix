"""What to watch (reco/pick.py): time, mood, quality, what's left out, the draw."""
import random

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import Profile, Title, TVShowExtras, User
from .models import TitleAction, TitleRating, WatchEvent
from .pick import draw


class PickTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.other = User.objects.create_user("bob@example.com", "Bob", "pw-bob-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="en")
        self.kid = Profile.objects.create(user=self.user, name="K", age_restriction="PG", is_kids=True, language_preference="en")
        self.bob = Profile.objects.create(user=self.other, name="B", age_restriction="NC-17", language_preference="en")
        self.client.force_authenticate(self.user)

        def title(name, kind="movie", runtime=90, genre="Comedy", votes=5000, rating=7.5, poster="p.jpg",
                  date="2000-01-01", maturity=2, episode=None):
            t = Title.objects.create(
                type=kind, title=name, runtime_minutes=runtime if kind == "movie" else None, genre=genre,
                vote_count=votes, vote_average=rating, poster=poster, maturity=maturity, popularity=votes / 100,
                release_date=date if kind == "movie" else "", first_air_date=date if kind == "tv" else "",
            )
            if episode:
                TVShowExtras.objects.create(title=t, episode_run_time=[episode])
            return t

        self.short_comedy = title("Short Comedy", runtime=88)
        self.long_comedy = title("Long Comedy", runtime=125)
        self.epic = title("Epic", runtime=200, genre="Drama")
        self.tiny = title("Short Film", runtime=20)
        self.horror = title("Night Terror", runtime=90, genre="Horror, Comedy", maturity=3)
        self.family = title("Family Fun", runtime=85, genre="Family, Animation", maturity=0)
        self.sitcom = title("Sitcom", kind="tv", genre="Comedy", episode=22, maturity=1)
        self.saga = title("Long Saga", kind="tv", genre="Drama", episode=75)
        self.obscure = title("Obscure", votes=20)
        self.bad = title("Bad", rating=4.0)
        self.no_poster = title("No Poster", poster="")
        self.future = title("Future", date="2999-01-01")

    def pick(self, profile=None, **params):
        q = "&".join(f"{k}={v}" for k, v in {"count": 12, **params}.items())
        return self.client.get(f"/api/pick/?profileId={(profile or self.profile).id}&{q}")

    def names(self, **params):
        return {i["title"] for i in self.pick(**params).data["items"]}

    def test_time(self):
        self.assertEqual(self.names(time="90", mood="funny"), {"Short Comedy"})  # no horror in funny, Family Fun isn't a comedy
        self.assertEqual(self.names(time="120"), {"Short Comedy", "Long Comedy", "Night Terror", "Family Fun"})
        self.assertEqual(self.names(time="episode"), {"Sitcom"})  # 22 min episodes, not the 75 min ones
        self.assertEqual(self.names(time="any"),
                         {"Short Comedy", "Long Comedy", "Epic", "Night Terror", "Family Fun", "Sitcom", "Long Saga"})
        item = next(i for i in self.pick(time="episode").data["items"])
        self.assertEqual(item["minutes"], 22)

    def test_mood(self):
        self.assertEqual(self.names(time="any", mood="scary"), {"Night Terror"})
        self.assertEqual(self.names(time="any", mood="feelgood"), {"Short Comedy", "Long Comedy", "Family Fun", "Sitcom"})  # no horror
        self.assertEqual(self.names(time="any", mood="thoughtful"), {"Epic", "Long Saga"})

    def test_what_was_seen_or_already_shown_is_left_out(self):
        WatchEvent.objects.create(profile=self.profile, title=self.short_comedy, watched_on="2026-01-01", watched_at="2026-01-01T20:00:00Z")
        TitleRating.objects.create(profile=self.profile, title=self.long_comedy, value=TitleRating.LIKE)
        TitleAction.objects.create(profile=self.profile, title=self.horror, action="not_interested", session_id="")
        names = self.names(time="120", exclude=self.family.id)
        self.assertEqual(names, set())
        self.assertEqual(self.pick(time="120").data["candidates"], 1)  # Family Fun

    def test_kids_and_other_accounts_and_bad_params(self):
        self.assertEqual(self.names(profile=self.kid, time="any"), {"Family Fun", "Sitcom"})
        self.assertEqual(self.pick(profile=self.bob).status_code, 404)
        self.assertEqual(self.pick(time="45").status_code, 400)
        self.assertEqual(self.pick(mood="sleepy").status_code, 400)

    def test_count_and_surprise(self):
        self.assertEqual(len(self.pick(time="any", count=1).data["items"]), 1)
        self.assertEqual(len(self.pick(time="any", count=3).data["items"]), 3)

    def test_draw_favours_the_best_without_repeats(self):
        items = list(range(100))
        rng = random.Random(7)
        firsts = [draw(items, 1, rng)[0] for _ in range(2000)]
        self.assertTrue(all(i < 60 for i in firsts))  # only from the best 60
        self.assertGreater(sum(1 for i in firsts if i < 10), sum(1 for i in firsts if 50 <= i < 60))
        picked = draw(items, 12, rng)
        self.assertEqual(len(set(picked)), 12)
