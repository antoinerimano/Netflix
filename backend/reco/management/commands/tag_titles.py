"""
manage.py tag_titles: AI moods / themes / pacing / content notes for titles (reco/tags.py).

Each run (nightly cron):
  1. collects the batches sent earlier that have ended (saves their tags);
  2. if no batch is still running, sends a new one: titles never tagged or whose TMDB data
     changed since, most popular first, up to --limit.
Batches cost half the normal price and finish within 24 h (usually under an hour), so nothing
waits on them. --wait stays until the batch it sent has ended (first run by hand).
--dry-run sends nothing: how many titles need tags and a rough cost.

What each batch cost is recorded when it's collected (reco/ai_budget.py). The catalog's first
tagging (batches sent before AI_BUDGET_EXEMPT_UNTIL) isn't counted in the US$5 a month; after
it, a new batch is cut to what the background jobs' budget (US$1 a month) has left.

Needs ANTHROPIC_API_KEY in backend/.env (except --dry-run).
"""
import time
from types import SimpleNamespace

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from reco import ai_budget, tags
from reco.models import TagBatch, TitleTags
from users.jobs import tracked
from users.models import Title

# Rough price per million tokens, batch rate (half the normal price), for --dry-run only.
PRICES = {"claude-haiku-5-5": (0.05, 0.25), "claude-sonnet-5-5": (1.0, 5.0), "claude-opus-5-5": (2.0, 10.0)}
OUT_TOKENS = 400  # thinking (effort low) + the JSON
COST_PER_TITLE = 0.0001  # US$, batch price: measured ~0.000075 (1,030 tokens in, 95 out), with a margin


def _client():
    import anthropic

    return anthropic.Anthropic()


class Command(BaseCommand):
    help = "AI tags (moods, themes, pacing, content notes) for titles, through Claude Message Batches."

    def add_arguments(self, p):
        p.add_argument("--limit", type=int, default=5000, help="titles sent in one batch (max 100,000)")
        p.add_argument("--model", default=tags.MODEL)
        p.add_argument("--min-votes", type=int, default=20, help="skip titles almost nobody rated")
        p.add_argument("--wait", action="store_true", help="wait for the batch sent to end, then save it")
        p.add_argument("--dry-run", action="store_true", help="count and estimate, send nothing")

    @tracked("tag_titles")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        if o["dry_run"]:
            return self._estimate(self._todo(o["min_votes"], o["limit"]), o["model"])

        client = _client()
        running = self._collect(client)  # first: what it saves isn't sent again
        if running:
            self.stdout.write(f"{running} batch(es) still running: nothing new sent.")
            return
        limit = o["limit"]
        if not ai_budget.is_setup(timezone.now()):  # past the first tagging: within the jobs' budget
            limit = min(limit, int(ai_budget.jobs_budget_left() / COST_PER_TITLE))
            if limit <= 0:
                self.stdout.write("The AI budget for background jobs is used up this month: nothing sent.")
                return
        todo = self._todo(o["min_votes"], limit)
        if not todo:
            self.stdout.write("Every title is tagged.")
            return

        batch = self._send(client, todo, o["model"])
        if o["wait"]:
            while client.messages.batches.retrieve(batch.batch_id).processing_status != "ended":
                time.sleep(30)
            self._collect(client)

    # ---- what to tag ----
    def _todo(self, min_votes, limit):
        qs = (
            Title.objects.filter(Q(vote_count__gte=min_votes) | Q(vote_count__isnull=True))
            .exclude(description="")
            .select_related("tags")
            .only("id", "type", "title", "original_title", "release_year", "first_air_date", "genre",
                  "keywords", "tagline", "description", "tags__source_hash")
            .order_by("-popularity", "id")
        )
        out = []
        for t in qs.iterator(chunk_size=2000):
            h = tags.source_hash(t)
            current = getattr(t, "tags", None)
            if current is None or current.source_hash != h:
                out.append((t, h))
                if len(out) >= limit:
                    break
        return out

    def _estimate(self, todo, model):
        chars = sum(len(tags.SYSTEM) + len(tags.title_text(t)) for t, _ in todo)
        tokens_in = chars / 4
        p_in, p_out = PRICES.get(model, PRICES["claude-opus-5-5"])
        cost = tokens_in / 1e6 * p_in + len(todo) * OUT_TOKENS / 1e6 * p_out
        self.stdout.write(f"{len(todo)} titles to tag with {model}: about ${cost:.2f} (batch price).")

    # ---- send ----
    def _send(self, client, todo, model):
        from anthropic.types.messages.batch_create_params import Request

        requests = [Request(custom_id=tags.custom_id(t.id), params=tags.request_params(t, model)) for t, _ in todo]
        sent = client.messages.batches.create(requests=requests)
        batch = TagBatch.objects.create(
            batch_id=sent.id, model_name=model, hashes={str(t.id): h for t, h in todo},
        )
        self.stdout.write(f"Sent batch {sent.id}: {len(todo)} titles ({model}).")
        return batch

    # ---- collect ----
    def _collect(self, client):
        """Saves every ended batch; returns how many are still running."""
        running = 0
        for batch in TagBatch.objects.filter(collected_at__isnull=True).order_by("created_at"):
            status = client.messages.batches.retrieve(batch.batch_id).processing_status
            if status != "ended":
                running += 1
                continue
            counts = {"saved": 0, "refused": 0, "unusable": 0, "failed": 0}
            spent = SimpleNamespace(input_tokens=0, output_tokens=0, usd=0.0)
            for result in client.messages.batches.results(batch.batch_id):
                if result.result.type == "succeeded":  # every answer is billed: counted first
                    usage = result.result.message.usage
                    spent.input_tokens += usage.input_tokens or 0
                    spent.output_tokens += usage.output_tokens or 0
                    spent.usd += ai_budget.cost(usage, batch.model_name, batch=True)
                tid = tags.title_id_of(result.custom_id)
                h = batch.hashes.get(str(tid)) if tid else None
                if h is None:
                    continue
                if result.result.type != "succeeded":  # errored / expired / canceled: sent again next run
                    counts["failed"] += 1
                    continue
                parsed = tags.parse(result.result.message)
                if parsed is None:  # cut off / not JSON: sent again next run
                    counts["unusable"] += 1
                    continue
                counts["refused" if not parsed else "saved"] += 1
                if not Title.objects.filter(id=tid).exists():
                    continue
                TitleTags.objects.update_or_create(
                    title_id=tid,
                    defaults={**tags.as_fields(parsed), "source_hash": h, "model_name": batch.model_name},
                )
            feature = "tags_setup" if ai_budget.is_setup(batch.created_at) else "tags"
            ai_budget.record(feature, spent, batch.model_name, usd=spent.usd)
            batch.collected_at = timezone.now()
            batch.summary = ", ".join(f"{k} {v}" for k, v in counts.items()) + f", US${spent.usd:.2f}"
            batch.save(update_fields=["collected_at", "summary"])
            self.stdout.write(f"Batch {batch.batch_id}: {batch.summary}.")
        return running
