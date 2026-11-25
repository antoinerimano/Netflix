"""
Tests for provider_health.py's "Block pop-ups" check (ROADMAP 9.1), no browser needed:
    cd provider_scraper && python -m unittest test_provider_health -v
"""
import asyncio
import unittest

import provider_health as ph

TITLES = [{"name": "Heat", "tmdb": 949}, {"name": "Inception", "tmdb": 27205}, {"name": "Casablanca", "tmdb": 289}]
SITE = "https://tauruss.example"


def films(*states):
    return [{"title": t["name"], "state": s} for t, s in zip(TITLES, states)]


def fake_play(answers):
    """play() stand-in: answers by title name; remembers what it was asked."""
    calls = []

    async def play(ctx, template, title, site, retry, sandbox=False):
        calls.append((title["name"], sandbox))
        return {"title": title["name"], **answers[title["name"]]}
    return play, calls


def check(film_results, answers, site=SITE):
    play, calls = fake_play(answers)
    r = asyncio.run(ph.sandbox_check(None, "https://p.example/movie/{tmdb}", film_results, TITLES, site, play_fn=play))
    return r, calls


class SitePageTests(unittest.TestCase):
    def test_sandboxed_like_the_watch_page(self):
        html = ph.site_page(SITE + "/__provider_scout", "https://p.example/movie/1?a=1&b=2", sandbox=True)
        self.assertIn('sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"', html)
        self.assertNotIn("allow-popups", html)
        self.assertNotIn("allow-top-navigation", html)
        self.assertIn('allow="autoplay; fullscreen *; picture-in-picture; encrypted-media"', html)
        self.assertIn("allowfullscreen", html)
        self.assertIn("a=1&amp;b=2", html)

    def test_not_sandboxed_by_default(self):
        self.assertNotIn("sandbox=", ph.site_page(SITE, "https://p.example/movie/1"))


class SandboxCheckTests(unittest.TestCase):
    def test_plays_sandboxed(self):
        r, calls = check(films("live", "live"), {"Heat": {"state": "live", "blocked": 3}})
        self.assertEqual(r["sandbox"], "yes")
        self.assertIn("3 pop-up", r["sandbox_detail"])
        self.assertEqual(calls, [("Heat", True)])  # one title that plays is enough

    def test_refuses_the_sandbox(self):
        r, calls = check(films("live", "live", "live"), {
            "Heat": {"state": "unverified", "detail": "page loads, the player asks for nothing"},
            "Inception": {"state": "no_source", "detail": "sandbox not allowed"},
        })
        self.assertEqual(r["sandbox"], "no")
        self.assertEqual([c[0] for c in calls], ["Heat", "Inception"])  # SANDBOX_TRIES titles, no more

    def test_one_of_two_plays(self):
        r, _ = check(films("live", "live"), {"Heat": {"state": "up", "detail": "slow"}, "Inception": {"state": "live"}})
        self.assertEqual(r["sandbox"], "yes")

    def test_only_titles_that_played_are_tried(self):
        r, calls = check(films("no_source", "live"), {"Inception": {"state": "live"}})
        self.assertEqual(calls, [("Inception", True)])
        self.assertEqual(r["sandbox"], "yes")

    def test_no_verdict(self):
        r, calls = check(films("no_source", "down"), {})
        self.assertEqual((r["sandbox"], calls), ("unknown", []))
        r, _ = check(films("live"), {"Heat": {"state": "protected", "detail": "Cloudflare"}})
        self.assertEqual(r["sandbox"], "unknown")
        r, calls = check(films("live"), {}, site=None)  # --direct: no iframe
        self.assertEqual((r["sandbox"], calls), ("unknown", []))


if __name__ == "__main__":
    unittest.main()
