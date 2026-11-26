"""Streaming services per country and TMDB's trending charts (ROADMAP 9.4): users/watch_services.py,
manage.py sync_tmdb_watch_providers / sync_tmdb_charts, the browse pages' service filter and
"Recently added" sort."""
import os
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from rest_framework.request import Request
from rest_framework.test import APIClient

from .management.commands import sync_tmdb_charts
from .management.commands.sync_tmdb_watch_providers import Command as WatchCommand
from .models import Profile, Title, TitleChartEntry, TitleOnService, User
from .watch_services import region_from_accept_language, request_region, services_on


def providers(**countries):
    """TMDB's watch/providers answer: providers(FR={"flatrate": [8], "rent": [2]})."""
    return {"id": 1, "results": {
        c: {k: [{"provider_id": pid, "provider_name": str(pid)} for pid in ids] for k, ids in offers.items()}
        for c, offers in countries.items()
    }}


class ServicesTests(TestCase):
    def test_only_subscriptions_of_known_services(self):
        data = providers(
            FR={"flatrate": [8, 337, 99999], "rent": [9]},      # Netflix, Disney+, unknown; Prime only to rent
            US={"flatrate": [1796, 384], "buy": [8]},            # Netflix with ads, HBO Max -> max
            XX1={"flatrate": [8]},                                # not a country code
        )
        self.assertEqual(services_on(data), {("FR", "netflix"), ("FR", "disney"), ("US", "netflix"), ("US", "max")})
        self.assertEqual(services_on({}), set())
        self.assertEqual(services_on({"results": {"FR": None}}), set())

    def test_region(self):
        self.assertEqual(region_from_accept_language("fr-CA,fr;q=0.9,en;q=0.8"), "CA")
        self.assertEqual(region_from_accept_language("fr,en;q=0.8"), "")
        self.assertEqual(region_from_accept_language("zh-Hant-TW"), "TW")
        user = User.objects.create_user("r@example.com", "R", "pw-r-12345!")
        fr = Profile.objects.create(user=user, name="F", language_preference="fr")
        br = Profile.objects.create(user=user, name="B", language_preference="pt-BR")

        def region(query="", accept="", profile=None):
            req = Request(RequestFactory().get(f"/x/{query}", HTTP_ACCEPT_LANGUAGE=accept))
            return request_region(req, profile)

        self.assertEqual(region("?region=de"), "DE")                         # the app's (browser region)
        self.assertEqual(region("?region=ZZ", "en-GB"), "GB")                # not a country: the header's
        self.assertEqual(region("", "fr", fr), "FR")                         # no region anywhere: the profile's language
        self.assertEqual(region("", "", br), "BR")
        self.assertEqual(region(), "US")


@mock.patch.dict(os.environ, {"TMDB_API_KEY": "test-key"})
class SyncWatchProvidersTests(TestCase):
    def setUp(self):
        self.film = Title.objects.create(type="movie", title="Heat", tmdb_id=949, popularity=90)
        self.show = Title.objects.create(type="tv", title="Dark", tmdb_id=70523, popularity=80)
        self.unknown = Title.objects.create(type="movie", title="Gone", tmdb_id=1, popularity=10)
        self.answers = {
            "/movie/949/watch/providers": providers(US={"flatrate": [8, 9]}, FR={"flatrate": [8]}),
            "/tv/70523/watch/providers": providers(DE={"flatrate": [8]}),
            "/movie/1/watch/providers": {},                                   # 404
        }

    def run_cmd(self, *args):
        out = StringIO()
        with mock.patch.object(WatchCommand, "_get", autospec=True,
                               side_effect=lambda cmd, path, **p: self.answers.get(path)):
            call_command("sync_tmdb_watch_providers", *args, stdout=out)
        return out.getvalue()

    def test_saves_services_and_replaces_them_next_time(self):
        out = self.run_cmd()
        self.assertIn("3 titles read: 4 service offers, 0 failed", out)
        self.assertEqual(
            set(TitleOnService.objects.values_list("title__title", "country", "service")),
            {("Heat", "US", "netflix"), ("Heat", "US", "prime"), ("Heat", "FR", "netflix"), ("Dark", "DE", "netflix")},
        )
        self.assertFalse(Title.objects.filter(services_synced_at__isnull=True).exists())
        # read again (--days 0): Heat left Netflix in France
        self.answers["/movie/949/watch/providers"] = providers(US={"flatrate": [8]})
        self.run_cmd("--days", "0")
        self.assertEqual(set(TitleOnService.objects.filter(title=self.film).values_list("country", "service")),
                         {("US", "netflix")})

    def test_a_failed_call_is_tried_again(self):
        self.answers["/tv/70523/watch/providers"] = None
        out = self.run_cmd()
        self.assertIn("1 failed", out)
        self.show.refresh_from_db()
        self.assertIsNone(self.show.services_synced_at)
        self.assertIn("1 titles to read", self.run_cmd())  # only the show is left (the others are fresh)


class FakeTMDb:
    def __init__(self, pages):
        self.pages = pages  # path -> [page 1 results, page 2 results...], or an exception

    def get(self, path, params=None):
        pages = self.pages[path]
        if isinstance(pages, Exception):
            raise pages
        page = params["page"]
        return {"results": pages[page - 1], "total_pages": len(pages)}


class SyncChartsTests(TestCase):
    def setUp(self):
        self.a = Title.objects.create(type="movie", title="A", tmdb_id=10)
        self.b = Title.objects.create(type="movie", title="B", tmdb_id=20)
        self.show = Title.objects.create(type="tv", title="S", tmdb_id=10)   # same TMDB id, a show

    def run_cmd(self, pages):
        with mock.patch.object(sync_tmdb_charts, "TMDbClient", return_value=FakeTMDb(pages)):
            call_command("sync_tmdb_charts", stdout=StringIO())

    def chart(self, chart):
        return list(TitleChartEntry.objects.filter(chart=chart).values_list("position", "title__title"))

    def test_keeps_tmdb_positions_of_the_titles_in_the_catalog(self):
        self.run_cmd({
            "/trending/movie/day": [[{"id": 99}, {"id": 20}, {"id": 666, "adult": True}], [{"id": 20}, {"id": 10}]],
            "/trending/tv/week": [[{"id": 10}]],
        })
        # 99 isn't in the catalog, the adult one is left out, 20 only once
        self.assertEqual(self.chart("movie_day"), [(2, "B"), (3, "A")])
        self.assertEqual(self.chart("tv_week"), [(1, "S")])

    def test_a_chart_that_fails_keeps_its_last_list(self):
        self.run_cmd({"/trending/movie/day": [[{"id": 10}]], "/trending/tv/week": [[{"id": 10}]]})
        self.run_cmd({"/trending/movie/day": [[{"id": 20}]], "/trending/tv/week": RuntimeError("TMDB down")})
        self.assertEqual(self.chart("movie_day"), [(1, "B")])
        self.assertEqual(self.chart("tv_week"), [(1, "S")])
        with self.assertRaises(RuntimeError):
            self.run_cmd({"/trending/movie/day": RuntimeError("x"), "/trending/tv/week": RuntimeError("y")})


class BrowseServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("b@example.com", "B", "pw-b-12345!")
        self.profile = Profile.objects.create(user=self.user, name="B", language_preference="fr", age_restriction="NC-17")
        self.kid = Profile.objects.create(user=self.user, name="K", language_preference="en", age_restriction="G", is_kids=True)
        self.client.force_authenticate(self.user)
        self.old = Title.objects.create(type="movie", title="Old", popularity=90, maturity=0)
        self.adult = Title.objects.create(type="movie", title="Adult", popularity=80, maturity=4)
        self.new = Title.objects.create(type="movie", title="New", popularity=10, maturity=0)
        self.show = Title.objects.create(type="tv", title="Show", popularity=50, maturity=0)
        for t in (self.old, self.adult, self.show):
            TitleOnService.objects.create(title=t, country="FR", service="netflix")
        TitleOnService.objects.create(title=self.new, country="US", service="netflix")
        TitleOnService.objects.create(title=self.new, country="FR", service="prime")

    def names(self, query, profile=None):
        res = self.client.get(f"/api/titles/{query}", HTTP_X_PROFILE_ID=str((profile or self.profile).id))
        self.assertEqual(res.status_code, 200)
        return [t["title"] for t in res.data["results"]]

    def test_service_filter_in_the_visitors_country(self):
        self.assertEqual(self.names("?type=movie&service=netflix&region=FR"), ["Old", "Adult"])
        self.assertEqual(self.names("?type=movie&service=netflix&region=US"), ["New"])
        # no region sent: the French profile's
        self.assertEqual(self.names("?type=movie&service=netflix"), ["Old", "Adult"])
        # the kids profile's limit still applies
        self.assertEqual(self.names("?type=movie&service=netflix&region=FR", self.kid), ["Old"])
        # an unknown service filters nothing
        self.assertEqual(len(self.names("?type=movie&service=nope")), 3)

    def test_recently_added_sort(self):
        self.assertEqual(self.names("?type=movie&sort=added"), ["New", "Adult", "Old"])

    def test_services_list(self):
        res = self.client.get("/api/titles/services/?region=FR")
        self.assertEqual(res.data, {"region": "FR", "services": [
            {"key": "netflix", "name": "Netflix", "count": 3}, {"key": "prime", "name": "Prime Video", "count": 1},
        ]})
        res = self.client.get("/api/titles/services/?region=FR&type=tv")
        self.assertEqual([s["key"] for s in res.data["services"]], ["netflix"])
        self.assertEqual(self.client.get("/api/titles/services/?region=JP").data["services"], [])
