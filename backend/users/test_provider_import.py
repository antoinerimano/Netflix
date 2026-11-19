import io
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from users.models import JobRun, Provider
from users.provider_import import import_catalog, paths_for, to_template

PROBE = {"tmdb": 1368337, "imdb": "tt33764258"}


def entry(name, state="live", test_url=None, observed=(), formats=(), sites=2, hosts=()):
    return {
        "provider": name, "site_count": sites, "sites": [f"s{i}.com" for i in range(sites)],
        "hosts": list(hosts), "observed_templates": list(observed), "doc_formats": list(formats),
        "health": {"state": state, "test_url": test_url} if state else {},
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

    def test_paths_from_what_played_then_templates(self):
        e = entry("xpass", test_url="https://play.xpass.top/e/movie/1368337",
                  formats=["https://play.xpass.top/e/tv/{tmdb_id}/{season}/{episode}"])
        self.assertEqual(paths_for(e, PROBE),
                         ("https://play.xpass.top", "/e/movie/{tmdb_id}", "/e/tv/{tmdb_id}/{season}/{episode}"))


class ImportTests(TestCase):
    def setUp(self):
        Provider.objects.all().delete()  # migration 0012 seeds the original ones
        self.vidfast = Provider.objects.create(key="vidfast", label="VidFast", domain="https://vidfast.pro",
                                               movie_path="/movie/{tmdb_id}?autoPlay=true", priority=20)

    def test_new_provider_on_two_sites_is_enabled_after_the_known_ones(self):
        lines, stats = import_catalog(catalog(
            entry("cinesrc", test_url="https://cinesrc.st/embed/movie/1368337", sites=3,
                  formats=["https://cinesrc.st/embed/tv/{id}/{season}/{episode}"])))
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

    def test_known_provider_down_moves_to_the_domain_it_plays_on(self):
        self.vidfast.status = Provider.DOWN
        self.vidfast.save()
        import_catalog(catalog(entry("vidfast", test_url="https://vidfast.vc/movie/1368337?autoPlay=true")))
        self.vidfast.refresh_from_db()
        self.assertEqual(self.vidfast.domain, "https://vidfast.vc")
        self.assertIn("https://vidfast.pro", self.vidfast.backups())  # the old one kept as a fallback
        self.assertEqual(self.vidfast.status, Provider.UP)
        self.assertEqual(self.vidfast.movie_path, "/movie/{tmdb_id}?autoPlay=true")  # admin's path kept

    def test_known_provider_up_only_gets_a_backup(self):
        self.vidfast.status = Provider.UP
        self.vidfast.save()
        import_catalog(catalog(entry("vidfast", test_url="https://vidfast.vc/movie/1368337")))
        self.vidfast.refresh_from_db()
        self.assertEqual(self.vidfast.domain, "https://vidfast.pro")
        self.assertEqual(self.vidfast.backups(), ["https://vidfast.vc"])

    def test_known_provider_found_by_host_and_other_link_format_is_left_alone(self):
        self.vidfast.status = Provider.DOWN
        self.vidfast.save()
        lines, _ = import_catalog(catalog(
            entry("vid-fast", test_url="https://vidfast.net/embed/1368337", hosts=["www.vidfast.pro"])))
        self.vidfast.refresh_from_db()
        self.assertEqual((self.vidfast.domain, self.vidfast.backup_domains), ("https://vidfast.pro", ""))
        self.assertFalse(Provider.objects.filter(key="vid-fast").exists())
        self.assertIn("another link format", lines[0])

    def test_admin_choices_win_and_a_second_run_changes_nothing(self):
        cat = catalog(entry("cinesrc", test_url="https://cinesrc.st/embed/movie/1368337", sites=3))
        import_catalog(cat)
        Provider.objects.filter(key="cinesrc").update(enabled=False, priority=5)
        _, stats = import_catalog(cat)
        p = Provider.objects.get(key="cinesrc")
        self.assertEqual((p.enabled, p.priority), (False, 5))
        self.assertEqual((stats["created"], stats["known_ok"]), (0, 1))

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

    def test_not_a_catalog(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_cmd({"results": {}})
