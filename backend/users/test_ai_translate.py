"""Missing translations (roadmap 8.6, users/ai_translate.py, manage.py translate_titles): only the
languages profiles use, TMDB first (and TMDB's text wins later), most popular first, within the
budget, send then collect. A fake Claude client: nothing is sent to the real API."""
import datetime as dt
from io import StringIO
from types import SimpleNamespace as NS
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from reco import ai_budget
from reco.models import AiUsage

from . import ai_translate
from .management.commands.sync_tmdb_translations import Command as SyncCommand
from .models import Profile, Title, TitleTranslation, TranslationBatch, User


class FakeBatches:
    def __init__(self):
        self.sent, self.status, self.answers = [], {}, {}

    def create(self, requests):
        bid = f"msgbatch_t{len(self.sent) + 1}"
        self.sent.append(list(requests))
        self.status[bid] = "in_progress"
        return NS(id=bid)

    def retrieve(self, bid):
        return NS(processing_status=self.status[bid])

    def results(self, bid):
        return [NS(custom_id=cid, result=r) for cid, r in self.answers.get(bid, {}).items()]


def ok(text, stop_reason="end_turn"):
    return NS(type="succeeded", message=NS(stop_reason=stop_reason, content=[NS(type="text", text=text)],
                                           usage=NS(input_tokens=400, output_tokens=400)))


class Base(TestCase):
    def setUp(self):
        user = User.objects.create_user("a@example.com", "A", "pw-a-123456!")
        for lang in ("en", "en", "fr", "es", "es"):
            Profile.objects.create(user=user, name=f"P{Profile.objects.count()}", age_restriction="NC-17",
                                   language_preference=lang)
        self.hit = Title.objects.create(type="movie", title="Hit", description="A big hit.", popularity=90,
                                        release_year=2020, vote_count=5000)
        self.mid = Title.objects.create(type="movie", title="Mid", description="A film.", popularity=50, vote_count=400)
        self.blank = Title.objects.create(type="movie", title="Blank", description="", popularity=99,
                                          vote_count=9000)  # nothing to translate
        self.obscure = Title.objects.create(type="movie", title="Obscure", description="Few saw it.",
                                            popularity=95, vote_count=12)  # hardly anyone opens it: left out
        # TMDB already has these
        TitleTranslation.objects.create(title=self.hit, language="fr", name="Succès", overview="Un grand succès.")
        TitleTranslation.objects.create(title=self.mid, language="es", name="", overview="")  # synced, but empty


class GapsTests(Base):
    def test_languages_in_use(self):
        self.assertEqual(ai_translate.languages_in_use(), ["es", "fr"])  # most used first, never English

    def test_gaps_most_popular_first(self):
        gaps = [(t.title, lang) for t, lang in ai_translate.gaps(["es", "fr"], 10)]
        # Hit/fr from TMDB, Blank: no English, Obscure: not well known
        self.assertEqual(gaps, [("Hit", "es"), ("Mid", "es"), ("Mid", "fr")])
        self.assertEqual(len(ai_translate.gaps(["es", "fr"], 2)), 2)

    def test_prompt(self):
        p = ai_translate.request_params(self.hit, "es")
        self.assertEqual(p["model"], ai_translate.MODEL)
        self.assertIn("into Spanish", p["system"])
        self.assertEqual(p["messages"][0]["content"], 'Movie "Hit" (2020)\n\nSynopsis:\nA big hit.')

    def test_translation_checks(self):
        msg = lambda text, stop="end_turn": NS(stop_reason=stop, content=[NS(type="text", text=text)])  # noqa: E731
        self.assertEqual(ai_translate.translation(msg(" Un gran éxito. "), "A big hit."), "Un gran éxito.")
        self.assertEqual(ai_translate.translation(msg("", "refusal"), "A big hit."), "")
        self.assertEqual(ai_translate.translation(msg("x" * 1000), "A big hit."), "")  # not a translation


class JobTests(Base):
    def setUp(self):
        super().setUp()
        self.client_ = NS(messages=NS(batches=FakeBatches()))
        patcher = mock.patch("users.management.commands.translate_titles._client", return_value=self.client_)
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def batches(self):
        return self.client_.messages.batches

    def run_cmd(self, *args):
        out = StringIO()
        call_command("translate_titles", *args, stdout=out)
        return out.getvalue()

    def test_dry_run(self):
        out = self.run_cmd("--dry-run")
        self.assertIn("Languages in use: es, fr", out)
        self.assertIn("3 overviews to translate", out)
        self.assertEqual(self.batches.sent, [])

    def test_send_collect_save(self):
        self.run_cmd()
        ids = [r["custom_id"] for r in self.batches.sent[0]]
        self.assertEqual(ids, [f"t{self.hit.id}-es", f"t{self.mid.id}-es", f"t{self.mid.id}-fr"])
        self.assertIn("still running", self.run_cmd())

        # meanwhile TMDB got Mid in French: TMDB's text wins
        TitleTranslation.objects.create(title=self.mid, language="fr", name="", overview="Un film (TMDB).")
        self.batches.status["msgbatch_t1"] = "ended"
        self.batches.answers["msgbatch_t1"] = {
            f"t{self.hit.id}-es": ok("Un gran éxito."),
            f"t{self.mid.id}-es": ok("", stop_reason="refusal"),
            f"t{self.mid.id}-fr": ok("Un film (Claude)."),
        }
        self.run_cmd()
        es = TitleTranslation.objects.get(title=self.hit, language="es")
        self.assertEqual((es.overview, es.machine_translated, es.name), ("Un gran éxito.", True, ""))
        self.assertEqual(TitleTranslation.objects.get(title=self.mid, language="fr").overview, "Un film (TMDB).")
        self.assertEqual(TranslationBatch.objects.get(batch_id="msgbatch_t1").summary.split(", US$")[0],
                         "saved 1, tmdb_meanwhile 1, unusable 1, failed 0")
        usage = AiUsage.objects.get(feature="translate")
        self.assertAlmostEqual(usage.cost_usd, 3 * (400 * 0.10 + 400 * 0.50) / 1e6 / 2)
        # the refused one is asked again; the others are done
        self.assertEqual([r["custom_id"] for r in self.batches.sent[1]], [f"t{self.mid.id}-es"])

    def test_within_tonights_share(self):
        with mock.patch.object(ai_budget, "jobs_daily_allowance", return_value=0.0004):  # two
            self.run_cmd()
        self.assertEqual(len(self.batches.sent[0]), 2)
        self.batches.status["msgbatch_t1"] = "ended"
        with mock.patch.object(ai_budget, "jobs_daily_allowance", return_value=0.0):
            self.assertIn("used up", self.run_cmd())

    def test_nobody_reads_another_language(self):
        Profile.objects.exclude(language_preference="en").update(language_preference="en")
        self.assertIn("nothing to translate", self.run_cmd())
        self.assertEqual(self.batches.sent, [])


class TmdbSyncKeepsAndReplacesTests(Base):
    """sync_tmdb_translations: an empty TMDB overview keeps Claude's; a real one replaces it."""

    def sync(self, overview):
        SyncCommand()._save_titles([TitleTranslation(title_id=self.mid.id, language="es", name="", overview=overview)])
        return TitleTranslation.objects.get(title=self.mid, language="es")

    def test_keeps_then_replaces(self):
        TitleTranslation.objects.filter(title=self.mid, language="es").update(overview="Una película.", machine_translated=True)
        row = self.sync("")
        self.assertEqual((row.overview, row.machine_translated), ("Una película.", True))
        row = self.sync("Una película (TMDB).")
        self.assertEqual((row.overview, row.machine_translated), ("Una película (TMDB).", False))


class DailyAllowanceTests(TestCase):
    def test_left_spread_over_the_days_left(self):
        nov16 = timezone.make_aware(dt.datetime(2026, 11, 16, 3, 0))
        dec31 = timezone.make_aware(dt.datetime(2026, 12, 31, 3, 0))
        with mock.patch.object(ai_budget, "jobs_budget_left", return_value=0.75):
            self.assertAlmostEqual(ai_budget.jobs_daily_allowance(nov16), 0.75 / 15)  # Nov 16..30
            self.assertAlmostEqual(ai_budget.jobs_daily_allowance(dec31), 0.75)       # the last day
