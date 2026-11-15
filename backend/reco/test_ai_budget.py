"""The AI budget (reco/ai_budget.py): costs, what counts, the jobs' share, the 80 % email, and
tag_titles staying within it once the catalog's first tagging is over."""
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace as NS
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from users.models import Title, User

from . import ai_budget
from .models import AiUsage, TagBatch

NO_USAGE = NS(input_tokens=0, output_tokens=0)


class BudgetTests(TestCase):
    def test_cost(self):
        u = NS(input_tokens=1_000_000, output_tokens=1_000_000)
        self.assertAlmostEqual(ai_budget.cost(u, "claude-haiku-5-5"), 0.60)
        self.assertAlmostEqual(ai_budget.cost(u, "claude-haiku-5-5", batch=True), 0.30)
        self.assertAlmostEqual(ai_budget.cost(u, "some-new-model"), 24.0)  # unknown: the dearest
        cached = NS(input_tokens=0, output_tokens=0, cache_read_input_tokens=1_000_000,
                    cache_creation_input_tokens=1_000_000)
        self.assertAlmostEqual(ai_budget.cost(cached, "claude-haiku-5-5"), 0.01 + 0.125)

    def test_setup_tagging_is_not_counted(self):
        AiUsage.objects.create(feature="tags_setup", cost_usd=4.0)
        AiUsage.objects.create(feature="recap", cost_usd=0.5)
        self.assertAlmostEqual(ai_budget.spent_this_month(), 0.5)

    def test_jobs_share(self):
        self.assertAlmostEqual(ai_budget.jobs_budget_left(), 1.0)
        AiUsage.objects.create(feature="tags", cost_usd=0.4)
        self.assertAlmostEqual(ai_budget.jobs_budget_left(), 0.6)
        AiUsage.objects.create(feature="recap", cost_usd=4.8)  # the month as a whole is nearly gone
        self.assertAlmostEqual(ai_budget.jobs_budget_left(), 0.0)

    def test_last_month_is_not_counted(self):
        old = AiUsage.objects.create(feature="recap", cost_usd=5.0)
        AiUsage.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=40))
        self.assertEqual(ai_budget.spent_this_month(), 0.0)

    def test_one_email_at_80_percent(self):
        User.objects.create_user("admin@example.com", "Admin", "pw-admin-123!", is_staff=True)
        ai_budget.record("recap", NO_USAGE, "claude-haiku-5-5", usd=3.9)
        self.assertEqual(len(mail.outbox), 0)
        ai_budget.record("recap", NO_USAGE, "claude-haiku-5-5", usd=0.2)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("US$4.10 of US$5.00", mail.outbox[0].subject)
        ai_budget.record("recap", NO_USAGE, "claude-haiku-5-5", usd=0.2)
        self.assertEqual(len(mail.outbox), 1)  # once a month


@override_settings(AI_BUDGET_EXEMPT_UNTIL="")  # the first tagging is over
class TagTitlesBudgetTests(TestCase):
    def setUp(self):
        for i in range(30):
            Title.objects.create(type="movie", title=f"T{i}", vote_count=500, popularity=i, description="A story.")
        self.client_ = mock.MagicMock()
        self.client_.messages.batches.create.return_value = NS(id="msgbatch_x")
        patcher = mock.patch("reco.management.commands.tag_titles._client", return_value=self.client_)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sent(self):
        return len(self.client_.messages.batches.create.call_args.kwargs["requests"])

    def test_batch_cut_to_the_jobs_budget(self):
        AiUsage.objects.create(feature="tags", cost_usd=0.998)  # US$0.002 left: 20 titles
        call_command("tag_titles", stdout=StringIO())
        self.assertEqual(self.sent(), 20)

    def test_nothing_sent_when_used_up(self):
        AiUsage.objects.create(feature="tags", cost_usd=1.0)
        out = StringIO()
        call_command("tag_titles", stdout=out)
        self.assertIn("used up this month", out.getvalue())
        self.client_.messages.batches.create.assert_not_called()

    def test_collected_batch_is_recorded(self):
        TagBatch.objects.create(batch_id="msgbatch_old", model_name="claude-haiku-5-5", hashes={})
        self.client_.messages.batches.retrieve.return_value = NS(processing_status="ended")
        msg = NS(stop_reason="end_turn", content=[], usage=NS(input_tokens=1000, output_tokens=100))
        self.client_.messages.batches.results.return_value = [
            NS(custom_id="t999999", result=NS(type="succeeded", message=msg)),
        ]
        call_command("tag_titles", stdout=StringIO())
        usage = AiUsage.objects.get()
        self.assertEqual(usage.feature, "tags")  # sent after the setup: counted
        self.assertAlmostEqual(usage.cost_usd, (1000 * 0.10 + 100 * 0.50) / 1e6 / 2)


class DashboardCardTests(TestCase):
    def test_ai_spend_card(self):
        from django.conf import settings

        AiUsage.objects.create(feature="recap", cost_usd=0.012)
        AiUsage.objects.create(feature="tags_setup", cost_usd=3.5)
        admin = User.objects.create_superuser("admin@example.com", "Admin", "pw-admin-123!")
        self.client.force_login(admin)
        res = self.client.get("/" + settings.ADMINADMIN_URL.strip("/") + "/dashboard/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn("AI spend this month", html)
        self.assertIn("US$0.01 of US$5.00", html)  # the first tagging is not counted
        self.assertIn("First catalog tagging (not counted)", html)
        self.assertIn("AI title tags", html)  # the job is listed with the others
