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

    def test_a_clip_made_again_gets_a_new_name_and_still_counts_as_done(self):
        # trailer-worker's audio re-check: same trailer, new file (the CDN keeps the old one 30 days)
        self.import_results({"a": self.result(self.show)})
        redone = dict(self.result(self.show), rev="a")
        self.assertIn("saved: 1", self.import_results({"a": redone}))
        self.show.refresh_from_db()
        self.assertEqual(self.show.trailer_clip_url, f"{CDN}/previews/tv/1399-showKey0001-a.mp4")
        self.assertNotIn(("tv", 1399), [(j["type"], j["tmdb_id"]) for j in self.export()])
        # a rev that isn't a short name is ignored, never put in a path
        self.assertEqual(preview_path("tv", 1, "k", "../x"), "previews/tv/1-k.mp4")

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


class OtherVideoTests(TestCase):
    """trailer-worker/ made the clip from another video than the one asked for (TMDB's was gone,
    blocked in its country or not the title's), or found one for a title TMDB has no trailer for."""

    def setUp(self):
        self.yt = "https://www.youtube.com/watch?v="
        self.film = Title.objects.create(type="movie", tmdb_id=35019, title="Nanny McPhee and the Big Bang",
                                         trailer_url=self.yt + "goneVideo01", popularity=9, vote_count=900)
        self.bare = Title.objects.create(type="movie", tmdb_id=99, title="No TMDB trailer", popularity=5,
                                         vote_count=40)
        Title.objects.create(type="movie", tmdb_id=98, title="Unknown film", popularity=4, vote_count=3)

    def export(self, *args):
        out, err = io.StringIO(), io.StringIO()
        call_command("export_trailer_jobs", *args, stdout=out, stderr=err)
        return json.loads(out.getvalue())["jobs"]

    def import_results(self, *results):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"version": 1, "results": {str(i): r for i, r in enumerate(results)}}, f)
        out = io.StringIO()
        call_command("import_trailer_results", f.name, stdout=out)
        return out.getvalue()

    def ok(self, title, used, asked):
        return {"type": title.type, "tmdb_id": title.tmdb_id, "status": "ok", "youtube_key": used,
                "asked_key": asked, "path": preview_path(title.type, title.tmdb_id, used)}

    def test_titles_without_a_tmdb_trailer_are_searched_when_enough_people_rated_them(self):
        jobs = {j["tmdb_id"]: j for j in self.export()}
        self.assertEqual(set(jobs), {35019, 99})  # 3 votes: too little known, a search goes wrong
        self.assertTrue(jobs[99]["search"])
        self.assertEqual((jobs[99]["youtube_key"], jobs[99]["path"]), ("", ""))
        self.assertNotIn("search", jobs[35019])
        self.assertEqual({j["tmdb_id"] for j in self.export("--search-min-votes", "-1")}, {35019})

    @override_settings(BUNNY_CDN_BASE=CDN)
    def test_a_clip_from_another_video_is_saved_and_the_title_page_plays_that_video(self):
        from .serializers import TitleSerializer

        out = self.import_results(self.ok(self.film, "otherVideo1", "goneVideo01"),
                                  self.ok(self.bare, "foundVideo1", ""))
        self.assertIn("saved: 2", out)
        self.assertIn("other_video: 2", out)
        self.film.refresh_from_db()
        self.bare.refresh_from_db()
        self.assertEqual(self.film.trailer_clip_url, f"{CDN}/previews/movie/35019-otherVideo1.mp4")
        self.assertEqual((self.film.trailer_clip_for, self.bare.trailer_clip_for), ("goneVideo01", "-"))
        self.assertEqual(self.export(), [])  # both answered
        self.assertEqual(TitleSerializer(self.film).data["trailer_url"], self.yt + "otherVideo1")
        self.assertEqual(TitleSerializer(self.bare).data["trailer_url"], self.yt + "foundVideo1")
        self.assertNotIn("trailer_clip_for", TitleSerializer(self.film).data)

        # TMDB picks a new trailer: asked again, and the page plays TMDB's new one meanwhile
        Title.objects.filter(pk=self.film.pk).update(trailer_url=self.yt + "newTrailer1")
        self.film.refresh_from_db()
        self.assertEqual([j["youtube_key"] for j in self.export()], ["newTrailer1"])
        self.assertEqual(TitleSerializer(self.film).data["trailer_url"], self.yt + "newTrailer1")

    @override_settings(BUNNY_CDN_BASE=CDN)
    def test_the_trailer_asked_for_after_all(self):
        self.import_results(self.ok(self.film, "otherVideo1", "goneVideo01"))
        self.import_results(self.ok(self.film, "goneVideo01", "goneVideo01"))  # it came back
        self.film.refresh_from_db()
        self.assertEqual(self.film.trailer_clip_for, "")
        self.assertEqual(self.film.trailer_clip_url, f"{CDN}/previews/movie/35019-goneVideo01.mp4")

    @override_settings(BUNNY_CDN_BASE=CDN)
    def test_stale_or_odd_results_are_skipped(self):
        out = self.import_results(self.ok(self.film, "otherVideo1", "olderTrail1"),  # asked about an old trailer
                                  self.ok(self.bare, "../../x", ""))                   # not a YouTube key
        self.assertIn("saved: 0", out)
        self.assertIn("stale: 1", out)
        self.assertIn("skipped: 1", out)

    def test_ranked_keys_and_clip_helpers(self):
        from .trailers import clip_answers, clip_youtube_key, ranked_trailer_keys, shown_trailer_url

        full = tmdb(video("teaser00001", kind="Teaser"), video("trailer0001"), video("clip0000001", kind="Clip"))
        self.assertEqual(ranked_trailer_keys(full), ["trailer0001", "teaser00001"])
        self.assertEqual(pick_trailer_url(full), self.yt + "trailer0001")
        clip = f"{CDN}/previews/movie/5-otherVideo1-a.mp4"
        self.assertEqual(clip_youtube_key(clip), "otherVideo1")
        self.assertEqual(clip_youtube_key(f"{CDN}/trailers/5.mp4"), "")
        self.assertTrue(clip_answers(clip, "goneVideo01", "movie", 5, self.yt + "goneVideo01"))
        self.assertFalse(clip_answers(clip, "goneVideo01", "movie", 5, self.yt + "newTrailer1"))
        self.assertFalse(clip_answers(clip, "", "movie", 5, self.yt + "goneVideo01"))
        self.assertEqual(shown_trailer_url(self.yt + "goneVideo01", clip, ""), self.yt + "goneVideo01")
