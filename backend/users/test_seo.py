"""users/seo.py: page shells with per-page tags, status codes, sitemaps."""
import json
import re
import tempfile
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.conf import settings
from django.test import TestCase, override_settings

from . import seo
from .models import Actor, Title, TitleTranslation

SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Tauruss – Stream Movies</title>
  <meta name="description" content="Home description" />
  <link rel="canonical" href="https://tauruss.top/" />
  <meta name="robots" content="index, follow" />
  <meta property="og:title" content="Home" />
  <meta property="og:image" content="https://tauruss.top/logo/og-image.jpg" />
  <meta name="twitter:card" content="summary_large_image" />
  <script type="module" src="/static/js/index-abc123.js"></script>
</head>
<body><div id="root"></div></body>
</html>
"""


def _tags(html, pattern):
    return re.findall(pattern, html)


class SeoPagesTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._dir = tempfile.TemporaryDirectory()
        cls.index = Path(cls._dir.name) / "index.html"
        cls.index.write_text(SHELL, encoding="utf-8")
        cls._settings = override_settings(FRONTEND_INDEX_FILE=str(cls.index), SITE_URL="https://tauruss.top")
        cls._settings.enable()

    @classmethod
    def tearDownClass(cls):
        cls._settings.disable()
        cls._dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        self.movie = Title.objects.create(
            type="movie", title="Heat", release_year=1995, release_date="1995-12-15",
            description="A group of high-end professional thieves start to feel the heat from the LAPD.",
            poster="https://image.tmdb.org/t/p/w500/heat.jpg", genre="Crime, Drama", director="Michael Mann",
            vote_average=7.9, vote_count=7000,
        )
        self.show = Title.objects.create(type="tv", title="The Wire", first_air_date="2002-06-02",
                                         description="Baltimore drug scene.")
        TitleTranslation.objects.create(title=self.movie, language="fr", name="Heat (FR)",
                                        overview="Des voleurs professionnels.")
        Actor.objects.create(title=self.movie, name="Al Pacino", name_norm="al pacino", tmdb_id=1158,
                             profile_path="/pacino.jpg")

    def test_movie_page_has_its_own_tags(self):
        res = self.client.get(f"/movies/{self.movie.pk}")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn("<title>Heat (1995) | Tauruss</title>", html)
        self.assertEqual(len(_tags(html, r"<title>")), 1)  # the shell's title is gone
        self.assertEqual(len(_tags(html, r'name="description"')), 1)
        self.assertIn("high-end professional thieves", html)
        self.assertIn(f'<link rel="canonical" href="https://tauruss.top/movies/{self.movie.pk}" />', html)
        self.assertIn('content="https://image.tmdb.org/t/p/w500/heat.jpg"', html)
        self.assertIn('content="video.movie"', html)
        self.assertNotIn("og-image.jpg", html)
        self.assertIn("/static/js/index-abc123.js", html)  # the app still loads
        self.assertEqual(res["Cache-Control"], "no-cache")

    def test_hreflang_for_every_language(self):
        html = self.client.get(f"/movies/{self.movie.pk}").content.decode()
        self.assertIn(f'hreflang="fr" href="https://tauruss.top/movies/{self.movie.pk}?lng=fr"', html)
        self.assertIn(f'hreflang="zh-Hans" href="https://tauruss.top/movies/{self.movie.pk}?lng=zh"', html)
        self.assertIn(f'hreflang="x-default" href="https://tauruss.top/movies/{self.movie.pk}"', html)
        self.assertEqual(len(_tags(html, r'rel="alternate"')), 14)  # 13 languages + x-default

    def test_translated_page(self):
        html = self.client.get(f"/movies/{self.movie.pk}?lng=fr").content.decode()
        self.assertIn("<title>Heat (FR) (1995) | Tauruss</title>", html)
        self.assertIn("Des voleurs professionnels.", html)
        self.assertIn('<html lang="fr"', html)
        self.assertIn('content="fr_FR"', html)
        self.assertIn(f'rel="canonical" href="https://tauruss.top/movies/{self.movie.pk}?lng=fr"', html)

    def test_json_ld(self):
        html = self.client.get(f"/movies/{self.movie.pk}").content.decode()
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        data = json.loads(blocks[-1])
        self.assertEqual(data["@type"], "Movie")
        self.assertEqual(data["name"], "Heat")
        self.assertEqual(data["director"]["name"], "Michael Mann")
        self.assertEqual(data["genre"], ["Crime", "Drama"])
        self.assertEqual(data["aggregateRating"]["ratingValue"], 7.9)

    def test_show_page_and_canonical_follows_type(self):
        html = self.client.get(f"/movies/{self.show.pk}").content.decode()
        self.assertIn("<title>The Wire (2002) | Tauruss</title>", html)
        self.assertIn(f'rel="canonical" href="https://tauruss.top/tv/{self.show.pk}"', html)
        self.assertIn('"@type": "TVSeries"', html)

    def test_text_is_escaped(self):
        self.movie.title = 'Bad "</title><script>x</script>'
        self.movie.save()
        html = self.client.get(f"/movies/{self.movie.pk}").content.decode()
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;/title&gt;", html)

    def test_missing_title_is_404(self):
        res = self.client.get("/movies/999999")
        self.assertEqual(res.status_code, 404)
        html = res.content.decode()
        self.assertIn('<meta name="robots" content="noindex" />', html)
        self.assertIn("/static/js/index-abc123.js", html)  # the app shows its own "Page not found"

    def test_actor_page(self):
        res = self.client.get("/actor/1158")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn("<title>Al Pacino | Tauruss</title>", html)
        self.assertIn("Movies and TV shows with Al Pacino.", html)
        self.assertIn("https://image.tmdb.org/t/p/w780/pacino.jpg", html)
        self.assertEqual(self.client.get("/actor/42").status_code, 404)

    def test_translated_fallback_description(self):
        self.show.description = ""
        self.show.save()
        html = self.client.get(f"/tv/{self.show.pk}?lng=fr").content.decode()
        self.assertIn("Regardez The Wire sur Tauruss.", html)

    def test_app_routes_200_unknown_404(self):
        for path in ("/", "/movies", "/tv/", "/search", "/login", "/watch/12", "/account/abc",
                     "/reset-password/u/t", "/confirm-email-change", "/admin/movies"):
            self.assertEqual(self.client.get(path).status_code, 200, path)
        for path in ("/nope", "/movies/abc", "/wp-login.php", "/movies/1/extra"):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_every_app_route_is_known(self):
        """Each <Route path> of the frontend (App.jsx) loads with 200, not a 404 page: a route
        missing from APP_ROUTES worked inside the app but not on a reload or an opened link."""
        app = Path(settings.BASE_DIR).parent / "frontend" / "src" / "App.jsx"
        if not app.exists():
            self.skipTest("frontend not checked out")
        paths = re.findall(r'<Route\s+path="([^"]+)"', app.read_text(encoding="utf-8"))
        self.assertGreater(len(paths), 20)
        own_views = ("/movies/:", "/tv/:", "/actor/:", "/l/:")  # their own pages (title / actor / list tags)
        for path in paths:
            if path in ("*", "/design-system") or path.startswith(own_views):
                continue
            url = re.sub(r":\w+", "x", path.replace("/*", "/x"))
            self.assertEqual(self.client.get(url).status_code, 200, f"{path} -> add it to seo.APP_ROUTES")

    def test_api_404_stays_json(self):
        res = self.client.get("/api/does-not-exist/")
        self.assertEqual(res.status_code, 404)
        self.assertNotIn("static/js", res.content.decode())


class SeoSitemapTests(TestCase):
    def setUp(self):
        cache.clear()
        self.m1 = Title.objects.create(type="movie", title="A")
        self.m2 = Title.objects.create(type="movie", title="B")
        self.tv = Title.objects.create(type="tv", title="C")
        Actor.objects.create(title=self.m1, name="X", name_norm="x", tmdb_id=7)
        Actor.objects.create(title=self.m2, name="X", name_norm="x", tmdb_id=7)  # same actor twice

    @override_settings(SITE_URL="https://tauruss.top")
    def test_index_and_sections(self):
        res = self.client.get("/sitemap.xml")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/xml; charset=utf-8")
        body = res.content.decode()
        for name in ("sitemap-static.xml", "sitemap-movies-1.xml", "sitemap-tv-1.xml", "sitemap-actors-1.xml"):
            self.assertIn(f"<loc>https://tauruss.top/{name}</loc>", body)

        movies = self.client.get("/sitemap-movies-1.xml").content.decode()
        self.assertIn(f"<loc>https://tauruss.top/movies/{self.m1.pk}</loc>", movies)
        self.assertNotIn(f"/movies/{self.tv.pk}<", movies)
        actors = self.client.get("/sitemap-actors-1.xml").content.decode()
        self.assertEqual(actors.count("/actor/7<"), 1)
        self.assertIn("<loc>https://tauruss.top/tv</loc>", self.client.get("/sitemap-static.xml").content.decode())

    def test_unknown_parts_404(self):
        self.assertEqual(self.client.get("/sitemap-movies-2.xml").status_code, 404)
        self.assertEqual(self.client.get("/sitemap-users-1.xml").status_code, 404)

    def test_split_into_files(self):
        with mock.patch.object(seo, "SITEMAP_URLS_PER_FILE", 1):
            body = self.client.get("/sitemap.xml").content.decode()
            self.assertIn("sitemap-movies-2.xml", body)
            self.assertNotIn("sitemap-movies-3.xml", body)
            self.assertIn(f"/movies/{self.m2.pk}<", self.client.get("/sitemap-movies-2.xml").content.decode())


class ShellFetchTests(TestCase):
    """index.html from the frontend container: revalidated every time, last copy if it's down."""

    def _res(self, status, text="", etag=None):
        r = mock.Mock(status_code=status, text=text, headers={"etag": etag} if etag else {})
        r.raise_for_status = mock.Mock(side_effect=None if status < 400 else seo.requests.HTTPError())
        return r

    @override_settings(FRONTEND_INDEX_FILE="", FRONTEND_INDEX_URL="http://frontend/index.html")
    def test_revalidates_and_survives_outage(self):
        shell = seo._Shell()
        with mock.patch.object(seo.requests, "get") as get:
            get.return_value = self._res(200, "<html>v1</html>", etag='"1"')
            self.assertEqual(shell.get(), "<html>v1</html>")
            get.return_value = self._res(304)
            self.assertEqual(shell.get(), "<html>v1</html>")
            self.assertEqual(get.call_args.kwargs["headers"]["If-None-Match"], '"1"')
            get.return_value = self._res(200, "<html>v2</html>", etag='"2"')
            self.assertEqual(shell.get(), "<html>v2</html>")  # a deploy shows at once
            get.side_effect = seo.requests.ConnectionError()
            self.assertEqual(shell.get(), "<html>v2</html>")
