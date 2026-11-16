"""Recaps written ahead at night (roadmap 8.1, manage.py write_recaps): who gets one, the budget
share, send then collect, what is kept. A fake Claude client: nothing is sent to the real API."""
import datetime as dt
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace as NS
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from users.models import Episode, Profile, Season, Title, User

from . import ai_budget, recap
from .management.commands.write_recaps import custom_id
from .models import AiUsage, RecapBatch, ShowRecap, WatchProgress


class FakeBatches:
    def __init__(self):
        self.sent, self.status, self.answers = [], {}, {}

    def create(self, requests):
        bid = f"msgbatch_r{len(self.sent) + 1}"
        self.sent.append(list(requests))
        self.status[bid] = "in_progress"
        return NS(id=bid)

    def retrieve(self, bid):
        return NS(processing_status=self.status[bid])

    def results(self, bid):
        return [NS(custom_id=cid, result=r) for cid, r in self.answers.get(bid, {}).items()]


def ok(text="Last time: it went well.", stop_reason="end_turn"):
    return NS(type="succeeded", message=NS(stop_reason=stop_reason, content=[NS(type="text", text=text)],
                                           usage=NS(input_tokens=3000, output_tokens=500)))


class WriteRecapsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a@example.com", "A", "pw-a-123456!")
        self.show = Title.objects.create(type="tv", title="Chem", description="A teacher.", maturity=2)
        for s in (1, 2):
            season = Season.objects.create(tv=self.show, season_number=s)
            for e in (1, 2, 3):
                Episode.objects.create(season=season, episode_number=e, name=f"E{s}.{e}", overview=f"Plot {s}.{e}.")

        def profile(name, lang, season, episode, days_ago=0):
            p = Profile.objects.create(user=self.user, name=name, age_restriction="NC-17", language_preference=lang)
            wp = WatchProgress.objects.create(profile=p, title=self.show, season_number=season, episode_number=episode)
            WatchProgress.objects.filter(id=wp.id).update(updated_at=timezone.now() - timedelta(days=days_ago))
            return p

        self.fr = profile("Fr", "fr", 2, 2, days_ago=1)
        self.en = profile("En", "en", 2, 2, days_ago=0)       # most recent: first
        self.en2 = profile("En2", "en", 2, 2, days_ago=2)     # same show, point and language: one recap
        self.start = profile("Start", "en", 1, 1)             # nothing to recap yet
        self.old = profile("Old", "de", 2, 3, days_ago=30)    # not watched for a month: left out

        self.client_ = NS(messages=NS(batches=FakeBatches()))
        patcher = mock.patch("reco.management.commands.write_recaps._client", return_value=self.client_)
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def batches(self):
        return self.client_.messages.batches

    def run_cmd(self, *args):
        out = StringIO()
        call_command("write_recaps", *args, stdout=out)
        return out.getvalue()

    def test_dry_run(self):
        self.assertIn("2 recaps to write", self.run_cmd("--dry-run"))
        self.assertEqual(self.batches.sent, [])

    def test_send_who_and_what(self):
        self.run_cmd()
        [requests] = self.batches.sent
        ids = [r["custom_id"] for r in requests]
        self.assertEqual(ids, [custom_id(self.show.id, 2, 2, "en"), custom_id(self.show.id, 2, 2, "fr")])
        # the same prompt as the button
        self.assertEqual(requests[1]["params"], recap.request_params(self.show, 2, 2, "fr"))
        self.assertEqual(RecapBatch.objects.get().targets[ids[1]], [self.show.id, 2, 2, "fr"])

    def test_already_kept_is_not_written_again(self):
        ShowRecap.objects.create(title=self.show, season=2, episode=2, language="fr", text="Kept.")
        self.run_cmd()
        self.assertEqual([r["custom_id"] for r in self.batches.sent[0]], [custom_id(self.show.id, 2, 2, "en")])

    def test_collect_keeps_recaps_and_records_the_cost(self):
        self.run_cmd()
        en, fr = custom_id(self.show.id, 2, 2, "en"), custom_id(self.show.id, 2, 2, "fr")
        self.assertIn("still running", self.run_cmd())  # nothing new meanwhile
        self.assertEqual(len(self.batches.sent), 1)
        ShowRecap.objects.create(title=self.show, season=2, episode=2, language="fr", text="Live one.")  # written meanwhile
        self.batches.status["msgbatch_r1"] = "ended"
        self.batches.answers["msgbatch_r1"] = {en: ok("Night one."), fr: ok("Night fr.")}
        out = self.run_cmd()
        self.assertEqual(ShowRecap.objects.get(language="en").text, "Night one.")
        self.assertEqual(ShowRecap.objects.get(language="fr").text, "Live one.")  # not replaced
        usage = AiUsage.objects.get(feature="recap_job")
        self.assertAlmostEqual(usage.cost_usd, 2 * (3000 * 0.10 + 500 * 0.50) / 1e6 / 2)
        self.assertIn("Every recap people may need is written", out)

    def test_declined_or_failed_not_kept(self):
        self.run_cmd()
        en, fr = custom_id(self.show.id, 2, 2, "en"), custom_id(self.show.id, 2, 2, "fr")
        self.batches.status["msgbatch_r1"] = "ended"
        self.batches.answers["msgbatch_r1"] = {en: ok("", stop_reason="refusal"), fr: NS(type="errored")}
        self.run_cmd()
        self.assertFalse(ShowRecap.objects.exists())
        self.assertEqual(RecapBatch.objects.get(batch_id="msgbatch_r1").summary.split(", US$")[0],
                         "kept 0, declined 1, failed 1")
        self.assertEqual(len(self.batches.sent), 2)  # both asked again on the next batch

    def test_within_tonights_share_of_the_budget(self):
        with mock.patch.object(ai_budget, "jobs_daily_allowance", return_value=0.0005):  # one recap
            self.run_cmd()
        self.assertEqual(len(self.batches.sent[0]), 1)
        self.batches.status["msgbatch_r1"] = "ended"  # (its recap came back: nothing kept here)
        with mock.patch.object(ai_budget, "jobs_daily_allowance", return_value=0.0):
            self.assertIn("used up", self.run_cmd())


class DailyAllowanceTests(TestCase):
    def test_left_spread_over_the_days_left(self):
        nov16 = timezone.make_aware(dt.datetime(2026, 11, 16, 3, 0))
        dec31 = timezone.make_aware(dt.datetime(2026, 12, 31, 3, 0))
        AiUsage.objects.create(feature="tags", cost_usd=0.25)  # US$0.75 left of the jobs' US$1
        with mock.patch.object(ai_budget, "jobs_budget_left", return_value=0.75):
            self.assertAlmostEqual(ai_budget.jobs_daily_allowance(nov16), 0.75 / 15)  # Nov 16..30
            self.assertAlmostEqual(ai_budget.jobs_daily_allowance(dec31), 0.75)       # the last day
