"""Anime / K-drama sections (ROADMAP 9.5): users/sections.py, Title.section, the browse pages'
?section= filter, rebuild_title_indexes, the scout's anime test (export_providers, import_providers)."""
from datetime import date, timedelta
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from .management.commands.export_providers import anime_episodes
from .management.commands.rebuild_title_indexes import update_sections
from .models import Episode, Profile, Provider, Season, Title, User
from .provider_import import import_catalog, scout_anime
from .sections import title_section


def mk(title, kind="tv", genre="Animation", lang="ja", **kw):
    kw.setdefault("popularity", 50)
    kw.setdefault("vote_count", 100)
    return Title.objects.create(type=kind, title=title, genre=genre, original_language=lang, **kw)


class SectionRuleTests(TestCase):
    def test_anime(self):
        self.assertEqual(title_section("tv", "Animation, Action & Adventure", "ja"), "anime")
        self.assertEqual(title_section("movie", "Animation, Fantasy", "ja"), "anime")         # Spirited Away
        self.assertEqual(title_section("tv", "Animation", "en", keywords=["anime", "magic"]), "anime")  # keyword 210024
        self.assertEqual(title_section("tv", "Animation", "", ["Japan"]), "anime")             # no language: made in Japan
        self.assertEqual(title_section("movie", "Animation, Family", "en", ["United States of America"]), "")  # Pixar
        self.assertEqual(title_section("movie", "Animation", "en", ["Japan", "United States of America"]), "")
        self.assertEqual(title_section("tv", "Drama", "ja"), "")                               # live action

    def test_kdrama(self):
        self.assertEqual(title_section("tv", "Drama, Mystery", "ko"), "kdrama")
        self.assertEqual(title_section("tv", "Drama", "", ["South Korea"]), "kdrama")
        self.assertEqual(title_section("movie", "Drama", "ko"), "")                             # Parasite: a film
        self.assertEqual(title_section("tv", "Comedy", "ko"), "")
        self.assertEqual(title_section("tv", "Animation, Drama", "ko"), "")                     # Korean animation
        self.assertEqual(title_section("tv", "Drama", "en", ["South Korea"]), "")

    def test_save_works_it_out_with_update_fields_too(self):
        t = mk("Frieren")
        self.assertEqual(t.section, "anime")
        t.original_language = "en"
        t.save(update_fields=["original_language"])
        self.assertEqual(Title.objects.get(id=t.id).section, "")
        # a row read with .only() and saved without the section's fields: left as it is, none of
        # them read (the belongs_to_collection read was there before)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        light = Title.objects.only("id", "poster").get(id=t.id)
        light.poster = "https://img/p.jpg"
        with CaptureQueriesContext(connection) as ctx:
            light.save(update_fields=["poster"])
        sql = " ".join(q["sql"] for q in ctx.captured_queries)
        self.assertNotIn("genre", sql)
        self.assertNotIn("section", sql)

    def test_rebuild_title_indexes_fixes_bulk_written_titles(self):
        a = mk("Bulk anime")
        k = mk("Bulk drama", genre="Drama", lang="ko")
        Title.objects.filter(id__in=[a.id, k.id]).update(section="")  # what a bulk sync leaves
        Title.objects.filter(id=mk("Was anime").id).update(genre="Comedy")
        self.assertEqual(update_sections(), 3)
        self.assertEqual(dict(Title.objects.values_list("title", "section")),
                         {"Bulk anime": "anime", "Bulk drama": "kdrama", "Was anime": ""})
        out = StringIO()
        call_command("rebuild_title_indexes", stdout=out)
        self.assertIn("sections (anime / K-drama) changed: 0", out.getvalue())


class BrowseSectionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("s@example.com", "S", "pw-s-12345!")
        self.profile = Profile.objects.create(user=self.user, name="A", language_preference="en", age_restriction="NC-17")
        self.kid = Profile.objects.create(user=self.user, name="K", language_preference="en", age_restriction="G", is_kids=True)
        self.client.force_authenticate(self.user)
        mk("Kids anime", maturity=0, popularity=90)
        mk("Adult anime", maturity=4, popularity=80, genre="Animation, Crime")
        mk("Anime film", kind="movie", maturity=1, popularity=70)
        mk("K drama", genre="Drama", lang="ko", maturity=3, popularity=60)
        mk("Pixar", kind="movie", lang="en", maturity=0, popularity=100)

    def names(self, query, profile=None):
        res = self.client.get(f"/api/titles/{query}", HTTP_X_PROFILE_ID=str((profile or self.profile).id))
        self.assertEqual(res.status_code, 200)
        return [t["title"] for t in res.data["results"]]

    def test_section_filter(self):
        self.assertEqual(self.names("?section=anime"), ["Kids anime", "Adult anime", "Anime film"])
        self.assertEqual(self.names("?section=anime&type=movie"), ["Anime film"])
        self.assertEqual(self.names("?section=kdrama"), ["K drama"])
        self.assertEqual(self.names("?section=anime", self.kid), ["Kids anime"])  # the kids limit still applies
        self.assertEqual(len(self.names("?section=nope")), 5)

    def test_genres_of_a_section(self):
        res = self.client.get("/api/titles/genres/?section=anime")
        self.assertEqual(res.data, ["Animation", "Crime"])

    def test_title_page_says_its_section(self):
        anime = Title.objects.get(title="Kids anime")
        self.assertEqual(self.client.get(f"/api/titles/{anime.id}/").data["section"], "anime")


class ScoutAnimeTests(TestCase):
    def test_anime_test_episodes_late_seasons_of_the_popular_anime(self):
        show = mk("Big anime", tmdb_id=500, imdb_code="tt500", popularity=99)
        mk("Live action", genre="Drama", lang="ja", tmdb_id=501, popularity=100)
        today = date.today()
        for n, aired in ((1, today - timedelta(days=900)), (2, today - timedelta(days=30)), (3, today + timedelta(days=30))):
            season = Season.objects.create(tv=show, season_number=n)
            Episode.objects.create(season=season, episode_number=1, name="E1", air_date=aired, runtime=23)
        eps = anime_episodes()
        self.assertEqual([e["name"] for e in eps], ["One Piece 1x01", "Big anime 2x01"])  # season 3 hasn't aired
        self.assertEqual(eps[1], {"tmdb": 500, "imdb": "tt500", "season": 2, "episode": 1,
                                  "name": "Big anime 2x01", "minutes": 23})

    def test_scout_anime_result(self):
        self.assertAlmostEqual(scout_anime({"anime_verified": "2/3"}), 2 / 3)
        self.assertEqual(scout_anime({"anime_verified": "0/2"}), 0.0)
        self.assertIsNone(scout_anime({"verified": "5/5"}))          # an older scout: not tested
        self.assertIsNone(scout_anime({"anime_verified": "0/0"}))
        p = Provider.objects.create(key="vidx", label="Vidx", domain="https://vidx.to", movie_path="/movie/{tmdb_id}")
        import_catalog({"generated": "2026-11-25 03:00", "probe_title": {"tmdb": 1, "imdb": "tt1"}, "providers": [
            {"provider": "vidx", "site_count": 2, "sites": [], "hosts": ["vidx.to"],
             "health": {"state": "partial", "verified": "3/5", "anime_verified": "1/2", "detail": "x"}},
        ]})
        p.refresh_from_db()
        self.assertEqual(p.scout_anime, 0.5)
        self.assertIn("anime 1/2", p.scout_check)
        res = APIClient().get("/api/providers/")
        self.assertEqual(res.data[0]["scout_anime"], 0.5)
