"""python -m unittest test_make_previews  (no network, no ffmpeg needed)"""
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from make_previews import (Blocked, Rejected, check_video, is_done, name_matches, progress, recheck_search, run,
                           search_problem)


class NameMatchTests(unittest.TestCase):
    def test_the_titles_own_trailer(self):
        self.assertTrue(name_matches("The Matrix (1999) Official Trailer - Keanu Reeves", "The Matrix"))
        self.assertTrue(name_matches("SPIDERMAN: NO WAY HOME - Official Trailer", "Spider-Man: No Way Home"))
        self.assertTrue(name_matches("Amélie - Bande annonce", "Amelie"))
        self.assertTrue(name_matches("Harry Potter and the Sorcerers Stone trailer",
                                     "Harry Potter and the Sorcerer's Stone"))
        self.assertTrue(name_matches("千と千尋の神隠し 予告編", "Spirited Away", "千と千尋の神隠し"))
        self.assertTrue(name_matches("Star Wars: A New Hope - Trailer", "Star Wars: Episode IV - A New Hope"))
        self.assertTrue(name_matches("Fast & Furious 6 Trailer", "Fast and Furious 6"))

    def test_another_video(self):
        self.assertFalse(name_matches("Breaking Bad - Season 5 Recap", "Better Call Saul"))
        self.assertFalse(name_matches("The Matrix Resurrections Trailer", "Inception"))
        self.assertFalse(name_matches("Top 10 movies of 2020", "Up"))
        self.assertFalse(name_matches("Superman Trailer", "Batman"))

    def test_a_name_that_contains_the_titles(self):
        # a spin-off / a plural: the title's last word changed, it's another show or film
        self.assertFalse(name_matches("American Horror Stories Season 1 Trailer | Rotten Tomatoes TV",
                                      "American Horror Story"))
        self.assertFalse(name_matches("Aliens (1986) Trailer", "Alien"))
        self.assertTrue(name_matches("American Horror Story: Season 2 Trailer", "American Horror Story"))
        # a letter off inside the name is still the title
        self.assertTrue(name_matches("Pirates of the Carribean Curse of the Black Pearl trailer",
                                     "Pirates of the Caribbean: Curse of the Black Pearl"))

    def test_a_films_sequel(self):
        movie = {"type": "movie", "title": "Toy Story"}
        with self.assertRaises(Rejected):
            check_video({"title": "Toy Story 4 Official Trailer", "duration": 140}, movie)
        for title, video in [("Dune", "Dune: Part Two - Official Trailer 3"),
                             ("John Wick", "John Wick: Chapter 2 trailer"),
                             ("Rocky", "ROCKY II (1979) Trailer")]:
            with self.assertRaises(Rejected, msg=video):
                check_video({"title": video, "duration": 140}, {"type": "movie", "title": title})
        check_video({"title": "Toy Story (1995) Trailer #1", "duration": 140}, movie)
        check_video({"title": "Toy Story - Official Trailer 2", "duration": 140}, movie)
        check_video({"title": "Fast & Furious 6 Trailer", "duration": 140},
                    {"type": "movie", "title": "Fast & Furious 6"})
        # a show's season trailer is the show's
        check_video({"title": "Stranger Things 4 | Official Trailer", "duration": 140},
                    {"type": "tv", "title": "Stranger Things"})

    def test_not_a_trailer(self):
        job = {"title": "The Matrix"}
        with self.assertRaises(Rejected):
            check_video({"title": "The Matrix full movie", "duration": 8100}, job)
        with self.assertRaises(Rejected):
            check_video({"title": "The Matrix", "duration": 9}, job)
        check_video({"title": "The Matrix Trailer", "duration": 140}, job)

    def test_errors_are_retried_a_few_times(self):
        self.assertFalse(is_done(None))
        self.assertFalse(is_done({"status": "error", "attempts": 1}))
        self.assertTrue(is_done({"status": "error", "attempts": 3}))
        self.assertTrue(is_done({"status": "ok"}))

    def test_no_video_is_tried_again_later(self):
        import time as _t
        now = _t.strftime("%Y-%m-%dT%H:%M:%S")
        old = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.localtime(_t.time() - 90 * 86400))
        self.assertTrue(is_done({"status": "rejected", "v": 2, "at": now}))
        self.assertTrue(is_done({"status": "unavailable", "v": 2, "at": now}))
        self.assertFalse(is_done({"status": "rejected", "v": 2, "at": old}))  # RECHECK_DAYS later
        # before v2 only the video asked for was looked at: once more with the others
        self.assertFalse(is_done({"status": "rejected", "at": now}))
        self.assertFalse(is_done({"status": "unavailable", "at": now}))




class DubbedAudioTests(unittest.TestCase):
    def test_original_plus_dubs(self):
        from make_previews import has_dubbed_audio
        info = {"formats": [
            {"acodec": "opus", "language": "en-US", "format_note": "English (US) original (default), low"},
            {"acodec": "opus", "language": "id", "format_note": "Indonesian, low"},
            {"acodec": "none", "vcodec": "avc1", "format_note": "480p"},
        ]}
        self.assertTrue(has_dubbed_audio(info))

    def test_one_track(self):
        from make_previews import has_dubbed_audio
        self.assertFalse(has_dubbed_audio({"formats": [
            {"acodec": "opus", "language": "en", "format_note": "medium"},
            {"acodec": "mp4a", "language": "en-US", "format_note": "low"},
            {"acodec": "none", "format_note": "1080p"},
        ]}))
        self.assertFalse(has_dubbed_audio({}))

    def test_a_clip_made_again_gets_a_new_name(self):
        from make_previews import next_rev, redo_path
        self.assertEqual([next_rev(""), next_rev("a"), next_rev("b")], ["a", "b", "c"])
        entry = {"type": "tv", "tmdb_id": 1402, "youtube_key": "cu2ApTImB-a"}  # a key may end like a rev
        self.assertEqual(redo_path(entry, "a"), "previews/tv/1402-cu2ApTImB-a-a.mp4")


class BlockedTests(unittest.TestCase):
    """YouTube refusing the machine stops the run (it waits and tries again), it isn't a title's error."""

    def _fails_with(self, stderr):
        done = subprocess.CompletedProcess([], 1, stdout="", stderr=stderr)
        with mock.patch("make_previews.subprocess.run", return_value=done):
            run(["yt-dlp"])

    def test_youtube_refusing_the_machine(self):
        for err in ("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies",
                    "ERROR: [youtube] x: Please sign in. This helps protect our community.",
                    "ERROR: [youtube] x: The following content is not available on this app. "
                    "You might want to use a VPN or a proxy server (with --proxy) to workaround.",
                    "ERROR: unable to download video data: HTTP Error 429: Too Many Requests"):
            with self.assertRaises(Blocked, msg=err):
                self._fails_with(err)

    def test_a_titles_own_problem(self):
        with self.assertRaises(RuntimeError) as cm:
            self._fails_with("ERROR: ffmpeg exited with code 8")
        self.assertNotIsInstance(cm.exception, Blocked)


class MoreNameTests(unittest.TestCase):
    def test_numbers_in_words_or_figures(self):
        self.assertTrue(name_matches("OCEAN'S 8 - Official Main Trailer", "Ocean's Eight"))
        self.assertTrue(name_matches("Ocean's Eleven - Trailer", "Oceans 11"))
        self.assertFalse(name_matches("Ocean's Twelve - Trailer", "Ocean's Eleven"))

    def test_another_year_is_another_film(self):
        from make_previews import other_year
        self.assertTrue(other_year("Ocean's 11 (1960) trailer", 2001))
        self.assertFalse(other_year("Ocean's Eleven (2001) Official Trailer", 2001))
        self.assertFalse(other_year("Dune Official Trailer", 2021))           # no year: fine
        self.assertFalse(other_year("Jaws (1975) - 2022 re-release trailer", 1975))
        self.assertFalse(other_year("Avatar Trailer 2009", 2010))             # a year off: fine
        with self.assertRaises(Rejected):
            check_video({"title": "Ocean's 11 (1960) trailer", "duration": 140},
                        {"type": "movie", "title": "Ocean's Eleven", "year": 2001})
        # a show's later season names a later year
        check_video({"title": "Stranger Things 4 (2022) Trailer", "duration": 140},
                    {"type": "tv", "title": "Stranger Things", "year": 2016})


class CountryBlockTests(unittest.TestCase):
    def _fails_with(self, stderr):
        done = subprocess.CompletedProcess([], 1, stdout="", stderr=stderr)
        with mock.patch("make_previews.subprocess.run", return_value=done):
            run(["yt-dlp"])

    def test_a_video_blocked_in_this_country_is_unavailable_not_youtube_refusing(self):
        from make_previews import Unavailable
        err = ("ERROR: [youtube] uDcQbk78CSw: The uploader has not made this video available in your country\n"
               "This video is available in United States.\n"
               "You might want to use a VPN or a proxy server (with --proxy) to workaround.")
        with self.assertRaises(Unavailable):
            self._fails_with(err)
        with self.assertRaises(Unavailable):
            self._fails_with("ERROR: [youtube] x: This video is unavailable")


class OtherNamesTests(unittest.TestCase):
    def test_alternative_titles_and_translations(self):
        from make_previews import other_names
        details = {
            "alternative_titles": {"titles": [{"title": "Nanny McPhee Returns"},
                                              {"title": "Nanny McPhee and the Big Bang"}]},
            "translations": {"translations": [
                {"iso_639_1": "fr", "data": {"title": "Nanny McPhee et le Big Bang"}},
                {"iso_639_1": "ja", "data": {"title": "Nanny McPhee Japan"}},  # not a language kept
            ]},
        }
        names = other_names(details, {"title": "Nanny McPhee and the Big Bang"})
        self.assertEqual(names, ["Nanny McPhee Returns", "Nanny McPhee et le Big Bang"])
        self.assertEqual(other_names({"alternative_titles": {"results": [{"title": "Skam Espana"}]}},
                                     {"title": "Skam"}), ["Skam Espana"])  # shows: "results"
        self.assertEqual(other_names({}, {"title": "x"}), [])


def _info(name, duration=120):
    return json.dumps({"title": name, "duration": duration})


class ChooseVideoTests(unittest.TestCase):
    """clip_for_job: the video asked for, else TMDB's other trailers, else a YouTube search."""

    def setUp(self):
        import shutil
        import tempfile
        self.workdir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.workdir, ignore_errors=True))
        self.job = {"type": "movie", "tmdb_id": 35019, "title": "Nanny McPhee and the Big Bang",
                    "original_title": "", "year": 2010, "youtube_key": "AAAAAAAAAAA"}
        made = mock.patch("make_previews.make_clip", side_effect=lambda job, wd, info=None, check=True:
                          (wd / "preview.mp4", {"video_title": info["title"], "bytes": 900_000}))
        made.start()
        self.addCleanup(made.stop)

    def _youtube(self, videos, search=()):
        """run() as yt-dlp: videos {key: name or an exception}, search: [(key, name)]."""
        def fake(cmd, timeout=300):
            target = cmd[-1]
            if target.startswith("ytsearch"):
                return json.dumps({"entries": [{"id": k, "title": n, "duration": 120} for k, n in search]})
            v = videos[target.rsplit("=", 1)[-1]]
            if isinstance(v, Exception):
                raise v
            return _info(v)
        return mock.patch("make_previews.run", side_effect=fake)

    def test_the_video_asked_for(self):
        from make_previews import clip_for_job
        with self._youtube({"AAAAAAAAAAA": "Nanny McPhee and the Big Bang - Trailer"}), \
                mock.patch("make_previews.tmdb_details") as tmdb:
            _, _, used, source = clip_for_job(self.job, self.workdir)
        self.assertEqual((used, source), ("AAAAAAAAAAA", "asked"))
        tmdb.assert_not_called()  # no TMDB request when the first video fits

    def test_gone_then_tmdbs_next_trailer(self):
        from make_previews import Unavailable, clip_for_job
        details = {"videos": {"results": [
            {"site": "YouTube", "key": "AAAAAAAAAAA", "type": "Trailer", "official": True},
            {"site": "YouTube", "key": "BBBBBBBBBBB", "type": "Trailer"},
        ]}}
        with self._youtube({"AAAAAAAAAAA": Unavailable("Video unavailable"),
                            "BBBBBBBBBBB": "Nanny McPhee and the Big Bang Official Trailer"}), \
                mock.patch("make_previews.tmdb_details", return_value=details):
            _, _, used, source = clip_for_job(self.job, self.workdir)
        self.assertEqual((used, source), ("BBBBBBBBBBB", "tmdb"))

    def test_another_name_of_the_title(self):
        from make_previews import clip_for_job
        details = {"alternative_titles": {"titles": [{"title": "Nanny McPhee Returns"}]}}
        with self._youtube({"AAAAAAAAAAA": "Nanny McPhee Returns - Trailer"}), \
                mock.patch("make_previews.tmdb_details", return_value=details):
            _, _, used, source = clip_for_job(self.job, self.workdir)
        self.assertEqual((used, source), ("AAAAAAAAAAA", "asked"))

    def test_no_tmdb_trailer_a_youtube_search(self):
        from make_previews import clip_for_job
        job = {**self.job, "youtube_key": "", "search": True}
        search = [("CCCCCCCCCCC", "Nanny McPhee and the Big Bang (2010) full movie"),   # not a trailer
                  ("DDDDDDDDDDD", "Paddington Trailer"),                                # another film
                  ("EEEEEEEEEEE", "Nanny McPhee and the Big Bang - Official Trailer")]
        with self._youtube({"EEEEEEEEEEE": "Nanny McPhee and the Big Bang - Official Trailer"}, search), \
                mock.patch("make_previews.tmdb_details", return_value={}):
            _, _, used, source = clip_for_job(job, self.workdir)
        self.assertEqual((used, source), ("EEEEEEEEEEE", "search"))

    def test_nothing_fits(self):
        from make_previews import NoVideo, Unavailable, clip_for_job
        with self._youtube({"AAAAAAAAAAA": "Paddington Trailer"}, [("FFFFFFFFFFF", "Paddington 2 Trailer")]), \
                mock.patch("make_previews.tmdb_details", return_value={}):
            with self.assertRaises(NoVideo) as cm:
                clip_for_job(self.job, self.workdir)
        self.assertEqual(cm.exception.status, "rejected")
        with self._youtube({"AAAAAAAAAAA": Unavailable("Private video")}), \
                mock.patch("make_previews.tmdb_details", return_value={}):
            with self.assertRaises(NoVideo) as cm:
                clip_for_job(self.job, self.workdir)
        self.assertEqual(cm.exception.status, "unavailable")

    def test_youtube_refusing_stops_everything(self):
        from make_previews import clip_for_job
        with self._youtube({"AAAAAAAAAAA": Blocked("Sign in to confirm you're not a bot")}), \
                mock.patch("make_previews.tmdb_details") as tmdb:
            with self.assertRaises(Blocked):
                clip_for_job(self.job, self.workdir)
        tmdb.assert_not_called()

    def test_no_video_file_for_any_video_is_not_the_titles_error(self):
        from make_previews import NoFormats, clip_for_job
        details = {"videos": {"results": [{"site": "YouTube", "key": "BBBBBBBBBBB", "type": "Trailer"}]}}
        with self._youtube({"AAAAAAAAAAA": NoFormats("no file"), "BBBBBBBBBBB": NoFormats("no file")}), \
                mock.patch("make_previews.tmdb_details", return_value=details), \
                mock.patch("make_previews.search_keys", return_value=[]):
            with self.assertRaises(NoFormats):
                clip_for_job(self.job, self.workdir)
        with self._youtube({"AAAAAAAAAAA": NoFormats("no file"), "BBBBBBBBBBB": RuntimeError("ffmpeg 8")}), \
                mock.patch("make_previews.tmdb_details", return_value=details), \
                mock.patch("make_previews.search_keys", return_value=[]):
            with self.assertRaises(RuntimeError) as cm:
                clip_for_job(self.job, self.workdir)
        self.assertNotIsInstance(cm.exception, NoFormats)  # a real error too: counted as before

    def test_the_server_ranking_is_used(self):
        from make_previews import SERVER_TRAILERS, tmdb_trailer_keys
        self.assertIsNotNone(SERVER_TRAILERS)  # backend/users/trailers.py next door
        details = {"original_language": "en", "videos": {"results": [
            {"site": "YouTube", "key": "AAAAAAAAAAA", "type": "Teaser"},
            {"site": "YouTube", "key": "BBBBBBBBBBB", "type": "Trailer", "official": True},
            {"site": "YouTube", "key": "CCCCCCCCCCC", "type": "Featurette"},
        ]}}
        self.assertEqual(tmdb_trailer_keys(details, {}), ["BBBBBBBBBBB", "AAAAAAAAAAA"])


if __name__ == "__main__":
    unittest.main()


class NoVideoFileTests(unittest.TestCase):
    """2026-11-27: YouTube's "SABR-only" experiment on the account sent no video file for hours
    ("Requested format is not available"); without the account the same videos worked."""
    NO_FILE = "ERROR: [youtube] x: Requested format is not available. Use --list-formats for a list"

    def _yt_dlp(self, *answers):
        done = [subprocess.CompletedProcess([], code, stdout="out" if code == 0 else "", stderr=err)
                for code, err in answers]
        return mock.patch("make_previews.subprocess.run", side_effect=done)

    def test_tried_again_without_the_account(self):
        with self._yt_dlp((1, self.NO_FILE), (0, "")) as sp:
            self.assertEqual(run(["yt-dlp", "--cookies", "c.txt", "-J", "URL"]), "out")
        self.assertEqual(sp.call_args_list[1].args[0], ["yt-dlp", "-J", "URL"])
        with self._yt_dlp((1, self.NO_FILE), (0, "")) as sp:
            run(["yt-dlp", "--cookies-from-browser", "firefox:/p", "URL"])
        self.assertEqual(sp.call_args_list[1].args[0], ["yt-dlp", "URL"])

    def test_nothing_either_way_is_not_the_titles_error(self):
        from make_previews import NoFormats
        with self._yt_dlp((1, self.NO_FILE), (1, self.NO_FILE)):
            with self.assertRaises(NoFormats):
                run(["yt-dlp", "--cookies", "c.txt", "URL"])
        with self._yt_dlp((1, "ERROR: ffmpeg exited with code 8")) as sp:  # not tried again
            with self.assertRaises(RuntimeError) as cm:
                run(["yt-dlp", "--cookies", "c.txt", "URL"])
        self.assertNotIsInstance(cm.exception, NoFormats)
        self.assertEqual(sp.call_count, 1)

    def _run_jobs(self, n, clip_for_job):
        import sys
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        jobs = tmp / "jobs.json"
        jobs.write_text(json.dumps({"jobs": [{"type": "movie", "tmdb_id": i, "youtube_key": f"k{i:010d}",
                                              "path": f"p{i}", "title": f"T{i}"} for i in range(n)]}))
        results = tmp / "results.json"
        results.write_text(json.dumps({"version": 1, "results": {
            "movie:0:k0000000000": {"status": "error", "attempts": 2}}}))
        import make_previews as mp
        with mock.patch.object(sys, "argv", ["make_previews.py", str(jobs), "--results", str(results)]), \
                mock.patch.multiple(mp, BUNNY_API_KEY="k", BUNNY_STORAGE_ZONE="z", NO_FORMATS_STOP=3,
                                    lock=mock.DEFAULT, bunny_upload=mock.DEFAULT, clip_for_job=clip_for_job), \
                mock.patch("make_previews.shutil.which", return_value="ffmpeg"), \
                mock.patch("make_previews.time.sleep"), mock.patch("make_previews.signal.signal"):
            code = mp.main()
        return code, json.loads(results.read_text())["results"]

    def test_no_attempt_used_up_and_a_long_streak_stops_the_run(self):
        from make_previews import EXIT_BLOCKED, NoFormats
        code, results = self._run_jobs(5, mock.Mock(side_effect=NoFormats("no file")))
        self.assertEqual(code, EXIT_BLOCKED)  # run.sh waits, refreshes the cookies, tries again
        self.assertEqual(len(results), 3)  # stopped after 3 in a row
        self.assertEqual(results["movie:0:k0000000000"]["attempts"], 2)  # untouched
        self.assertEqual(results["movie:1:k0000000001"]["attempts"], 0)

    def test_a_title_that_works_ends_the_streak(self):
        from make_previews import NoFormats
        answers = [NoFormats("x"), NoFormats("x"), (Path("c.mp4"), {"bytes": 2048}, "k", "asked"),
                   NoFormats("x"), NoFormats("x")]
        code, results = self._run_jobs(5, mock.Mock(side_effect=answers))
        self.assertEqual(code, 0)
        self.assertEqual(len(results), 5)


class ProgressTests(unittest.TestCase):
    def test_counts_this_run_and_what_is_left(self):
        jobs = [{"type": "movie", "tmdb_id": n, "youtube_key": f"k{n:010d}"} for n in range(5)]
        key = lambda n: f"movie:{n}:k{n:010d}"  # noqa: E731
        results = {
            key(0): {"status": "ok", "at": "2026-11-23T03:00:00"},  # last night's
            key(1): {"status": "ok", "at": "2026-11-24T02:00:00"},
            key(2): {"status": "rejected", "v": 2, "at": "2026-11-24T02:10:00"},
            key(3): {"status": "error", "attempts": 1, "at": "2026-11-24T02:20:00"},
        }
        with mock.patch("make_previews.time.time", return_value=1795600000):  # 2026-11-24, rejected is recent
            line = progress(jobs, results, "2026-11-24T01:00:02")
        self.assertEqual(line, "1 clips made since 01:00, 1 without a usable video, 1 errors; 2 titles left")


class SearchVideoTests(unittest.TestCase):
    """A YouTube search's video: stricter rules (wrong clips seen on 2026-11-24)."""

    def problem(self, kind, name, year, video):
        if not name_matches(video, name, fuzzy=False):
            return "name"
        return search_problem(video, {"type": kind, "title": name, "year": year}, [name])

    def test_wrong_videos_are_turned_down(self):
        for kind, name, year, video in [
            ("tv", "NOVA", 1974, "1974 Chevrolet Nova Spirit of America Walk-Around and Drive for Bring a Trailer"),
            ("tv", "How It's Made", 2001, "How It`s Made   Semi trailers"),
            ("tv", "Snapped", 2004, "Snapped (2021) - Official Trailer - Stallion Pictures"),
            ("tv", "Yowamushi Pedal", 2013, "Yowamushi Pedal The Movie - Official Theatrical Trailer"),
            ("tv", "Monster High", 2022, '"Welcome to Monster High" Official Movie Trailer | Monster High'),
            ("tv", "The Demon Hunter", 2025, "The Demon Hunter Season 1 Trailer In Hindi Dubbed"),
            ("tv", "Escape to the Country", 2002, "TRAILER Escape In The Country"),
            ("movie", "Up", 2009, "Up Close and Personal Trailer"),  # another film
            ("tv", "Spider-Man", 1994, "Spider Man: The Venom Saga DVD trailer"),
        ]:
            self.assertTrue(self.problem(kind, name, year, video), video)

    def test_right_videos_are_kept(self):
        for kind, name, year, video in [
            ("tv", "ALF", 1986, "ALF (1986) Official Trailer"),
            ("tv", "Newhart", 1982, "CBS Newhart/Kate & Allie promo 1988"),  # a later season's promo
            ("tv", "Trailer Park Boys", 2001, "Trailer Park Boys Season 1 Trailer"),
            ("tv", "Clarence", 2014, "Cartoon Network Clarence Trailer"),
            ("tv", "Gotham", 2014, "Gotham Trailer"),  # just the name: fine
            ("tv", "TaleSpin", 1990, "TaleSpin - VHS Trailer"),
            ("tv", "Attack on Titan", 2013, "Attack on Titan English Dubbed Trailer"),
            ("tv", "Quantum Leap", 1989, "Quantum Leap (1989) season 1 BLURAY Trailer #1 - Scott Bakula"),
            ("movie", "Logan", 2017, "Logan Official Trailer 1 (2017) - Hugh Jackman Movie"),
        ]:
            self.assertIsNone(self.problem(kind, name, year, video), video)

    def test_recheck_withdraws_only_wrong_search_clips(self):
        def entry(title, video, source="search", status="ok"):
            return {"type": "tv", "tmdb_id": 1, "title": title, "status": status, "source": source,
                    "video_title": video, "path": f"previews/tv/1-{title[:4]}.mp4"}
        results = {
            "tv:1:": entry("NOVA", "1974 Chevrolet Nova Walk-Around for Bring a Trailer"),
            "tv:2:": entry("ALF", "ALF (1986) Official Trailer"),
            "tv:3:": entry("How It's Made", "How It's Made Semi trailers", source="asked"),  # TMDB's own: kept
        }
        jobs = [{"type": "tv", "tmdb_id": 1, "youtube_key": "", "title": "NOVA", "year": 1974},
                {"type": "tv", "tmdb_id": 2, "youtube_key": "", "title": "ALF", "year": 1986}]
        self.assertEqual([t for t, _ in recheck_search(results, jobs)], ["NOVA"])
        nova = results["tv:1:"]
        self.assertEqual((nova["status"], nova["withdrawn"]), ("withdrawn", "previews/tv/1-NOVA.mp4"))
        self.assertFalse(is_done(nova))  # looked for again
        self.assertEqual(results["tv:2:"]["status"], "ok")
        self.assertEqual(recheck_search(results, jobs), [])  # once
