"""TMDB errors never carry the API key (users/tmdb_http.py): job logs, JobRun summaries and
check-up emails print them."""
from unittest import mock

import requests
from django.test import SimpleTestCase

from users.management.commands.sync_tmdb_monthly import TMDbClient
from users.tmdb_http import get_json, redact

KEY = "0123456789abcdef0123456789abcdef"


def response(status, reason="Not Found", body=None):
    r = requests.Response()
    r.status_code = status
    r.reason = reason
    r.url = f"https://api.themoviedb.org/3/movie/1?api_key={KEY}&language=en"
    r._content = b'{"ok": true}' if body is None else body
    return r


class RedactTests(SimpleTestCase):
    def test_key_replaced_wherever_it_is(self):
        text = f"404 for url: https://x/3/movie/1?api_key={KEY}&language=en and ?a=1&api_key={KEY}"
        out = redact(text)
        self.assertNotIn(KEY, out)
        self.assertEqual(out.count("api_key=***"), 2)
        self.assertIn("&language=en", out)

    def test_text_without_key_unchanged(self):
        self.assertEqual(redact("HTTP 500"), "HTTP 500")


class GetJsonTests(SimpleTestCase):
    def session(self, **kw):
        s = mock.Mock()
        s.get = mock.Mock(**kw)
        return s

    def test_ok_returns_json(self):
        s = self.session(return_value=response(200, "OK"))
        self.assertEqual(get_json(s, "https://x/3/movie/1", {"api_key": KEY}, 5, "/movie/1"), {"ok": True})

    def test_http_error_names_path_and_status_not_key(self):
        s = self.session(return_value=response(404))
        with self.assertRaises(requests.HTTPError) as cm:
            get_json(s, "https://x/3/movie/1", {"api_key": KEY}, 5, "/movie/1")
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("404", str(cm.exception))
        self.assertIn("/movie/1", str(cm.exception))
        self.assertEqual(cm.exception.response.status_code, 404)  # callers can still read it

    def test_connection_error_hides_key(self):
        err = requests.ConnectionError(
            f"HTTPSConnectionPool(host='api.themoviedb.org', port=443): Max retries exceeded with url: "
            f"/3/movie/1?api_key={KEY} (Caused by NameResolutionError)")
        s = self.session(side_effect=err)
        with self.assertRaises(requests.RequestException) as cm:
            get_json(s, "https://x/3/movie/1", {"api_key": KEY}, 5, "/movie/1")
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIn("ConnectionError", str(cm.exception))

    def test_tmdb_client_uses_it(self):
        client = TMDbClient(api_key=KEY)
        client.s = self.session(return_value=response(404))
        with self.assertRaises(requests.HTTPError) as cm:
            client.get("/movie/1506134/release_dates")
        self.assertNotIn(KEY, str(cm.exception))
