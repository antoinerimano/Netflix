"""Trailers: which video is picked, and the export / import trailer-worker/ talks to."""
import io
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings

from .models import Title
from .trailers import pick_trailer_url, preview_path, youtube_key

CDN = "https://cdn.example.com"


def video(key, name="Official Trailer", kind="Trailer", official=True, lang="en", published="2020-01-01T00:00:00.000Z"):
    return {"site": "YouTube", "key": key, "name": name, "type": kind, "official": official,
            "iso_639_1": lang, "published_at": published, "size": 1080}


def tmdb(*videos, original_language="en"):
    return {"original_language": original_language, "videos": {"results": list(videos)}}


class PickTrailerTests(TestCase):
    def test_official_trailer_over_an_earlier_fan_upload(self):
        full = tmdb(video("fanUpload01", "Trailer (fan made)", official=False), video("officialKey"))
        self.assertEqual(pick_trailer_url(full), "https://www.youtube.com/watch?v=officialKey")

    def test_a_show_gets_its_series_trailer_not_a_later_season(self):
        full = tmdb(
            video("season4Key1", "Season 4 Official Trailer", published="2023-05-01T00:00:00.000Z"),
            video("season1Key1", "Official Trailer", published="2016-07-01T00:00:00.000Z"),
        )
        self.assertIn("season1Key1", pick_trailer_url(full))

    def test_original_language_first_then_english(self):
        full = tmdb(video("englishKey1", lang="en"), video("koreanKey01", lang="ko"), original_language="ko")
        self.assertIn("koreanKey01", pick_trailer_url(full))
        self.assertIn("englishKey1", pick_trailer_url(tmdb(video("englishKey1"), video("germanKey01", lang="de"))))

    def test_trailer_over_teaser_and_never_a_clip(self):
        full = tmdb(video("clipKey0001", "Opening scene", kind="Clip"), video("teaserKey01", kind="Teaser"))
        self.assertIn("teaserKey01", pick_trailer_url(full))
        self.assertEqual(pick_trailer_url(tmdb(video("clipKey0001", kind="Clip"))), "")

    def test_re_release_trailer_loses_to_the_original(self):
        full = tmdb(
            video("rerelease01", "4K Re-release Trailer", published="2023-01-01T00:00:00.000Z"),
            video("original001", "Trailer", published="1999-01-01T00:00:00.000Z"),
        )
        self.assertIn("original001", pick_trailer_url(full))

    def test_youtube_key_and_paths(self):
        self.assertEqual(youtube_key("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(youtube_key("https://youtu.be/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(youtube_key("https://example.com/x.mp4"), "")
        # a movie and a show with the same TMDB id never share a file
        self.assertNotEqual(preview_path("movie", 1399, "k"), preview_path("tv", 1399, "k"))


@override_settings(BUNNY_CDN_BASE=CDN)
class TrailerJobsTests(TestCase):
    def setUp(self):
        yt = "https://www.youtube.com/watch?v="
        # a movie and a show with the same TMDB id: the old trailers/{id}.mp4 clips collided
        self.movie = Title.objects.create(type="movie", tmdb_id=1399, title="Some Film", trailer_url=yt + "movieKey001",
                                          trailer_clip_url=f"{CDN}/trailers/1399.mp4", popularity=5)
        self.show = Title.objects.create(type="tv", tmdb_id=1399, title="Some Show", trailer_url=yt + "showKey0001",
                                         popularity=50)
        self.done = Title.objects.create(type="movie", tmdb_id=7, title="Done", trailer_url=yt + "doneKey0001",
                                         trailer_clip_url=f"{CDN}/previews/movie/7-doneKey0001.mp4")
        Title.objects.create(type="movie", tmdb_id=8, title="No trailer")

    def export(self, *args):
        out, err = io.StringIO(), io.StringIO()
        call_command("export_trailer_jobs", *args, stdout=out, stderr=err)
        return json.loads(out.getvalue())["jobs"]

    def import_results(self, results, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"version": 1, "results": results}, f)
        out = io.StringIO()
        call_command("import_trailer_results", f.name, *args, stdout=out)
        return out.getvalue()

    def result(self, title, status="ok", key=None):
        key = key or youtube_key(title.trailer_url)
        return {"type": title.type, "tmdb_id": title.tmdb_id, "youtube_key": key, "status": status,
                "path": preview_path(title.type, title.tmdb_id, key), "url": "https://evil.example/x.mp4"}

    def test_export_lists_titles_without_the_clip_of_their_trailer_most_popular_first(self):
        jobs = self.export()
        self.assertEqual([(j["type"], j["tmdb_id"]) for j in jobs], [("tv", 1399), ("movie", 1399)])
        self.assertEqual(jobs[0]["path"], "previews/tv/1399-showKey0001.mp4")
        self.assertEqual(jobs[0]["title"], "Some Show")
        self.assertEqual(len(self.export("--limit", "1")), 1)
        self.assertEqual([j["type"] for j in self.export("--type", "movie")], ["movie"])

    def test_import_saves_the_clip_on_the_right_title_from_the_cdn_address(self):
        self.import_results({"a": self.result(self.movie), "b": self.result(self.show)})
        self.movie.refresh_from_db()
        self.show.refresh_from_db()
        # the URL is built here, not taken from the file
        self.assertEqual(self.movie.trailer_clip_url, f"{CDN}/previews/movie/1399-movieKey001.mp4")
        self.assertEqual(self.show.trailer_clip_url, f"{CDN}/previews/tv/1399-showKey0001.mp4")
        self.assertEqual(self.export(), [])  # nothing left to do
        self.assertIn("unchanged: 2", self.import_results({"a": self.result(self.movie), "b": self.result(self.show)}))

    def test_import_skips_errors_stale_trailers_and_dry_runs(self):
        out = self.import_results({
            "a": self.result(self.show, status="error"),
            "b": self.result(self.movie, key="oldTrailer1"),  # TMDB changed the trailer since
        })
        self.assertIn("saved: 0", out)
        self.assertIn("stale: 1", out)
        self.import_results({"a": self.result(self.show)}, "--dry-run")
        self.show.refresh_from_db()
        self.assertEqual(self.show.trailer_clip_url, "")

    def test_rejected_trailer_clears_the_old_clip_only_when_asked(self):
        self.import_results({"a": self.result(self.movie, status="rejected")})
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.trailer_clip_url, f"{CDN}/trailers/1399.mp4")
        self.import_results({"a": self.result(self.movie, status="rejected")}, "--clear-rejected")
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.trailer_clip_url, "")
