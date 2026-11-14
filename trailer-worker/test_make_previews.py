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
