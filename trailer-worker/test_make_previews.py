"""python -m unittest test_make_previews  (no network, no ffmpeg needed)"""
import unittest

from make_previews import Rejected, check_video, is_done, name_matches


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
        self.assertTrue(is_done({"status": "rejected"}))


if __name__ == "__main__":
    unittest.main()


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
