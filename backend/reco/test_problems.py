"""'Playback problem?' + the status page (reco/problems.py, ROADMAP 9.8)."""
import io
import json
from datetime import timedelta

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import Episode, Profile, Provider, Season, Title, User
from users.provider_import import import_catalog
from .models import PlaybackOutcome, PlaybackReport
from .problems import open_reports, source_state


class ProblemTestCase(TestCase):
    def setUp(self):
        cache.clear()
        Provider.objects.all().delete()  # migration 0012 seeds the original ones
        self.vidfast = Provider.objects.create(key="vidfast", label="VidFast", domain="https://vidfast.pro",
                                               movie_path="/movie/{tmdb_id}", episode_path="/tv/{tmdb_id}/{season}/{episode}",
                                               status=Provider.UP, checked_at=timezone.now(), priority=10,
                                               scout_check="2026-11-25 04:10 live 9/11 anime 0/3 - plays 9/11 titles",
                                               scout_score=0.82)
        self.cinesrc = Provider.objects.create(key="cinesrc", label="CineSrc", domain="https://cinesrc.st",
                                               movie_path="/embed/movie/{tmdb_id}", status=Provider.DOWN, priority=20)
        self.movie = Title.objects.create(type="movie", title="Interstellar", tmdb_id=157336, imdb_code="tt0816692",
                                          runtime_minutes=169)
        self.show = Title.objects.create(type="tv", title="Dark", tmdb_id=70523)
        s1 = Season.objects.create(tv=self.show, season_number=1)
        Episode.objects.create(season=s1, episode_number=2, runtime=44)
        self.user = User.objects.create_user("p@example.com", "P", "pw-p-12345!")
        self.profile = Profile.objects.create(user=self.user, name="P", age_restriction="NC-17", language_preference="en")
        self.client = APIClient()

    def report(self, **data):
        body = {"provider": "vidfast", "title_id": self.movie.id, "problem": "no_sound", **data}
        return self.client.post("/api/playback/report/", body, format="json")


class ReportTests(ProblemTestCase):
    def test_a_signed_in_report_is_saved_with_the_source_and_episode(self):
        self.client.force_authenticate(self.user)
        res = self.report(title_id=self.show.id, season=1, episode=2, problem="out_of_sync", profile_id=str(self.profile.id))
        self.assertEqual(res.status_code, 201)
        r = PlaybackReport.objects.get()
        self.assertEqual((r.provider_key, r.title_id, r.season_number, r.episode_number, r.problem, r.profile_id),
                         ("vidfast", self.show.id, 1, 2, "out_of_sync", self.profile.id))
        # the same thing again soon: kept once
        again = self.report(title_id=self.show.id, season=1, episode=2, problem="out_of_sync", profile_id=str(self.profile.id))
        self.assertTrue(again.data.get("again"))
        self.assertEqual(PlaybackReport.objects.count(), 1)
        self.assertFalse(PlaybackOutcome.objects.exists())  # sound / sync: the source did play

    def test_doesnt_play_or_wrong_film_count_as_a_failed_play(self):
        self.client.force_authenticate(self.user)
        self.report(problem="wrong_title", profile_id=str(self.profile.id))
        outcome = PlaybackOutcome.objects.get()
        self.assertEqual((outcome.provider_key, outcome.worked, outcome.title_id), ("vidfast", False, self.movie.id))

    def test_signed_out_works_and_a_movie_has_no_episode(self):
        res = self.report(season=3, episode=4)
        self.assertEqual(res.status_code, 201)
        r = PlaybackReport.objects.get()
        self.assertIsNone(r.profile_id)
        self.assertIsNone(r.season_number)

    def test_bad_reports_are_refused(self):
        self.assertEqual(self.report(problem="ads").status_code, 400)
        self.assertEqual(self.report(provider="nope").status_code, 400)
        self.assertEqual(self.report(title_id=999999).status_code, 404)
        other = User.objects.create_user("o@example.com", "O", "pw-o-12345!")
        self.client.force_authenticate(other)
        self.assertEqual(self.report(profile_id=str(self.profile.id)).status_code, 404)  # not their profile
        self.assertFalse(PlaybackReport.objects.exists())


class ScoutTests(ProblemTestCase):
    def test_export_hands_the_open_reports_to_the_scout_reported_sources_first(self):
        PlaybackReport.objects.create(title=self.movie, provider_key="cinesrc", problem="not_playing")
        for _ in range(2):
            PlaybackReport.objects.create(title=self.show, season_number=1, episode_number=2,
                                          provider_key="vidfast", problem="wrong_title")
        old = PlaybackReport.objects.create(title=self.movie, provider_key="vidfast", problem="no_sound")
        PlaybackReport.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=8))
        PlaybackReport.objects.create(title=self.movie, provider_key="vidfast", problem="no_sound",
                                      checked_at=timezone.now())  # already re-checked

        out = io.StringIO()
        call_command("export_providers", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["reports"][0], {
            "provider": "vidfast", "type": "tv", "tmdb": 70523, "imdb": "", "name": "Dark 1x02",
            "season": 1, "episode": 2, "minutes": 44, "problems": {"wrong_title": 2}, "count": 2})
        self.assertEqual([(r["provider"], r["tmdb"]) for r in data["reports"]], [("vidfast", 70523), ("cinesrc", 157336)])
        self.assertEqual(data["reports"][1]["minutes"], 169)
        self.vidfast.delete()
        self.assertEqual([r["provider"] for r in open_reports()], ["cinesrc"])  # a removed source can't be checked

    def test_the_scouts_answer_goes_on_the_reports(self):
        open_ep = PlaybackReport.objects.create(title=self.show, season_number=1, episode_number=2,
                                                provider_key="vidfast", problem="wrong_title")
        other_ep = PlaybackReport.objects.create(title=self.show, season_number=1, episode_number=3,
                                                 provider_key="vidfast", problem="wrong_title")
        movie = PlaybackReport.objects.create(title=self.movie, provider_key="vidfast", problem="not_playing")
        health = {"state": "live", "verified": "9/11", "films": [{"state": "live"}],
                  "reports": [{"type": "tv", "tmdb": 70523, "season": 1, "episode": 2, "state": "up",
                               "detail": "only a 1.5 min video"},
                              {"type": "movie", "tmdb": 157336, "state": "live", "detail": "plays (169 min)"}]}
        lines, stats = import_catalog({"generated": "2026-11-26 04:10:00", "probe_title": {},
                                       "providers": [{"provider": "vidfast", "health": health}]})
        self.assertEqual(stats["reports_checked"], 2)
        open_ep.refresh_from_db(), other_ep.refresh_from_db(), movie.refresh_from_db()
        self.assertEqual(open_ep.check_result, "didn't play in the scout's test (up): only a 1.5 min video")
        self.assertEqual(movie.check_result, "played in the scout's test: plays (169 min)")
        self.assertIsNone(other_ep.checked_at)  # not that episode
        self.assertIn("vidfast: re-checked 2 reported title(s), 1 played (2 report(s) answered)", lines)


class StatusTests(ProblemTestCase):
    def test_the_public_status_page(self):
        for i in range(6):
            PlaybackOutcome.objects.create(profile=self.profile, title=self.movie, provider_key="vidfast", worked=i < 5)
        PlaybackReport.objects.create(title=self.movie, provider_key="vidfast", problem="no_sound")
        res = APIClient().get("/api/status/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["ok"])
        first, second = res.data["sources"]
        self.assertEqual((first["key"], first["state"], second["key"], second["state"]),
                         ("vidfast", "up", "cinesrc", "down"))  # working ones first
        self.assertEqual(first["scout"], {"date": "2026-11-25", "played": 9, "tested": 11})
        self.assertEqual((first["plays_24h"], first["played_share_24h"], first["reports_24h"]), (6, 0.83, 1))
        self.assertIsNone(second["scout"])
        self.assertEqual(res.data["counts"], {"up": 1, "problems": 0, "unknown": 0, "down": 1})
        self.assertIn("max-age=60", res["Cache-Control"])

    def test_source_states(self):
        self.assertEqual(source_state("up", 0, 0, 0, None), "up")
        self.assertEqual(source_state("up", 0, 0, 3, None), "problems")  # 3 reports in 24 h
        self.assertEqual(source_state("up", 10, 4, 0, None), "problems")  # most plays failed
        self.assertEqual(source_state("up", 4, 0, 0, None), "up")  # too few plays to say
        self.assertEqual(source_state("up", 0, 0, 0, 0.3), "problems")  # the scout's test
        self.assertEqual(source_state("unknown", 0, 0, 0, None), "unknown")
        self.assertEqual(source_state("down", 10, 10, 0, 1.0), "down")

    def test_the_dashboard_shows_the_reports(self):
        PlaybackReport.objects.create(title=self.show, season_number=1, episode_number=2,
                                      provider_key="vidfast", problem="no_subtitles")
        staff = User.objects.create_user("s@example.com", "S", "pw-s-12345!", is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        from django.conf import settings
        res = self.client.get("/" + settings.ADMINADMIN_URL.strip("/") + "/dashboard/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn("Playback problems reported", html)
        self.assertIn("No subtitles 1", html)
        self.assertIn("Dark <span class=\"quiet\">S1 E2</span>", html)
