"""Top 10 and "On <service>" home rows (reco/top10.py, ROADMAP 9.4)."""
from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import Profile, Title, TitleChartEntry, TitleOnService, User
from .models import RecoHomeSnapshot, TitleAction
from .top10 import blend


class BlendTests(TestCase):
    def test_tmdb_order_until_there_are_enough_plays(self):
        self.assertEqual(blend([1, 2, 3], {3: 5}, min_people=30), [1, 2, 3])
        self.assertEqual(blend([1, 2, 3], {}, min_people=0), [1, 2, 3])
        self.assertEqual(blend(list(range(1, 30)), {}, size=20), list(range(1, 21)))

    def test_our_plays_move_titles_up_and_bring_new_ones(self):
        chart = list(range(1, 11))
        # 10 is last on TMDB but everybody here plays it; 99 isn't on TMDB's chart at all
        ids = blend(chart, {10: 40, 99: 30, 1: 2}, min_people=30, own_weight=0.5)
        self.assertEqual(ids[0], 10)
        self.assertLess(ids.index(99), ids.index(5))
        self.assertLess(ids.index(1), ids.index(2))  # TMDB's first stays above TMDB's second


class HomeRowsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("t@example.com", "T", "pw-t-12345!")
        self.profile = Profile.objects.create(user=self.user, name="A", language_preference="en", age_restriction="NC-17")
        self.kid = Profile.objects.create(user=self.user, name="K", language_preference="en", age_restriction="G", is_kids=True)
        self.client.force_authenticate(self.user)
        now = timezone.now()
        self.movies = [Title.objects.create(type="movie", title=f"M{i}", popularity=100 - i, maturity=0 if i % 2 else 4)
                       for i in range(1, 13)]
        self.shows = [Title.objects.create(type="tv", title=f"S{i}", popularity=50 - i, maturity=0) for i in range(1, 4)]
        for pos, t in enumerate(self.movies, start=1):
            TitleChartEntry.objects.create(chart="movie_day", position=pos, title=t, synced_at=now)
        for pos, t in enumerate(self.shows, start=1):
            TitleChartEntry.objects.create(chart="tv_week", position=pos, title=t, synced_at=now)
        for t in self.movies:  # 12 titles on Netflix in France, 3 on Prime Video (too few for a row)
            TitleOnService.objects.create(title=t, country="FR", service="netflix")
        for t in self.shows:
            TitleOnService.objects.create(title=t, country="FR", service="prime")
        snap_rows = [{"row_type": f"for_you_{i}", "title": f"Row {i}", "items": [{"id": self.shows[0].id, "title": "S1"}]}
                     for i in range(5)]
        for p in (self.profile, self.kid):
            RecoHomeSnapshot.objects.update_or_create(profile=p, defaults={
                "algo_version": "home_v1", "payload": {"rows": snap_rows}, "expires_at": now + timedelta(hours=1)})

    def rows(self, profile=None, query=""):
        res = self.client.get(f"/api/reco/home/?profileId={(profile or self.profile).id}{query}")
        self.assertEqual(res.status_code, 200)
        return res.data["rows"]

    def test_top10_rows_on_the_first_screen(self):
        rows = self.rows(query="&region=US")
        types = [r["row_type"] for r in rows]
        self.assertEqual(types[:4], ["for_you_0", "top10_movies", "for_you_1", "top10_tv"])
        movies = rows[1]
        self.assertEqual([i["title"] for i in movies["items"]], [f"M{i}" for i in range(1, 13)])
        self.assertEqual(movies["title"], "Top 10 movies today")
        self.assertNotIn("service:netflix", types)  # nothing on Netflix in the US

    def test_age_limit_applies_to_the_top10(self):
        rows = {r["row_type"]: r for r in self.rows(self.kid)}
        self.assertEqual([i["title"] for i in rows["top10_movies"]["items"]], ["M1", "M3", "M5", "M7", "M9", "M11"])

    def test_our_plays_count_once_there_are_enough(self):
        others = [Profile.objects.create(user=self.user, name=f"P{i}", language_preference="en") for i in range(30)]
        for p in others:
            TitleAction.objects.create(profile=p, title=self.movies[-1], action="outbound")
        TitleAction.objects.create(profile=self.profile, title=self.shows[-1], action="outbound")  # 1 play: not enough
        rows = {r["row_type"]: r for r in self.rows()}
        self.assertEqual(rows["top10_movies"]["items"][0]["title"], "M12")
        self.assertEqual([i["title"] for i in rows["top10_tv"]["items"]], ["S1", "S2", "S3"])

    def test_service_rows_in_the_visitors_country(self):
        rows = self.rows(query="&region=FR")
        svc = [r for r in rows if r["row_type"].startswith("service:")]
        self.assertEqual([r["row_type"] for r in svc], ["service:netflix"])  # Prime Video: only 3 titles
        self.assertEqual(svc[0]["params"], {"name": "Netflix", "service": "netflix"})
        self.assertEqual(svc[0]["title"], "On Netflix")
        self.assertEqual(svc[0]["items"][0]["title"], "M1")  # most popular first
        # from the browser's Accept-Language when the app sends no region
        res = self.client.get(f"/api/reco/home/?profileId={self.profile.id}", HTTP_ACCEPT_LANGUAGE="fr-FR,fr")
        self.assertIn("service:netflix", [r["row_type"] for r in res.data["rows"]])

    def test_no_chart_no_row(self):
        TitleChartEntry.objects.all().delete()
        types = [r["row_type"] for r in self.rows()]
        self.assertNotIn("top10_movies", types)
        self.assertNotIn("top10_tv", types)
