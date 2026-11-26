"""'Popular anime' / 'Popular K-dramas' home rows (ROADMAP 9.5): reco/section_rows.py."""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import Profile, Title, User
from .models import RecoHomeSnapshot, TitleAction, TitleRating


class SectionRowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("a@example.com", "A", "pw-a-12345!")
        self.fan = Profile.objects.create(user=self.user, name="Fan", language_preference="en", age_restriction="NC-17")
        self.other = Profile.objects.create(user=self.user, name="Other", language_preference="en", age_restriction="NC-17")
        self.kid = Profile.objects.create(user=self.user, name="K", language_preference="en", age_restriction="G", is_kids=True)
        self.client.force_authenticate(self.user)

        def mk(name, pop, maturity=0, **kw):
            kw.setdefault("genre", "Animation")
            kw.setdefault("original_language", "ja")
            return Title.objects.create(type="tv", title=name, popularity=pop, vote_count=500, maturity=maturity, **kw)

        self.anime = [mk(f"A{i}", 100 - i, maturity=0 if i % 2 else 4) for i in range(1, 7)]
        self.drama = mk("D1", 90, genre="Drama", original_language="ko")
        self.film = Title.objects.create(type="movie", title="Heat", genre="Crime", popularity=99, vote_count=900)
        now = timezone.now()
        for p in (self.fan, self.other, self.kid):
            RecoHomeSnapshot.objects.update_or_create(profile=p, defaults={
                "algo_version": "home_v1", "expires_at": now + timedelta(hours=1),
                "payload": {"rows": [{"row_type": f"for_you_{i}", "title": f"Row {i}", "items": [{"id": self.film.id}]}
                                     for i in range(4)]}})
        # the fan watched 2 anime and liked a third; the other profile watched one anime only
        for p, titles in ((self.fan, self.anime[:2]), (self.kid, [self.anime[0], self.anime[2]]), (self.other, self.anime[:1])):
            for t in titles:
                TitleAction.objects.create(profile=p, title=t, action="outbound")
        TitleRating.objects.create(profile=self.fan, title=self.drama, value=TitleRating.LIKE)

    def rows(self, profile):
        res = self.client.get(f"/api/reco/home/?profileId={profile.id}")
        self.assertEqual(res.status_code, 200)
        return {r["row_type"]: r for r in res.data["rows"]}

    def test_profiles_that_watch_anime_get_the_row(self):
        res = self.client.get(f"/api/reco/home/?profileId={self.fan.id}")
        types = [r["row_type"] for r in res.data["rows"]]
        self.assertIn("anime", types)
        self.assertLess(types.index("anime"), types.index("for_you_3"))  # on the first screen
        row = self.rows(self.fan)["anime"]
        self.assertEqual(row["title"], "Popular anime")
        # most popular first, without the ones it played
        self.assertEqual([i["title"] for i in row["items"]], ["A3", "A4", "A5", "A6"])
        self.assertNotIn("kdrama", self.rows(self.fan))  # one K-drama liked: not enough

    def test_one_anime_is_not_enough(self):
        self.assertNotIn("anime", self.rows(self.other))

    def test_the_kids_limit_applies(self):
        row = self.rows(self.kid)["anime"]
        self.assertEqual([i["title"] for i in row["items"]], ["A5"])  # A2, A4, A6 are for adults

    def test_kdrama_row(self):
        more = Title.objects.create(type="tv", title="D2", genre="Drama", original_language="ko", popularity=80, vote_count=50)
        TitleAction.objects.create(profile=self.other, title=more, action="add_to_list")
        TitleAction.objects.create(profile=self.other, title=self.drama, action="click")
        rows = self.rows(self.other)
        self.assertEqual(rows["kdrama"]["title"], "Popular K-dramas")
        self.assertEqual([i["title"] for i in rows["kdrama"]["items"]], ["D1", "D2"])  # listed, not watched yet
