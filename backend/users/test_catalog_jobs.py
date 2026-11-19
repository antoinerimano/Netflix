"""The nightly catalog jobs added for fresh titles, and the dashboard that shows them:
  - sync_tmdb_new_releases: adds the released movies of TMDB's lists the catalog lacks (fake TMDB);
  - rebuild_title_indexes: indexes the titles missing from the keyword / studio / network tables,
    and re-indexes the ones clean_db just read;
  - the dashboard's jobs card (groups, schedule, summary) and catalog freshness card."""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from .models import JobRun, Title, TitleCompany, TitleKeyword, TitleNetwork, TVShowExtras, User

NEW_RELEASES = "users.management.commands.sync_tmdb_new_releases"


class FakeTMDb:
    """TMDB's lists, then /movie/{id} details for what the job adds."""

    def __init__(self, lists):
        self.lists = lists
        self.details = []

    def get(self, path, params=None):
        if path in self.lists:
            return {"results": self.lists[path] if (params or {}).get("page", 1) == 1 else [], "total_pages": 1}
        tmdb_id = int(path.split("/")[2])
        if path.endswith("/external_ids"):
            return {"imdb_id": f"tt{tmdb_id}"}
        self.details.append(tmdb_id)
        return {"id": tmdb_id, "title": f"New film {tmdb_id}", "overview": "Just out.", "release_date": "2026-11-01",
                "vote_count": 120, "vote_average": 7.1, "popularity": 80.0, "genres": [{"name": "Drama"}],
                "keywords": {"keywords": [{"name": "heist"}]}, "credits": {"cast": [], "crew": []}}


def movie(tmdb_id, votes=200, date="2026-11-01", **kw):
    return {"id": tmdb_id, "title": f"Film {tmdb_id}", "vote_count": votes, "release_date": date, **kw}


class NewReleasesTests(TestCase):
    def run_job(self, fake, *args):
        out = StringIO()
        with mock.patch(f"{NEW_RELEASES}.TMDbClient", return_value=fake), \
                mock.patch(f"{NEW_RELEASES}.datetime") as dt:
            import datetime as real
            dt.date.today.return_value = real.date(2026, 11, 19)
            dt.timedelta = real.timedelta
            call_command("sync_tmdb_new_releases", "--sleep", "0", *args, stdout=out)
        return out.getvalue()

    def test_adds_only_released_movies_with_enough_votes_that_are_not_in_the_catalog(self):
        Title.objects.create(type="movie", title="Known", tmdb_id=1)
        fake = FakeTMDb({
            "/trending/movie/day": [movie(1), movie(2), movie(3, votes=10), movie(4, date="2026-12-25")],
            "/movie/now_playing": [movie(2), movie(5)],
            "/discover/movie": [movie(6), movie(7, adult=True)],
        })
        out = self.run_job(fake)

        added = set(Title.objects.filter(type="movie").exclude(tmdb_id=1).values_list("tmdb_id", flat=True))
        self.assertEqual(added, {2, 5, 6})  # 1 known, 3 too few votes, 4 not out yet, 7 adult
        self.assertEqual(sorted(fake.details), [2, 5, 6])  # nothing asked twice, nothing known asked
        self.assertEqual(Title.objects.get(tmdb_id=5).title, "New film 5")
        self.assertIn("added 3 movies", out)
        run = JobRun.objects.get(name="sync_tmdb_new_releases")
        self.assertTrue(run.ok)

    def test_dry_run_adds_nothing(self):
        fake = FakeTMDb({"/trending/movie/day": [movie(8)], "/movie/now_playing": [], "/discover/movie": []})
        out = self.run_job(fake, "--dry-run")
        self.assertIn("would add tmdb=8", out)
        self.assertFalse(Title.objects.filter(tmdb_id=8).exists())
        self.assertEqual(fake.details, [])

    def test_a_list_that_fails_does_not_stop_the_others(self):
        class Flaky(FakeTMDb):
            def get(self, path, params=None):
                if path == "/movie/now_playing":
                    raise RuntimeError("TMDB down")
                return super().get(path, params)

        self.run_job(Flaky({"/trending/movie/day": [movie(9)], "/discover/movie": [movie(10)]}))
        self.assertEqual(set(Title.objects.values_list("tmdb_id", flat=True)), {9, 10})


class TitleIndexTests(TestCase):
    def setUp(self):
        self.film = Title.objects.create(type="movie", title="Heat", tmdb_id=949, keywords=["Heist", "Los Angeles"],
                                         production_companies=[{"id": 1, "name": "Warner Bros."}])
        self.show = Title.objects.create(type="tv", title="The Wire", tmdb_id=1438, keywords=["Baltimore"])
        TVShowExtras.objects.create(title=self.show, network_names=["HBO"])
        self.bare = Title.objects.create(type="movie", title="Nothing", tmdb_id=5)  # nothing to index

    def index(self, *args):
        out = StringIO()
        call_command("rebuild_title_indexes", *args, stdout=out)
        return out.getvalue()

    def kws(self, title):
        return set(TitleKeyword.objects.filter(title=title).values_list("keyword_norm", flat=True))

    def test_indexes_the_titles_missing_then_nothing_left(self):
        self.assertIn("titles to index: 2", self.index())
        self.assertEqual(self.kws(self.film), {"heist", "los angeles"})
        self.assertEqual(list(TitleCompany.objects.filter(title=self.film).values_list("company_norm", flat=True)),
                         ["warner bros."])
        self.assertEqual(list(TitleNetwork.objects.filter(title=self.show).values_list("network_norm", flat=True)),
                         ["hbo"])
        self.assertIn("titles to index: 0", self.index())  # the bare title isn't taken every night
        self.assertTrue(JobRun.objects.filter(name="rebuild_title_indexes", ok=True).exists())

    def test_a_title_clean_db_just_read_is_reindexed_old_keywords_go(self):
        self.index()
        Title.objects.filter(id=self.film.id).update(keywords=["Bank robbery"], tmdb_checked_at=timezone.now())
        self.index()
        self.assertEqual(self.kws(self.film), {"bank robbery"})
        self.assertEqual(self.kws(self.show), {"baltimore"})  # untouched

    def test_all(self):
        self.index()
        TitleKeyword.objects.filter(title=self.show).delete()
        Title.objects.filter(id=self.show.id).update(keywords=[])  # nothing "missing" any more
        self.assertIn("titles to index: 0", self.index("--since-days", "0"))
        self.assertIn("titles to index: 3", self.index("--all"))


class DashboardJobsTests(TestCase):
    def setUp(self):
        self.base = "/" + settings.ADMINADMIN_URL.strip("/") + "/"
        self.client.force_login(User.objects.create_superuser("admin@example.com", "Admin", "pw-admin-123!"))

    def test_jobs_by_group_with_their_schedule_and_a_summary(self):
        now = timezone.now()
        JobRun.objects.create(name="clean_db", ok=True, finished_at=now, summary="[clean_db] DONE elapsed=9000.0s")
        JobRun.objects.create(name="backup_db", ok=False, finished_at=now, error="ERROR: mysqldump failed (exit 1)")
        JobRun.objects.filter(name="clean_db").update(started_at=now - timedelta(hours=2, minutes=30))

        res = self.client.get(self.base + "dashboard/")
        self.assertEqual(res.status_code, 200)
        board = res.context["jobs"]
        self.assertEqual([g["name"] for g in board["groups"]],
                         ["Catalog", "Recommendations & home pages", "AI", "Health & safety"])
        self.assertEqual(board["counts"]["failed"], 1)
        self.assertFalse(board["all_ok"])
        safety = next(g for g in board["groups"] if g["name"] == "Health & safety")
        self.assertEqual(safety["jobs"][0]["name"], "backup_db")  # problems first
        clean = next(j for g in board["groups"] for j in g["jobs"] if j["name"] == "clean_db")
        self.assertEqual((clean["state"], clean["duration"], clean["when"]), ("ok", "2 h 30", "Every night 04:30, 2 h 30 max"))
        self.assertContains(res, "1 failed")
        self.assertContains(res, "mysqldump failed")
        self.assertContains(res, "Every night 00:30")  # the new movies job, with its schedule

    def test_catalog_freshness(self):
        Title.objects.create(type="movie", title="Read", tmdb_id=1, keywords=["x"], tmdb_checked_at=timezone.now())
        Title.objects.create(type="movie", title="Never read", tmdb_id=2, keywords=["y"])
        call_command("rebuild_title_indexes", stdout=StringIO())

        res = self.client.get(self.base + "dashboard/")
        rows = {f["label"]: f for f in res.context["freshness"]}
        self.assertEqual((rows["Read on TMDB in the last 30 days"]["pct"], rows["Read on TMDB in the last 30 days"]["ok"]),
                         (50, False))
        self.assertEqual((rows["Findable by keyword"]["pct"], rows["Findable by keyword"]["missing"]), (100, 0))
        self.assertContains(res, "Catalog freshness")
        self.assertContains(res, "Behind")


class CountryTests(TestCase):
    """The "Made in <country>" home row: titles store TMDB's English country names, the index and
    the row use ISO codes (users/countries.py)."""

    def test_country_code(self):
        from .countries import country_code

        self.assertEqual(country_code("United States of America"), "US")
        self.assertEqual(country_code("south korea"), "KR")
        self.assertEqual(country_code({"iso_3166_1": "FR", "name": "France"}), "FR")
        self.assertEqual(country_code("{'name': 'United Kingdom', 'iso_3166_1': 'GB'}"), "GB")
        self.assertEqual(country_code("jp"), "JP")
        self.assertEqual((country_code("Atlantis"), country_code(""), country_code("XX")), ("", "", ""))

    def test_index_and_home_row(self):
        from reco.views import _home_country, _row_params
        from .models import TitleCountry

        amelie = Title.objects.create(type="movie", title="Amelie", tmdb_id=194, popularity=40,
                                      production_countries=["France", "Germany"])
        lupin = Title.objects.create(type="tv", title="Lupin", tmdb_id=96677, popularity=60,
                                     production_countries=["France"])
        heat = Title.objects.create(type="movie", title="Heat", tmdb_id=949, popularity=90,
                                    production_countries=["United States of America"])
        call_command("rebuild_title_indexes", stdout=StringIO())
        self.assertEqual(set(TitleCountry.objects.filter(title=amelie).values_list("country_code", flat=True)),
                         {"FR", "DE"})

        # a profile that watched Heat, Amelie and Lupin: the US doesn't count, France it is, most popular first
        self.assertEqual(_home_country([heat.id, amelie.id, lupin.id]), ("FR", [lupin.id, amelie.id]))
        self.assertEqual(_home_country([heat.id]), ("", []))
        self.assertEqual(_row_params("country:FR", None), {"country": "FR"})  # the app names it in its language
