"""'Ask Taurus' (reco/ask.py, roadmap 8.10): the search tool (age limit, seen titles, moods, kind,
length), the loop (only titles the search returned, a few searches at most, cost recorded,
failures), the endpoint (caps, errors, someone else's profile). Fake Claude clients only."""
import json
from types import SimpleNamespace as NS
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from users.models import Profile, Title, User

from . import ask
from .models import AiUsage, TitleTags, WatchEvent

USAGE = NS(input_tokens=3000, output_tokens=300)


def search_call(**filters):
    args = {"query": None, "like_title": None, "kind": "any", "moods": [], "genres": [], "max_minutes": None,
            "year_from": None, "year_to": None, **filters}
    return NS(stop_reason="tool_use", usage=USAGE,
              content=[NS(type="tool_use", id="toolu_1", name="find_titles", input=args)])


def final(title_ids, reply="Voilà.", chips=("Plus court", "Plus léger", "Une série")):
    text = json.dumps({"reply": reply, "title_ids": list(title_ids), "chips": list(chips)})
    return NS(stop_reason="end_turn", usage=USAGE, content=[NS(type="text", text=text)])


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("a@example.com", "A", "pw-a-123456!")
        self.adult = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="fr")
        self.kid = Profile.objects.create(user=self.user, name="K", age_restriction="G", is_kids=True, language_preference="en")

        def title(name, kind="movie", minutes=95, maturity=2, moods="", genre="Comedy"):
            t = Title.objects.create(type=kind, title=name, genre=genre, runtime_minutes=minutes if kind == "movie" else None,
                                     vote_count=900, vote_average=7.2, poster="p.jpg", maturity=maturity,
                                     popularity=50, release_date="2010-01-01", release_year=2010)
            if moods:
                TitleTags.objects.create(title=t, moods=moods)
            return t

        self.funny = title("Funny Film", moods=",funny,")
        self.long_funny = title("Long Funny Film", minutes=170, moods=",funny,")
        self.scary = title("Scary Film", moods=",scary,", genre="Horror", maturity=3)
        self.show = title("Funny Show", kind="tv", moods=",funny,")
        self.cartoon = title("Cartoon", maturity=0, moods=",funny,feelgood,", genre="Animation")
        self.seen = title("Seen Already", moods=",funny,")
        WatchEvent.objects.create(profile=self.adult, title=self.seen, watched_on="2026-01-01", watched_at="2026-01-01T20:00Z")


class FindTitlesTests(Base):
    def names(self, profile, **args):
        return {t["title"] for t in ask.find_titles(profile, args)}

    def test_filters(self):
        self.assertEqual(self.names(self.adult, moods=["funny"]), {"Funny Film", "Long Funny Film", "Funny Show", "Cartoon"})
        self.assertEqual(self.names(self.adult, moods=["funny"], kind="tv"), {"Funny Show"})
        self.assertEqual(self.names(self.adult, moods=["funny"], kind="movie", max_minutes=100), {"Funny Film", "Cartoon"})
        self.assertEqual(self.names(self.adult, genres=["Horror"]), {"Scary Film"})
        self.assertNotIn("Seen Already", self.names(self.adult))  # watched: left out

    def test_age_limit(self):
        self.assertEqual(self.names(self.kid, moods=["funny", "scary"]), {"Cartoon"})

    def test_what_claude_sees(self):
        [row] = ask.find_titles(self.adult, {"genres": ["Horror"]})
        self.assertEqual(row["moods"], ["scary"])
        self.assertEqual((row["type"], row["minutes"], row["year"]), ("movie", 95, 2010))


class AnswerTests(Base):
    def run_with(self, replies, message="Quelque chose de drôle", history=None):
        client = mock.MagicMock()
        client.messages.create.side_effect = replies
        with mock.patch("reco.ask._client", return_value=client):
            result = ask.answer(self.adult, message, history or [])
        return result, client.messages.create

    def test_only_titles_the_search_returned(self):
        result, create = self.run_with([search_call(moods=["funny"]),
                                        final([self.funny.id, self.scary.id, 999999, self.funny.id])])
        # Scary Film exists but this search didn't return it; 999999 doesn't exist; repeats dropped
        self.assertEqual(result["title_ids"], [self.funny.id])
        self.assertEqual(result["chips"], ["Plus court", "Plus léger", "Une série"])
        first = create.call_args_list[0].kwargs
        self.assertIn("in French", first["system"])
        self.assertIn("Seen Already", first["system"])  # what it watched lately
        self.assertEqual(first["tools"][0]["name"], "find_titles")
        sent_back = json.loads(create.call_args_list[1].kwargs["messages"][-1]["content"][0]["content"])
        self.assertIn(self.funny.id, [t["id"] for t in sent_back])

    def test_every_call_is_counted(self):
        self.run_with([search_call(moods=["funny"]), final([self.funny.id])])
        usage = AiUsage.objects.get(feature="ask")
        self.assertEqual(usage.profile, self.adult)
        self.assertAlmostEqual(usage.cost_usd, 2 * (3000 * 0.10 + 300 * 0.50) / 1e6)

    def test_a_few_searches_at_most(self):
        replies = [search_call(moods=["funny"])] * ask.MAX_ROUNDS + [final([self.funny.id])]
        result, create = self.run_with(replies)
        self.assertEqual(create.call_count, ask.MAX_ROUNDS + 1)
        self.assertEqual(create.call_args_list[-1].kwargs["tool_choice"], {"type": "none"})  # last: answer now
        self.assertEqual(result["title_ids"], [self.funny.id])

    def test_history_goes_back(self):
        _, create = self.run_with([final([])], history=[{"message": "Un film", "reply": "Essaie ceux-là."}] * 9)
        messages = create.call_args_list[0].kwargs["messages"]
        self.assertEqual(len(messages), 2 * ask.MAX_HISTORY + 1)
        self.assertEqual(messages[-1], {"role": "user", "content": "Quelque chose de drôle"})

    def test_failures(self):
        self.assertIsNone(self.run_with([NS(stop_reason="refusal", usage=USAGE, content=[])])[0])
        self.assertIsNone(self.run_with([NS(stop_reason="end_turn", usage=USAGE, content=[NS(type="text", text="not json")])])[0])
        self.assertIsNone(self.run_with(RuntimeError("API down"))[0])
        self.assertEqual(AiUsage.objects.filter(feature="ask").count(), 2)  # the two answers that came back cost


@override_settings(AI_FAKE=True)  # the scripted fake (reco/ask_fake.py), as in the end-to-end tests
class AskViewTests(Base):
    def setUp(self):
        super().setUp()
        self.api = APIClient()
        self.api.force_authenticate(self.user)

    def post(self, profile, message="something funny"):
        return self.api.post("/api/ask/", {"profileId": profile.id, "message": message, "history": []}, format="json")

    def test_answer(self):
        r = self.post(self.adult)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["reply"], "Here are a few ideas for tonight.")
        self.assertEqual(len(r.data["chips"]), 3)
        names = [i["title"] for i in r.data["items"]]
        self.assertTrue(names and set(names) <= {"Funny Film", "Long Funny Film", "Funny Show", "Cartoon"}, names)
        self.assertEqual(set(r.data["items"][0]) >= {"id", "type", "title", "poster", "minutes"}, True)

    def test_kids_only_get_what_they_may_watch(self):
        r = self.post(self.kid)
        self.assertEqual([i["title"] for i in r.data["items"]], ["Cartoon"])

    def test_empty_message_and_someone_elses_profile(self):
        self.assertEqual(self.post(self.adult, message="  ").status_code, 400)
        other = Profile.objects.create(user=User.objects.create_user("b@example.com", "B", "pw-b-123456!"),
                                       name="B", age_restriction="NC-17", language_preference="en")
        self.assertEqual(self.post(other).status_code, 404)

    def test_caps(self):
        for _ in range(12):  # 12 messages today by this account
            AiUsage.objects.create(feature="ask", profile=self.adult, cost_usd=0.0001)
        r = self.post(self.adult)
        self.assertEqual((r.status_code, r.data["code"], r.data["reason"]), (429, "ai_budget", "user"))

    def test_unavailable(self):
        with mock.patch("reco.ask.answer", return_value=None):
            r = self.post(self.adult)
        self.assertEqual((r.status_code, r.data["code"]), (503, "ask_unavailable"))
