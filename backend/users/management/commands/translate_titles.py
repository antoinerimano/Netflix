"""
manage.py translate_titles: overviews TMDB doesn't have in a language the profiles use, translated
by Claude from the English one (users/ai_translate.py, roadmap 8.6).

Each run (nightly cron):
  1. collects the batches sent earlier that have ended: each translation is saved as the title's
     overview in that language, machine_translated (unless TMDB filled it meanwhile), and what the
     batch cost is recorded (reco/ai_budget.py "translate");
  2. if no batch is still running, sends a new one: the gaps in the languages profiles use, most
     popular titles first, within tonight's share of the background jobs' AI budget and --limit.
  --dry-run   how many gaps, in which languages, and a rough cost; sends nothing
"""
from types import SimpleNamespace

from django.core.management.base import BaseCommand
from django.utils import timezone

from reco import ai_budget
from users import ai_translate
from users.jobs import tracked
from users.models import Title, TitleTranslation, TranslationBatch

COST_PER_TRANSLATION = 0.0002  # US$ at batch price, with a margin (an overview: ~400 tokens in, ~400 out)


def _client():
    import anthropic

    return anthropic.Anthropic()


class Command(BaseCommand):
    help = "Translate missing overviews (languages profiles use, TMDB first) with Claude Message Batches."

    def add_arguments(self, p):
        p.add_argument("--limit", type=int, default=2000, help="translations sent in one batch at most")
        p.add_argument("--dry-run", action="store_true", help="count the gaps, send nothing")

    @tracked("translate_titles")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        languages = ai_translate.languages_in_use()
        if o["dry_run"]:
            todo = ai_translate.gaps(languages, 100000)
            per_lang = {lang: sum(1 for _, l in todo if l == lang) for lang in languages}
            self.stdout.write(f"Languages in use: {', '.join(languages) or 'none but English'}. "
                              f"{len(todo)} overviews to translate ({per_lang}): about "
                              f"US${len(todo) * COST_PER_TRANSLATION:.2f}.")
            return

        client = _client()
        running = self._collect(client)
        if running:
            self.stdout.write(f"{running} batch(es) still running: nothing new sent.")
            return
        if not languages:
            self.stdout.write("No profile uses another language than English: nothing to translate.")
            return
        limit = min(o["limit"], int(ai_budget.jobs_daily_allowance() / COST_PER_TRANSLATION))
        if limit <= 0:
            self.stdout.write("Tonight's share of the AI budget for background jobs is used up: nothing sent.")
            return
        todo = ai_translate.gaps(languages, limit)
        if not todo:
            self.stdout.write("Every overview is there in the languages profiles use.")
            return
        self._send(client, todo)

    def _send(self, client, todo):
        from anthropic.types.messages.batch_create_params import Request

        requests = [
            Request(custom_id=ai_translate.custom_id(t.id, lang), params=ai_translate.request_params(t, lang))
            for t, lang in todo
        ]
        sent = client.messages.batches.create(requests=requests)
        TranslationBatch.objects.create(
            batch_id=sent.id, model_name=ai_translate.MODEL,
            targets={ai_translate.custom_id(t.id, lang): [t.id, lang] for t, lang in todo},
        )
        self.stdout.write(f"Sent batch {sent.id}: {len(todo)} overviews.")

    def _collect(self, client):
        """Saves the translations of every ended batch; returns how many are still running."""
        running = 0
        for batch in TranslationBatch.objects.filter(collected_at__isnull=True).order_by("created_at"):
            if client.messages.batches.retrieve(batch.batch_id).processing_status != "ended":
                running += 1
                continue
            counts = {"saved": 0, "tmdb_meanwhile": 0, "unusable": 0, "failed": 0}
            spent = SimpleNamespace(input_tokens=0, output_tokens=0, usd=0.0)
            for result in client.messages.batches.results(batch.batch_id):
                if result.result.type != "succeeded":  # errored / expired: sent again next run
                    counts["failed"] += 1
                    continue
                msg = result.result.message
                spent.input_tokens += msg.usage.input_tokens or 0
                spent.output_tokens += msg.usage.output_tokens or 0
                spent.usd += ai_budget.cost(msg.usage, batch.model_name, batch=True)  # billed even when unusable
                target = batch.targets.get(result.custom_id)
                title = Title.objects.filter(id=target[0]).only("id", "description").first() if target else None
                text = ai_translate.translation(msg, title.description) if title else ""
                if not text:
                    counts["unusable"] += 1
                    continue
                row, _ = TitleTranslation.objects.get_or_create(title_id=title.id, language=target[1])
                if row.overview and not row.machine_translated:  # TMDB has one now: it wins
                    counts["tmdb_meanwhile"] += 1
                    continue
                row.overview, row.machine_translated = text, True
                row.save(update_fields=["overview", "machine_translated", "synced_at"])
                counts["saved"] += 1
            ai_budget.record("translate", spent, batch.model_name, usd=spent.usd)
            batch.collected_at = timezone.now()
            batch.summary = ", ".join(f"{k} {v}" for k, v in counts.items()) + f", US${spent.usd:.3f}"
            batch.save(update_fields=["collected_at", "summary"])
            self.stdout.write(f"Batch {batch.batch_id}: {batch.summary}.")
        return running
