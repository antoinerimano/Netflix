"""Internationalization: language codes, translated messages / emails, catalog texts in the API."""
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .i18n import to_app_language, to_django_language
from .localize import localize_payload
from .models import Episode, EpisodeTranslation, Profile, Season, Title, TitleTranslation, User


class LanguageCodeTests(TestCase):
    def test_codes(self):
        self.assertEqual(to_app_language("fr-CA"), "fr")
        self.assertEqual(to_app_language("jp"), "ja")
        self.assertEqual(to_app_language("zh-Hans"), "zh")
        self.assertEqual(to_app_language("ZH_tw"), "zh")
        self.assertIsNone(to_app_language("pt"))
        self.assertEqual(to_app_language("", "en"), "en")
        self.assertEqual(to_django_language("zh"), "zh-hans")
        self.assertEqual(to_django_language("xx"), "en")


class CatalogTextsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("sam@example.com", "Sam", "pw-sam-123!")
        self.client.force_authenticate(self.user)
        self.show = Title.objects.create(type="tv", title="The Office", description="A mockumentary.", tmdb_id=2316)
        self.season = Season.objects.create(tv=self.show, season_number=1)
        self.ep = Episode.objects.create(season=self.season, episode_number=1, name="Pilot", overview="Michael...")
        TitleTranslation.objects.create(title=self.show, language="fr", name="The Office (FR)", overview="Un faux documentaire.")
        EpisodeTranslation.objects.create(episode=self.ep, language="fr", name="Le pilote", overview="")

    def test_payload_walker(self):
        data = {
            "rows": [{"title": "Row title", "items": [{"id": self.show.id, "title": "The Office", "type": "tv", "description": "A mockumentary."}]}],
            "episodes": [{"id": self.ep.id, "episode_number": 1, "name": "Pilot", "overview": "Michael..."}],
            "notifications": [{"title_id": self.show.id, "show": "The Office"}],
        }
        out = localize_payload(data, "fr")
        item = out["rows"][0]["items"][0]
        self.assertEqual(item["title"], "The Office (FR)")
        self.assertEqual(item["description"], "Un faux documentaire.")
        self.assertEqual(out["rows"][0]["title"], "Row title")  # not a title object: untouched
        self.assertEqual(out["episodes"][0]["name"], "Le pilote")
        self.assertEqual(out["episodes"][0]["overview"], "Michael...")  # empty translation: English kept
        self.assertEqual(out["notifications"][0]["show"], "The Office (FR)")

    def test_api_serves_the_request_language(self):
        fr = self.client.get(f"/api/titles/{self.show.id}/", HTTP_ACCEPT_LANGUAGE="fr-FR,fr;q=0.9").json()
        self.assertEqual(fr["title"], "The Office (FR)")
        self.assertEqual(fr["description"], "Un faux documentaire.")
        self.assertEqual(fr["seasons"][0]["episodes"][0]["name"], "Le pilote")

        en = self.client.get(f"/api/titles/{self.show.id}/", HTTP_ACCEPT_LANGUAGE="en").json()
        self.assertEqual(en["title"], "The Office")

        es = self.client.get(f"/api/titles/{self.show.id}/", HTTP_ACCEPT_LANGUAGE="es").json()
        self.assertEqual(es["title"], "The Office")  # no Spanish row: English

    def test_editing_tools_get_the_stored_texts(self):
        res = self.client.get(
            f"/api/titles/{self.show.id}/", HTTP_ACCEPT_LANGUAGE="fr", HTTP_X_ORIGINAL_CONTENT="1"
        ).json()
        self.assertEqual(res["title"], "The Office")

    def test_response_varies_on_language(self):
        res = self.client.get(f"/api/titles/{self.show.id}/", HTTP_ACCEPT_LANGUAGE="fr")
        self.assertEqual(res["Content-Language"], "fr")
        self.assertIn("Accept-Language", res["Vary"])


class MessagesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("sam@example.com", "Sam", "pw-sam-123!")

    def test_register_errors_are_translated_with_a_stable_code(self):
        res = self.client.post(
            "/api/users/register/",
            {"name": "Sam", "email": "sam@example.com", "password": "pw-other-123!"},
            format="json", HTTP_ACCEPT_LANGUAGE="fr",
        )
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["code"], "email_taken")
        self.assertEqual(res.json()["error"], "Cette adresse e-mail est déjà enregistrée.")

    def test_password_rules_in_the_request_language(self):
        res = self.client.post(
            "/api/users/register/",
            {"name": "Kim", "email": "kim@example.com", "password": "123"},
            format="json", HTTP_ACCEPT_LANGUAGE="de",
        )
        self.assertEqual(res.json()["code"], "password_invalid")
        self.assertIn("Passwort", res.json()["error"])

    def test_reset_email_in_the_request_language(self):
        self.client.post("/api/password-reset/", {"email": "sam@example.com"}, format="json", HTTP_ACCEPT_LANGUAGE="es")
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.subject, "Restablece tu contraseña")
        self.assertIn("Hola, Sam:", msg.body)
        html = msg.alternatives[0][0]
        self.assertIn('lang="es"', html)
        self.assertIn("Restablecer contraseña", html)

    def test_profile_language_is_normalized(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            f"/api/users/{self.user.id}/profiles/",
            {"name": "Aki", "language_preference": "jp", "age_restriction": "NC-17"},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Profile.objects.get(name="Aki").language_preference, "ja")


class SearchTests(TransactionTestCase):
    """Search answers in the request's language and finds titles by their translated name.
    TransactionTestCase: InnoDB FULLTEXT only sees committed rows."""

    FULLTEXT = {
        "users_title": [("title_name_ft", "title, original_title"), ("title_director_ft", "director")],
        "users_actor": [("actor_name_ft", "name")],
    }

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # a test database built without migrations has no FULLTEXT index (users/0017)
        with connection.cursor() as cur:
            for table, indexes in cls.FULLTEXT.items():
                existing = {i for i in connection.introspection.get_constraints(cur, table)}
                for name, cols in indexes:
                    if name not in existing:
                        cur.execute(f"ALTER TABLE {table} ADD FULLTEXT INDEX {name} ({cols})")

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.user = User.objects.create_user("sam@example.com", "Sam", "pw-sam-123!")
        self.client.force_authenticate(self.user)
        self.movie = Title.objects.create(type="movie", title="The Godfather", original_title="The Godfather", popularity=90)
        TitleTranslation.objects.create(title=self.movie, language="fr", name="Le Parrain", overview="")

    def test_translated_name_and_reason_shape(self):
        res = self.client.get("/api/titles/search/", {"q": "Le Parrain"}, HTTP_ACCEPT_LANGUAGE="fr")
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body[0]["id"], self.movie.id)
        self.assertEqual(body[0]["title"], "Le Parrain")
        self.assertIn("match_key", body[0])

    def test_typo_fallback_runs(self):
        # few name matches: the typo-tolerant pass runs over the scores (regression: crashed)
        res = self.client.get("/api/titles/search/", {"q": "godfathr"}, HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(res.status_code, 200, res.content)
