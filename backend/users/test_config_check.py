"""users/config_check.py: missing settings, debug mode in production, keys a service refuses
(no network: TMDB, Anthropic and SMTP are mocked)."""
import smtplib
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from users import config_check

FULL_ENV = {name: "x" for name, _why in config_check.REQUIRED} | {"SITE_DOMAIN": "tauruss.top"}
PROD = {"SITE_URL": "https://tauruss.top", "DEBUG": False}


def kinds(problems):
    return sorted(p["kind"] for p in problems)


@override_settings(**PROD)
class PresenceTests(SimpleTestCase):
    def test_all_set_nothing_to_say(self):
        with mock.patch.dict("os.environ", FULL_ENV):
            self.assertEqual(config_check.presence_problems(), [])

    def test_a_missing_setting_says_what_stops_working_and_where_to_set_it(self):
        env = dict(FULL_ENV, TMDB_API_KEY="", SITE_DOMAIN="")
        with mock.patch.dict("os.environ", env):
            problems = config_check.presence_problems()
        self.assertEqual([p["what"] for p in problems],
                         ["Setting TMDB_API_KEY is missing", "Setting SITE_DOMAIN is missing"])
        self.assertIn("catalog syncs", problems[0]["detail"])
        self.assertIn("/opt/taurus/backend/.env", problems[0]["fix"])
        self.assertIn("/opt/taurus/.env", problems[1]["fix"])  # the compose one

    @override_settings(DEBUG=True)
    def test_debug_mode_in_production(self):
        with mock.patch.dict("os.environ", FULL_ENV):
            self.assertEqual(kinds(config_check.presence_problems()), ["config_debug"])

    @override_settings(DEBUG=True, SITE_URL="http://localhost:3000")
    def test_debug_mode_on_a_local_run_is_fine(self):
        with mock.patch.dict("os.environ", FULL_ENV):
            self.assertEqual(config_check.presence_problems(), [])

    @override_settings(SITE_URL="https://old-name.com")
    def test_site_url_on_another_domain(self):
        with mock.patch.dict("os.environ", FULL_ENV):
            self.assertEqual(kinds(config_check.presence_problems()), ["config_domain"])

    @override_settings(SITE_URL="https://www.tauruss.top")
    def test_www_is_the_same_domain(self):
        with mock.patch.dict("os.environ", FULL_ENV):
            self.assertEqual(config_check.presence_problems(), [])


class LiveTests(SimpleTestCase):
    def test_tmdb_refused_key(self):
        with mock.patch("users.config_check.requests.get", return_value=mock.Mock(status_code=401, text="Invalid API key")):
            p = config_check.check_tmdb("bad")
        self.assertEqual(p["what"], "TMDB refuses TMDB_API_KEY")
        self.assertIn("TMDB_API_KEY", p["fix"])

    def test_tmdb_down_is_not_a_key_problem(self):
        with mock.patch("users.config_check.requests.get", side_effect=requests.ConnectionError("down")):
            self.assertIsNone(config_check.check_tmdb("k"))
        with mock.patch("users.config_check.requests.get", return_value=mock.Mock(status_code=503, text="")):
            self.assertIsNone(config_check.check_tmdb("k"))

    def test_anthropic_refused_key_and_outage(self):
        # stand-in error classes: the SDK's need an HTTP response object to be built
        class APIError(Exception):
            pass

        class AuthenticationError(APIError):
            pass

        class PermissionDeniedError(APIError):
            pass

        class APIConnectionError(APIError):
            pass

        errors = {"APIError": APIError, "AuthenticationError": AuthenticationError,
                  "PermissionDeniedError": PermissionDeniedError}
        with mock.patch.multiple("anthropic", **errors), mock.patch("anthropic.Anthropic") as client:
            client.return_value.models.retrieve.side_effect = AuthenticationError("invalid x-api-key")
            self.assertEqual(config_check.check_anthropic("bad")["what"], "Anthropic refuses ANTHROPIC_API_KEY")
            client.return_value.models.retrieve.side_effect = PermissionDeniedError("forbidden")
            self.assertEqual(config_check.check_anthropic("bad")["kind"], "config_refused")
            client.return_value.models.retrieve.side_effect = APIConnectionError("no network")
            self.assertIsNone(config_check.check_anthropic("k"))
            client.return_value.models.retrieve.side_effect = None
            self.assertIsNone(config_check.check_anthropic("k"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend", EMAIL_HOST="smtp.example.com",
                       EMAIL_PORT=587, EMAIL_USE_TLS=True, EMAIL_HOST_USER="u", EMAIL_HOST_PASSWORD="p")
    def test_smtp_refused_password_and_unreachable_server(self):
        with mock.patch("users.config_check.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad")
            self.assertEqual(config_check.check_smtp()["kind"], "config_refused")
            smtp.side_effect = OSError("no route")
            self.assertIsNone(config_check.check_smtp())

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_no_smtp_check_without_smtp(self):
        with mock.patch("users.config_check.smtplib.SMTP") as smtp:
            self.assertIsNone(config_check.check_smtp())
        smtp.assert_not_called()

    @override_settings(SITE_URL="http://localhost:3000")
    def test_no_live_calls_outside_production(self):
        with mock.patch("users.config_check.live_problems") as live, mock.patch.dict("os.environ", FULL_ENV):
            config_check.config_problems()
        live.assert_not_called()
