import io
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from users.models import JobRun, Provider
from users.provider_import import import_catalog, paths_for, to_template

PROBE = {"tmdb": 1368337, "imdb": "tt33764258"}


def entry(name, state="live", test_url=None, observed=(), formats=(), sites=2, hosts=(), episode=None,
          dead=False, episode_dead=False):
    """A catalog provider as provider_health.py leaves it: "live" = played every test film."""
    health = {"state": state, "test_url": test_url, "current_tried": True} if state else {}
    if state in ("live", "partial"):
        ok = 5 if state == "live" else 2
        health.update(films=[{"state": "live"}] * ok + [{"state": "up"}] * (5 - ok), verified=f"{ok}/5",
                      detail="plays all 5 test films" if ok == 5 else "does not play Inception (wrong video)")
        if test_url:
            health["movie_template"] = test_url.replace(str(PROBE["tmdb"]), "{tmdb}")
        if episode:
            health["episode_template"] = episode
            health["episode"] = {"state": "live"}
        health["current_dead"], health["current_episode_dead"] = dead, episode_dead
    return {
        "provider": name, "site_count": sites, "sites": [f"s{i}.com" for i in range(sites)],
        "hosts": list(hosts), "observed_templates": list(observed), "doc_formats": list(formats),
        "health": health,
    }


def catalog(*entries):
    return {"generated": "2026-11-19 03:10:00", "probe_title": PROBE, "providers": list(entries)}


class TemplateTests(TestCase):
    def test_placeholders_are_ours_and_plain_query_params_go(self):
        self.assertEqual(to_template("https://vidfast.vc/movie/{id}?autoPlay=true"),
                         ("https://vidfast.vc", "/movie/{tmdb_id}"))
        self.assertEqual(to_template("https://player.cinezo.live/embed/tv/{tmdbId}/{season}/{episode}"),
                         ("https://player.cinezo.live", "/embed/tv/{tmdb_id}/{season}/{episode}"))
        self.assertEqual(to_template("https://primesrc.me/embed/movie?tmdb={tmdb_id}&autoplay=1"),
                         ("https://primesrc.me", "/embed/movie?tmdb={tmdb_id}"))

    def test_the_probe_titles_ids_become_placeholders(self):
        self.assertEqual(to_template("https://vixsrc.to/movie/1368337", PROBE), ("https://vixsrc.to", "/movie/{tmdb_id}"))
        self.assertEqual(to_template("https://x.to/e/tt33764258", PROBE), ("https://x.to", "/e/{imdb_id}"))

    def test_unusable_urls(self):
        self.assertIsNone(to_template("https://vidlink.pro/movie/786892", PROBE))  # a docs example, not our id
        self.assertIsNone(to_template("https://api.2embed.cc/movie?imdb_id={tt�}"))
        self.assertIsNone(to_template("https://vaplayer.ru/"))
        self.assertIsNone(to_template("/movie/{id}"))

    def test_paths_are_the_formats_that_played(self):
        e = entry("xpass", test_url="https://play.xpass.top/e/movie/1368337",
                  episode="https://play.xpass.top/e/tv/{tmdb}/{season}/{episode}")
        self.assertEqual(paths_for(e, PROBE),
                         ("https://play.xpass.top", "/e/movie/{tmdb_id}", "/e/tv/{tmdb_id}/{season}/{episode}"))

    def test_no_tv_link_when_no_episode_played(self):
        e = entry("xpass", test_url="https://play.xpass.top/e/movie/1368337",
                  formats=["https://play.xpass.top/e/tv/{tmdb_id}/{season}/{episode}"])
        self.assertEqual(paths_for(e, PROBE), ("https://play.xpass.top", "/e/movie/{tmdb_id}", ""))


class ImportTests(TestCase):
    def setUp(self):
        Provider.objects.all().delete()  # migration 0012 seeds the original ones
        self.vidfast = Provider.objects.create(key="vidfast", label="VidFast", domain="https://vidfast.pro",
                                               movie_path="/movie/{tmdb_id}?autoPlay=true", priority=20)

    def test_new_provider_on_two_sites_is_enabled_after_the_known_ones(self):
        lines, stats = import_catalog(catalog(
            entry("cinesrc", test_url="https://cinesrc.st/embed/movie/1368337", sites=3,
                  episode="https://cinesrc.st/embed/tv/{tmdb}/{season}/{episode}")))
        p = Provider.objects.get(key="cinesrc")
        self.assertTrue(p.enabled)
        self.assertEqual((p.domain, p.movie_path, p.episode_path),
                         ("https://cinesrc.st", "/embed/movie/{tmdb_id}", "/embed/tv/{tmdb_id}/{season}/{episode}"))
        self.assertEqual(p.status, Provider.UP)
        self.assertGreater(p.priority, self.vidfast.priority)
        self.assertEqual(stats["created_enabled"], 1)

    def test_new_provider_on_one_site_waits_disabled(self):
        import_catalog(catalog(entry("vidly", test_url="https://vidly.pro/movie/1368337", sites=1)))
        self.assertFalse(Provider.objects.get(key="vidly").enabled)

    def test_new_provider_not_playing_or_without_link_is_skipped(self):
        _, stats = import_catalog(catalog(
            entry("ployan", state="no_source", test_url="https://ployan.me/movie/1368337"),
            entry("vidapi", state="up", test_url="https://vaplayer.ru/"),
            entry("odd", test_url="https://odd.to/"),
            entry("cdn:workers", test_url="https://x.workers.dev/movie/1368337"),
        ))
        self.assertEqual(Provider.objects.count(), 1)
        self.assertEqual((stats["skipped_not_live"], stats["skipped_no_link"]), (2, 1))

    def test_a_dead_link_gets_the_domain_the_films_play_on(self):
        lines, stats = import_catalog(catalog(entry("vidfast", test_url="https://vidfast.vc/movie/1368337?autoPlay=true",
                                                    dead=True)))
        self.vidfast.refresh_from_db()
        self.assertEqual(self.vidfast.domain, "https://vidfast.vc")
        self.assertIn("https://vidfast.pro", self.vidfast.backups())  # the old one kept as a fallback
        self.assertEqual(self.vidfast.status, Provider.UP)
        self.assertEqual(self.vidfast.movie_path, "/movie/{tmdb_id}")
        self.assertEqual(stats["switched"], 1)

    def test_a_link_that_answers_is_never_replaced(self):
        # another link plays too, but its own wasn't dead (slow, a bot check, a missing title...)
        _, stats = import_catalog(catalog(entry("vidfast", test_url="https://vidfast.vc/embed/1368337")))
        self.vidfast.refresh_from_db()
        self.assertEqual((self.vidfast.domain, self.vidfast.movie_path), ("https://vidfast.pro", "/movie/{tmdb_id}?autoPlay=true"))
        self.assertEqual((stats["known_ok"], stats["fixed_link"]), (1, 0))
        self.assertIn("live 5/5", self.vidfast.scout_check)

    def test_a_dead_link_structure_gets_the_one_that_plays(self):
        Provider.objects.create(key="vidsrc", label="Vidsrc", domain="https://vidsrc.mov",
                                movie_path="/embed/movie/{imdb_id}", episode_path="/embed/tv/{tmdb_id}/{season}-{episode}")
        import_catalog(catalog(entry("vidsrc", test_url="https://vidsrc.mov/movie/1368337", dead=True,
                                     episode="https://vidsrc.mov/tv/{tmdb}/{season}/{episode}", episode_dead=True)))
        p = Provider.objects.get(key="vidsrc")
        self.assertEqual((p.domain, p.movie_path, p.episode_path),
                         ("https://vidsrc.mov", "/movie/{tmdb_id}", "/tv/{tmdb_id}/{season}/{episode}"))

    def test_a_tv_link_that_answers_is_kept(self):
        self.vidfast.episode_path = "/tv/{tmdb_id}/{season}/{episode}"
        self.vidfast.save()
        e = entry("vidfast", test_url="https://vidfast.pro/movie/1368337")
        e["health"]["episode"] = {"state": "up", "detail": "page loads, nothing plays"}
        import_catalog(catalog(e))
        self.vidfast.refresh_from_db()
        self.assertEqual(self.vidfast.episode_path, "/tv/{tmdb_id}/{season}/{episode}")

    def test_a_player_that_reports_playback_gets_sends_events(self):
        e = entry("vidfast", test_url="https://vidfast.pro/movie/1368337")
        e["health"]["sends_events"] = True
        lines, _ = import_catalog(catalog(e))
        self.vidfast.refresh_from_db()
        self.assertTrue(self.vidfast.sends_events)
        self.assertIn("sends_events on", lines[0])

    def test_plays_with_pop_ups_blocked_comes_from_the_scout(self):
        # Block pop-ups (9.1): the scout's sandboxed check sets sandbox_ok, also on a source that isn't live
        self.assertEqual(self.vidfast.sandbox_ok, Provider.UNKNOWN)
        e = entry("vidfast", test_url="https://vidfast.pro/movie/1368337")
        e["health"].update(sandbox="no", sandbox_detail="plays, but not sandboxed")
        lines, _ = import_catalog(catalog(e))
        self.vidfast.refresh_from_db()
        self.assertEqual(self.vidfast.sandbox_ok, Provider.SANDBOX_NO)
        self.assertIn("pop-ups blocked: unknown -> no", lines[0])
        e = entry("vidfast", state="partial", test_url="https://vidfast.pro/movie/1368337")
        e["health"]["sandbox"] = "yes"
        import_catalog(catalog(e))
        self.vidfast.refresh_from_db()
        self.assertEqual(self.vidfast.sandbox_ok, Provider.SANDBOX_YES)

    def test_no_sandbox_verdict_keeps_what_is_known(self):
        self.vidfast.sandbox_ok = Provider.SANDBOX_NO
        self.vidfast.save()
        for verdict in ("unknown", None):
            e = entry("vidfast", test_url="https://vidfast.pro/movie/1368337")
            if verdict:
                e["health"]["sandbox"] = verdict
            import_catalog(catalog(e))
            self.vidfast.refresh_from_db()
            self.assertEqual(self.vidfast.sandbox_ok, Provider.SANDBOX_NO)

    def test_a_new_provider_gets_the_sandbox_verdict(self):
        e = entry("cinesrc", test_url="https://cinesrc.st/embed/movie/1368337", sites=3)
        e["health"]["sandbox"] = "yes"
        import_catalog(catalog(e, entry("vidly", test_url="https://vidly.pro/movie/1368337", sites=3)))
        self.assertEqual(Provider.objects.get(key="cinesrc").sandbox_ok, Provider.SANDBOX_YES)
        self.assertEqual(Provider.objects.get(key="vidly").sandbox_ok, Provider.UNKNOWN)

    def test_found_by_host(self):
        import_catalog(catalog(entry("vid-fast", test_url="https://vidfast.net/embed/1368337", hosts=["www.vidfast.pro"],
                                     dead=True)))
        self.vidfast.refresh_from_db()
        self.assertEqual((self.vidfast.domain, self.vidfast.movie_path), ("https://vidfast.net", "/embed/{tmdb_id}"))
        self.assertFalse(Provider.objects.filter(key="vid-fast").exists())

    def test_priority_kept_and_a_second_run_changes_nothing(self):
        cat = catalog(entry("cinesrc", test_url="https://cinesrc.st/embed/movie/1368337", sites=3))
        import_catalog(cat)
        Provider.objects.filter(key="cinesrc").update(priority=5)
        _, stats = import_catalog(cat)
        p = Provider.objects.get(key="cinesrc")
        self.assertEqual((p.enabled, p.priority), (True, 5))
        self.assertEqual((stats["created"], stats["known_ok"]), (0, 1))

    def test_playing_one_film_is_not_enough_for_a_new_one(self):
        old = catalog(entry("vidly", test_url="https://vidly.pro/movie/1368337"))
        old["providers"][0]["health"] = {"state": "live", "test_url": "https://vidly.pro/movie/1368337"}
        _, stats = import_catalog(old)  # the old one-title check
        self.assertEqual(stats["skipped_not_live"], 1)
        _, stats = import_catalog(catalog(entry("vidly", state="partial", test_url="https://vidly.pro/movie/1368337")))
        self.assertEqual(stats["skipped_not_live"], 1)
        self.assertFalse(Provider.objects.filter(key="vidly").exists())

    def test_never_turned_off_nor_on(self):
        for state in ("partial", "up", "no_source", "down", "protected", "unverified"):
            import_catalog(catalog(entry("vidfast", state=state, test_url="https://vidfast.pro/movie/1368337")))
            self.vidfast.refresh_from_db()
            self.assertTrue(self.vidfast.enabled, state)
        Provider.objects.filter(key="vidfast").update(enabled=False)  # turned off by hand
        import_catalog(catalog(entry("vidfast", test_url="https://vidfast.pro/movie/1368337")))
        self.assertFalse(Provider.objects.get(key="vidfast").enabled)

    def test_not_in_tonights_catalog_changes_nothing(self):
        import_catalog(catalog(entry("other", state="partial", test_url="https://other.to/movie/1368337")))
        self.vidfast.refresh_from_db()
        self.assertTrue(self.vidfast.enabled)

    def test_dry_run_changes_nothing(self):
        self.vidfast.status = Provider.DOWN
        self.vidfast.save()
        import_catalog(catalog(entry("vidfast", test_url="https://vidfast.vc/movie/1368337"),
                               entry("vidly", test_url="https://vidly.pro/movie/1368337")), dry_run=True)
        self.vidfast.refresh_from_db()
        self.assertEqual((self.vidfast.domain, Provider.objects.count()), ("https://vidfast.pro", 1))


class CommandTests(TestCase):
    def setUp(self):
        Provider.objects.all().delete()

    def run_cmd(self, data, *args):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
        out = io.StringIO()
        call_command("import_providers", f.name, *args, stdout=out)
        return out.getvalue()

    def test_imports_and_is_recorded_for_the_dashboard(self):
        out = self.run_cmd(catalog(entry("vidly", test_url="https://vidly.pro/movie/1368337", sites=2)))
        self.assertIn("1 new (1 enabled)", out)
        self.assertTrue(Provider.objects.get(key="vidly").enabled)
        self.assertTrue(JobRun.objects.get(name="import_providers").ok)

    def test_export_gives_the_scout_the_site_its_providers_and_test_titles(self):
        from users.models import Episode, Season, Title
        Provider.objects.create(key="vidfast", label="VidFast", domain="https://vidfast.vc", backup_domains="https://vidfast.pro",
                                movie_path="/movie/{tmdb_id}", episode_path="/tv/{tmdb_id}/{season}/{episode}", enabled=False)
        Title.objects.create(type=Title.MOVIE, title="Fight Club", tmdb_id=550, imdb_code="tt0137523",
                             runtime_minutes=139, release_year=1999, popularity=50)
        Title.objects.create(type=Title.MOVIE, title="Short", tmdb_id=1, runtime_minutes=20, release_year=1999, popularity=99)
        show = Title.objects.create(type=Title.TV, title="Breaking Bad", tmdb_id=1396, imdb_code="tt0903747", popularity=40)
        Episode.objects.create(season=Season.objects.create(tv=show, season_number=1), episode_number=1, runtime=58)
        out = io.StringIO()
        call_command("export_providers", stdout=out)
        data = json.loads(out.getvalue())
        self.assertTrue(data["site_origin"].startswith("http"))
        self.assertEqual(data["providers"], [{
            "key": "vidfast", "domain": "https://vidfast.vc", "backups": ["https://vidfast.pro"],
            "movie_path": "/movie/{tmdb_id}", "episode_path": "/tv/{tmdb_id}/{season}/{episode}",
            "enabled": False, "sends_events": False}])
        # the classics first, then the catalog's (no short film)
        self.assertEqual([m["name"] for m in data["test_titles"]["movies"]],
                         ["The Godfather", "Pulp Fiction", "Casablanca", "Fight Club"])
        self.assertEqual(data["test_titles"]["movies"][-1], {"tmdb": 550, "imdb": "tt0137523", "name": "Fight Club", "minutes": 139})
        self.assertEqual(data["test_titles"]["episodes"][-1], {"tmdb": 1396, "imdb": "tt0903747", "season": 1, "episode": 1,
                                                               "name": "Breaking Bad 1x01", "minutes": 58})
        self.assertEqual(data["test_titles"]["episodes"][0]["name"], "Friends 1x01")

    def test_not_a_catalog(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_cmd({"results": {}})
