"""Free TMDB data (roadmap 8.8, users/tmdb_related.py, manage.py sync_tmdb_related): reading TMDB's
answer, saving it, "More like this" taking turns with the embeddings, search by other names.
TMDB is faked: nothing is sent to it."""
import os
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from reco.models import TitleSimilar
from reco.views import MODEL_NAME as EMBEDDINGS

from . import tmdb_related
from .management.commands.sync_tmdb_related import Command
from .models import Profile, Title, TitleAltName, User


def tmdb_movie(tmdb_id, recs=(), similar=(), alts=(), key="titles"):
    return {
        "id": tmdb_id,
        "recommendations": {"results": [{"id": i} for i in recs]},
        "similar": {"results": [{"id": i} for i in similar]},
        "alternative_titles": {key: [{"iso_3166_1": c, "title": t, "type": ""} for c, t in alts]},
    }


class ParseTests(TestCase):
    def test_related_ids(self):
        data = tmdb_movie(1, recs=[5, 6, 5], similar=[6, 7, 1])
        self.assertEqual(tmdb_related.related_tmdb_ids(data), [5, 6, 7])  # recs first, no repeats, not itself
        self.assertEqual(tmdb_related.related_tmdb_ids({}), [])

    def test_alt_names(self):
        data = tmdb_movie(1, alts=[("DE", "Stirb langsam"), ("FR", "Piège de cristal"), ("US", "Die Hard"),
                                   ("AT", "Stirb  Langsam"), ("XX", ""), ("GB", "The Die Hard")])
        self.assertEqual(
            tmdb_related.alt_names(data, "Die Hard", "Die Hard"),
            [("Stirb langsam", "stirb langsam", "DE"), ("Piège de cristal", "piège de cristal", "FR")],
        )  # its own names (articles ignored), repeats, blanks: out
        shows = tmdb_movie(1, alts=[("JP", "ブレイキング・バッド")], key="results")  # shows: "results"
        self.assertEqual(tmdb_related.alt_names(shows, "Breaking Bad")[0][0], "ブレイキング・バッド")

    def test_interleave(self):
        self.assertEqual(tmdb_related.interleave([1, 2, 3], [9, 2, 8, 7]), [1, 9, 2, 3, 8, 7])
        self.assertEqual(tmdb_related.interleave([], [4, 5]), [4, 5])
        self.assertEqual(tmdb_related.interleave([4, 5], []), [4, 5])


@mock.patch.dict(os.environ, {"TMDB_API_KEY": "test-key"})
class SyncTests(TestCase):
    def setUp(self):
        self.film = Title.objects.create(type="movie", title="Die Hard", tmdb_id=562, popularity=90)
        self.rec = Title.objects.create(type="movie", title="Lethal Weapon", tmdb_id=941, popularity=50)
        self.sim = Title.objects.create(type="movie", title="Speed", tmdb_id=1637, popularity=40)
        self.show_same_id = Title.objects.create(type="tv", title="A Show", tmdb_id=1637, popularity=30)
        self.answers = {
            "/movie/562": tmdb_movie(562, recs=[941, 99999], similar=[1637], alts=[("DE", "Stirb langsam")]),
        }

    def fake_get(self, cmd, path, **params):
        self.assertEqual(params["append_to_response"], "recommendations,similar,alternative_titles")
        return self.answers.get(path, {})

    def run_cmd(self, *args):
        out = StringIO()
        with mock.patch.object(Command, "_get", autospec=True, side_effect=self.fake_get):
            call_command("sync_tmdb_related", *args, stdout=out)
        return out.getvalue()

    def test_saves_related_and_other_names(self):
        self.run_cmd()
        rows = list(TitleSimilar.objects.filter(title=self.film, model_name="tmdb").order_by("-score")
                    .values_list("similar_id", flat=True))
        # TMDB's order, only titles in the catalog (99999 isn't), the movie Speed, not the show with the same id
        self.assertEqual(rows, [self.rec.id, self.sim.id])
        self.assertEqual(list(self.film.alt_names.values_list("name", "country")), [("Stirb langsam", "DE")])
        self.film.refresh_from_db()
        self.assertIsNotNone(self.film.related_synced_at)

    def test_resync_replaces_and_fresh_titles_wait(self):
        self.run_cmd()
        self.answers["/movie/562"] = tmdb_movie(562, recs=[1637], alts=[("FR", "Piège de cristal")])
        Title.objects.update(related_synced_at=timezone.now() - timedelta(days=61))
        self.run_cmd()
        self.assertEqual(list(TitleSimilar.objects.filter(title=self.film, model_name="tmdb")
                              .values_list("similar_id", flat=True)), [self.sim.id])
        self.assertEqual(list(self.film.alt_names.values_list("name", flat=True)), ["Piège de cristal"])

    def test_synced_recently_is_skipped(self):
        Title.objects.update(related_synced_at=timezone.now())
        self.assertIn("0 titles to sync", self.run_cmd())

    def test_failure_retried_next_run_and_unknown_marked(self):
        self.answers = {"/movie/562": None}  # kept failing
        self.assertIn("1 failed", self.run_cmd())
        self.film.refresh_from_db()
        self.assertIsNone(self.film.related_synced_at)
        self.rec.refresh_from_db()
        self.assertIsNotNone(self.rec.related_synced_at)  # {}: TMDB doesn't know it, nothing to wait for

    def test_embeddings_rows_untouched(self):
        TitleSimilar.objects.create(title=self.film, similar=self.sim, score=0.8, model_name=EMBEDDINGS)
        self.run_cmd()
        self.assertTrue(TitleSimilar.objects.filter(title=self.film, model_name=EMBEDDINGS).exists())


class MoreLikeThisTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        user = User.objects.create_user("sam@example.com", "Sam", "pw-sam-123!")
        self.kid = Profile.objects.create(user=user, name="K", age_restriction="G", is_kids=True, language_preference="en")
        self.api.force_authenticate(user)

        def movie(name, maturity=2):
            return Title.objects.create(type="movie", title=name, maturity=maturity, popularity=10)

        self.film = movie("Heat")
        self.t1, self.t2, self.e1, self.e2 = movie("T1"), movie("T2"), movie("E1"), movie("E2")
        self.adult = movie("Adult", maturity=4)
        for rank, t in enumerate([self.t1, self.adult, self.t2]):
            TitleSimilar.objects.create(title=self.film, similar=t, score=1 - rank / 100, model_name="tmdb")
        for rank, t in enumerate([self.e1, self.t1, self.e2]):
            TitleSimilar.objects.create(title=self.film, similar=t, score=0.9 - rank / 100, model_name=EMBEDDINGS)

    def names(self, headers=None):
        res = self.api.get(f"/api/titles/{self.film.id}/similar/", **(headers or {}))
        self.assertEqual(res.status_code, 200)
        return [t["title"] for t in res.json()]

    def test_takes_turns_without_repeats(self):
        with mock.patch("users.views.random.random", return_value=0.1):  # TMDB starts
            self.assertEqual(self.names(), ["T1", "E1", "Adult", "T2", "E2"])

    def test_either_list_may_start(self):
        # a fixed start would favour one list in the comparison (reco/ai_report.py)
        with mock.patch("users.views.random.random", return_value=0.9):  # the embeddings start
            self.assertEqual(self.names(), ["E1", "T1", "Adult", "E2", "T2"])

    def test_each_one_says_where_it_came_from(self):
        res = self.api.get(f"/api/titles/{self.film.id}/similar/").json()
        sources = {t["title"]: t["source"] for t in res}
        self.assertEqual(sources, {"T1": "tmdb", "Adult": "tmdb", "T2": "tmdb", "E1": "embeddings", "E2": "embeddings"})

    def test_age_limit_still_applies(self):
        self.assertNotIn("Adult", self.names({"HTTP_X_PROFILE_ID": str(self.kid.id)}))

    def test_not_synced_yet_embeddings_alone(self):
        TitleSimilar.objects.filter(model_name="tmdb").delete()
        self.assertEqual(self.names(), ["E1", "T1", "E2"])


class SearchOtherNamesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        user = User.objects.create_user("sam@example.com", "Sam", "pw-sam-123!")
        self.api.force_authenticate(user)
        self.film = Title.objects.create(type="movie", title="Die Hard", original_title="Die Hard", popularity=60)
        TitleAltName.objects.create(title=self.film, name="Stirb langsam", name_norm="stirb langsam", country="DE")

    def search(self, q):
        res = self.api.get("/api/titles/search/", {"q": q}, HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()

    def test_found_by_another_name_with_the_reason(self):
        for q in ("Stirb langsam", "stirb", "langsam"):
            [hit] = self.search(q)
            self.assertEqual(hit["id"], self.film.id, q)
            self.assertEqual(hit["match_key"], {"key": "aka", "name": "Stirb langsam"})
            self.assertEqual(hit["match"], "Also known as Stirb langsam")



class SearchOwnNameTests(TransactionTestCase):
    """A real commit: MySQL's FULLTEXT index (the main name match) doesn't see rows inside the
    transaction a TestCase runs in."""

    def test_its_own_name_needs_no_reason(self):
        cache.clear()
        api = APIClient()
        api.force_authenticate(User.objects.create_user("sam@example.com", "Sam", "pw-sam-123!"))
        film = Title.objects.create(type="movie", title="Die Hard", original_title="Die Hard", popularity=60)
        TitleAltName.objects.create(title=film, name="Die Hard: Stirb langsam", name_norm="die hard: stirb langsam")
        hits = api.get("/api/titles/search/", {"q": "Die Hard"}, HTTP_ACCEPT_LANGUAGE="en").json()
        self.assertEqual(hits[0]["id"], film.id)
        self.assertEqual(hits[0]["match"], "")  # its own name beats the other one: no "Also known as"


@mock.patch.dict(os.environ, {"TMDB_API_KEY": "test-key"})
class SyncRobustnessTests(TestCase):
    def test_names_the_database_sees_as_one(self):
        film = Title.objects.create(type="movie", title="Amelie", tmdb_id=194, popularity=10)
        data = tmdb_movie(194, alts=[("FR", "Le Fabuleux Destin"), ("CA", "Le Fabuleux Déstin")])  # one for MySQL
        Command.save(film, data)
        self.assertEqual(film.alt_names.count(), 1)

    def test_one_bad_title_never_stops_the_run(self):
        Title.objects.create(type="movie", title="Bad", tmdb_id=1, popularity=20)
        good = Title.objects.create(type="movie", title="Good", tmdb_id=2, popularity=10)
        real_save = Command.save

        def save(title, data):
            if title.title == "Bad":
                raise ValueError("broken data")
            return real_save(title, data)

        out = StringIO()
        with mock.patch.object(Command, "_get", autospec=True, return_value=tmdb_movie(2)), \
                mock.patch.object(Command, "save", side_effect=save):
            call_command("sync_tmdb_related", stdout=out, stderr=StringIO())
        self.assertIn("1 failed", out.getvalue())
        good.refresh_from_db()
        self.assertIsNotNone(good.related_synced_at)
