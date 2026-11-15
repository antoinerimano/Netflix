"""AI title tags (reco/tags.py, manage.py tag_titles, their use in /pick): a fake Claude client,
nothing is sent to the real API."""
import json
from io import StringIO
from types import SimpleNamespace as NS
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from users.models import Profile, Title, User

from . import tags
from .models import TagBatch, TitleTags
from .pick import MOODS as PICK_MOODS


def message(payload, stop_reason="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return NS(stop_reason=stop_reason, content=[NS(type="thinking", thinking=""), NS(type="text", text=text)])


class FakeBatches:
    def __init__(self):
        self.sent = []          # the requests of each create()
        self.status = {}        # batch id -> processing_status
        self.answers = {}       # batch id -> {custom_id: result}

    def create(self, requests):
        bid = f"msgbatch_{len(self.sent) + 1}"
        self.sent.append(list(requests))
        self.status[bid] = "in_progress"
        return NS(id=bid, processing_status="in_progress")

    def retrieve(self, bid):
        return NS(id=bid, processing_status=self.status[bid])

    def results(self, bid):
        return [NS(custom_id=cid, result=r) for cid, r in self.answers.get(bid, {}).items()]


class FakeClient:
    def __init__(self):
        self.messages = NS(batches=FakeBatches())


def ok(payload, stop_reason="end_turn"):
    return NS(type="succeeded", message=message(payload, stop_reason))


GOOD = {"moods": ["funny", "feelgood"], "themes": ["Road Trip", "found family"], "pacing": "fast", "content_notes": []}


def make_title(name, genre="Comedy", votes=5000, description="A story.", **kw):
    return Title.objects.create(type=kw.pop("type", "movie"), title=name, genre=genre, vote_count=votes,
                                vote_average=7.5, popularity=votes / 100, description=description, **kw)


class CleanTests(TestCase):
    def test_pick_moods_are_tag_moods(self):
        self.assertTrue(set(PICK_MOODS) <= set(tags.MOODS))

    def test_clean_keeps_allowed_values_in_limits(self):
        out = tags.clean({
            "moods": ["funny", "nope", "funny", "dark", "sad", "tense", "cozy"],
            "themes": ["  Time   Loop ", "time loop", 3, "x" * 80, "a", "b", "c", "d", "e"],
            "pacing": "very fast",
            "content_notes": ["gore", "made_up"],
        })
        self.assertEqual(out["moods"], ["funny", "dark", "sad", "tense"])
        self.assertEqual(out["themes"][0], "time loop")
        self.assertEqual(len(out["themes"]), tags.MAX_THEMES)
        self.assertEqual(len(out["themes"][1]), 40)
        self.assertEqual(out["pacing"], "")
        self.assertEqual(out["content_notes"], ["gore"])

    def test_parse(self):
        self.assertEqual(tags.parse(message(GOOD))["moods"], ["funny", "feelgood"])
        self.assertEqual(tags.parse(message("", stop_reason="refusal")), {})
        self.assertIsNone(tags.parse(message('{"moods": [', stop_reason="max_tokens")))
        self.assertIsNone(tags.parse(message("not json")))

    def test_request_uses_structured_output_and_title_data(self):
        t = make_title("Little Trip", keywords=["road trip", "family"], tagline="Buckle up.", release_year=2006)
        p = tags.request_params(t)
        self.assertEqual(p["model"], tags.MODEL)
        self.assertEqual(p["output_config"]["format"]["schema"], tags.SCHEMA)
        text = p["messages"][0]["content"]
        for part in ("Movie: Little Trip (2006)", "Genres: Comedy", "road trip, family", "Buckle up.", "A story."):
            self.assertIn(part, text)


class CommandTests(TestCase):
    def setUp(self):
        self.client_ = FakeClient()
        patcher = mock.patch("reco.management.commands.tag_titles._client", return_value=self.client_)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.popular = make_title("Popular", votes=9000)
        self.other = make_title("Other", votes=3000)
        self.obscure = make_title("Obscure", votes=2)                 # under --min-votes
        self.empty = make_title("No Overview", description="")        # nothing to go on

    def run_cmd(self, *args):
        out = StringIO()
        call_command("tag_titles", *args, stdout=out)
        return out.getvalue()

    @property
    def batches(self):
        return self.client_.messages.batches

    def test_dry_run_sends_nothing(self):
        out = self.run_cmd("--dry-run")
        self.assertIn("2 titles to tag", out)
        self.assertEqual(self.batches.sent, [])

    def test_send_then_collect_on_the_next_run(self):
        self.run_cmd()
        ids = [r["custom_id"] for r in self.batches.sent[0]]
        self.assertEqual(ids, [f"t{self.popular.id}", f"t{self.other.id}"])  # most popular first

        out = self.run_cmd()  # still running: waits, sends nothing new
        self.assertIn("still running", out)
        self.assertEqual(len(self.batches.sent), 1)

        self.batches.status["msgbatch_1"] = "ended"
        self.batches.answers["msgbatch_1"] = {
            f"t{self.popular.id}": ok(GOOD),
            f"t{self.other.id}": NS(type="errored"),
        }
        self.run_cmd()
        tt = TitleTags.objects.get(title=self.popular)
        self.assertEqual(tt.moods, ",funny,feelgood,")
        self.assertEqual(tt.themes, ["road trip", "found family"])
        self.assertEqual(tt.model_name, tags.MODEL)
        self.assertIsNotNone(TagBatch.objects.get(batch_id="msgbatch_1").collected_at)
        # the errored one is sent again, the tagged one isn't
        self.assertEqual([r["custom_id"] for r in self.batches.sent[1]], [f"t{self.other.id}"])

    def test_refusal_is_kept_cut_off_is_retried(self):
        self.run_cmd("--limit", "2")
        self.batches.status["msgbatch_1"] = "ended"
        self.batches.answers["msgbatch_1"] = {
            f"t{self.popular.id}": ok("", stop_reason="refusal"),
            f"t{self.other.id}": ok('{"moods": [', stop_reason="max_tokens"),
        }
        self.run_cmd()
        self.assertEqual(TitleTags.objects.get(title=self.popular).moods, "")
        self.assertFalse(TitleTags.objects.filter(title=self.other).exists())
        self.assertEqual([r["custom_id"] for r in self.batches.sent[1]], [f"t{self.other.id}"])

    def test_retagged_when_the_title_changes(self):
        for t in (self.popular, self.other):
            TitleTags.objects.create(title=t, moods=",funny,", source_hash=tags.source_hash(t))
        self.assertIn("Every title is tagged", self.run_cmd())
        self.other.description = "A new overview."
        self.other.save()
        self.run_cmd()
        self.assertEqual([r["custom_id"] for r in self.batches.sent[0]], [f"t{self.other.id}"])

    def test_wait(self):
        def ended_on_retrieve(bid):
            self.batches.status[bid] = "ended"
            self.batches.answers[bid] = {f"t{self.popular.id}": ok(GOOD)}
            return NS(id=bid, processing_status="ended")

        with mock.patch.object(self.batches, "retrieve", side_effect=ended_on_retrieve):
            self.run_cmd("--wait", "--limit", "1")
        self.assertTrue(TitleTags.objects.filter(title=self.popular).exists())


class EmbeddingTextTests(TestCase):
    def test_embedding_text(self):
        t = make_title("X")
        self.assertEqual(tags.embedding_text(None), "")
        tt = TitleTags.objects.create(title=t, moods=",dark,tense,", themes=["heist"], pacing="slow")
        self.assertEqual(tags.embedding_text(tt), "dark tense | heist | slow paced")


class PickWithTagsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.profile = Profile.objects.create(user=user, name="A", age_restriction="NC-17", language_preference="en")
        self.api.force_authenticate(user)

        def movie(name, genre):
            return Title.objects.create(type="movie", title=name, genre=genre, runtime_minutes=90, vote_count=5000,
                                        vote_average=7.5, poster="p.jpg", maturity=2, popularity=50,
                                        release_date="2000-01-01")

        self.grim_comedy = movie("Grim Comedy", "Comedy, Drama")     # a comedy by genre, not funny per Claude
        self.funny_drama = movie("Funny Drama", "Drama")             # not a comedy by genre, funny per Claude
        self.untagged = movie("Plain Comedy", "Comedy")              # no tags yet: genres decide
        self.declined = movie("Declined Comedy", "Comedy")           # Claude declined: genres decide
        TitleTags.objects.create(title=self.grim_comedy, moods=",dark,sad,")
        TitleTags.objects.create(title=self.funny_drama, moods=",funny,thoughtful,")
        TitleTags.objects.create(title=self.declined, moods="")

    def test_tags_decide_the_mood_when_there_are_some(self):
        r = self.api.get("/api/pick/", {"profileId": self.profile.id, "time": "any", "mood": "funny", "count": 12})
        self.assertEqual(r.status_code, 200)
        names = {i["title"] for i in r.data["items"]}
        self.assertEqual(names, {"Funny Drama", "Plain Comedy", "Declined Comedy"})
