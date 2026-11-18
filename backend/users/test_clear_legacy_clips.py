"""manage.py clear_legacy_clips: the old trailers/{tmdb_id}.mp4 clips of a TMDB id a movie and a show
share are removed (one file for both: Breaking Bad played another title's preview); the other old
clips stay unless --all, the new ones always."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .models import Title

CDN = "https://cdn.example.com"


class ClearLegacyClipsTests(TestCase):
    def setUp(self):
        yt = "https://www.youtube.com/watch?v=AAAAAAAAAAA"
        self.show = Title.objects.create(type="tv", tmdb_id=1396, title="Breaking Bad", trailer_url=yt,
                                         trailer_clip_url=f"{CDN}/trailers/1396.mp4")
        self.movie = Title.objects.create(type="movie", tmdb_id=1396, title="Other", trailer_url=yt,
                                          trailer_clip_url=f"{CDN}/trailers/1396.mp4")
        self.alone = Title.objects.create(type="movie", tmdb_id=603, title="The Matrix", trailer_url=yt,
                                          trailer_clip_url=f"{CDN}/trailers/603.mp4")
        self.new = Title.objects.create(type="movie", tmdb_id=27205, title="Inception", trailer_url=yt,
                                        trailer_clip_url=f"{CDN}/previews/movie/27205-AAAAAAAAAAA.mp4")

    def run_cmd(self, *args):
        out = StringIO()
        call_command("clear_legacy_clips", *args, stdout=out)
        return out.getvalue()

    def clips(self):
        return {t.title: t.trailer_clip_url for t in Title.objects.all()}

    def test_dry_run_changes_nothing(self):
        before = self.clips()
        out = self.run_cmd("--dry-run")
        self.assertIn("Old-format clips: 3, 2 of them", out)
        self.assertIn("shared id 1396: tv 'Breaking Bad'", out)
        self.assertIn("would clear 2", out)
        self.assertEqual(self.clips(), before)

    def test_shared_ids_only_by_default(self):
        self.assertIn("Cleared 2 clip(s)", self.run_cmd())
        clips = self.clips()
        self.assertEqual((clips["Breaking Bad"], clips["Other"]), ("", ""))
        self.assertTrue(clips["The Matrix"].endswith("/trailers/603.mp4"))

    def test_all_old_clips_cleared_new_ones_kept(self):
        self.assertIn("Cleared 3 clip(s)", self.run_cmd("--all"))
        clips = self.clips()
        self.assertEqual([clips["Breaking Bad"], clips["Other"], clips["The Matrix"]], ["", "", ""])
        self.assertTrue(clips["Inception"].endswith("/previews/movie/27205-AAAAAAAAAAA.mp4"))
        # still listed for trailer-worker/: they have a trailer, not its clip
        out = StringIO()
        call_command("export_trailer_jobs", stdout=out, stderr=StringIO())
        self.assertEqual(out.getvalue().count('"tmdb_id": 1396'), 2)
