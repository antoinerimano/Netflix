"""
manage.py write_recaps: "Catch me up" recaps written ahead, at night (roadmap 8.1), so the button
on a show page opens at once and never has to wait for (or be refused by) a live AI call.

Each run (nightly cron, before people come back to their shows):
  1. collects the batches sent earlier that have ended: each recap is kept (ShowRecap, the same
     table the button reads), and what the batch cost is recorded (reco/ai_budget.py "recap_job");
  2. if no batch is still running, sends a new one: for every show a profile watched in the last
     ACTIVE_DAYS days, the recap of everything before the episode it resumes at (reco/recap.py, the
     same prompt as the button), in its language, not already kept; most recently watched first.
     Within tonight's share of the background jobs' AI budget (jobs_daily_allowance: what's left
     this month / the days left) and --limit.
Message Batches: half price, done within 24 h (usually under an hour). The live button stays as
a fallback for a show started since the last run, within its own caps.
"""
from datetime import timedelta
from types import SimpleNamespace

from django.core.management.base import BaseCommand
from django.utils import timezone

from reco import ai_budget, recap
from reco.models import RecapBatch, ShowRecap, WatchProgress
from users.jobs import tracked
from users.models import Title

ACTIVE_DAYS = 14          # a show watched in the last 2 weeks: likely to be picked up again
COST_PER_RECAP = 0.0005   # US$ at batch price, with a margin (measured ~0.0003: ~3,000 tokens in, ~500 out)


def _client():
    import anthropic

    return anthropic.Anthropic()


def custom_id(title_id, season, episode, language):
    return f"r{title_id}-{season}-{episode}-{language}"  # [a-zA-Z0-9_-]{1,64}


class Command(BaseCommand):
    help = "Write 'Catch me up' recaps ahead of time, as Claude Message Batches, within the AI budget."

    def add_arguments(self, p):
        p.add_argument("--limit", type=int, default=200, help="recaps sent in one batch at most")
        p.add_argument("--dry-run", action="store_true", help="say what would be sent, send nothing")

    @tracked("write_recaps")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **o):
        if o["dry_run"]:
            todo = self._todo(o["limit"])
            cost = len(todo) * COST_PER_RECAP
            self.stdout.write(f"{len(todo)} recaps to write: about US${cost:.3f} (tonight's share: "
                              f"US${ai_budget.jobs_daily_allowance():.3f}).")
            return

        client = _client()
        running = self._collect(client)
        if running:
            self.stdout.write(f"{running} batch(es) still running: nothing new sent.")
            return
        limit = min(o["limit"], int(ai_budget.jobs_daily_allowance() / COST_PER_RECAP))
        if limit <= 0:
            self.stdout.write("Tonight's share of the AI budget for background jobs is used up: nothing sent.")
            return
        todo = self._todo(limit)
        if not todo:
            self.stdout.write("Every recap people may need is written.")
            return
        self._send(client, todo)

    # ---- what to write ----
    def _todo(self, limit):
        """[(custom id, (title id, season, episode, language), params)], most recently watched first."""
        since = timezone.now() - timedelta(days=ACTIVE_DAYS)
        out, seen = [], set()
        progress = (
            WatchProgress.objects.filter(title__type="tv", updated_at__gte=since)
            .select_related("profile", "title").order_by("-updated_at")
        )
        for wp in progress:
            if len(out) >= limit:
                break
            point = recap.resume_point(wp.profile, wp.title)
            if point is None or point <= (1, 1):
                continue
            language = recap.profile_language(wp.profile)
            key = (wp.title_id, point[0], point[1], language)
            if key in seen:
                continue
            seen.add(key)
            if ShowRecap.objects.filter(title_id=key[0], season=key[1], episode=key[2], language=language).exists():
                continue
            params = recap.request_params(wp.title, point[0], point[1], language)
            if params:
                out.append((custom_id(*key), key, params))
        return out

    # ---- send ----
    def _send(self, client, todo):
        from anthropic.types.messages.batch_create_params import Request

        sent = client.messages.batches.create(requests=[Request(custom_id=cid, params=params) for cid, _, params in todo])
        RecapBatch.objects.create(batch_id=sent.id, model_name=recap.MODEL, targets={cid: list(key) for cid, key, _ in todo})
        self.stdout.write(f"Sent batch {sent.id}: {len(todo)} recaps.")

    # ---- collect ----
    def _collect(self, client):
        """Keeps the recaps of every ended batch; returns how many are still running."""
        running = 0
        for batch in RecapBatch.objects.filter(collected_at__isnull=True).order_by("created_at"):
            if client.messages.batches.retrieve(batch.batch_id).processing_status != "ended":
                running += 1
                continue
            counts = {"kept": 0, "declined": 0, "failed": 0}
            spent = SimpleNamespace(input_tokens=0, output_tokens=0, usd=0.0)
            for result in client.messages.batches.results(batch.batch_id):
                if result.result.type != "succeeded":  # errored / expired: written next run if still needed
                    counts["failed"] += 1
                    continue
                msg = result.result.message
                spent.input_tokens += msg.usage.input_tokens or 0
                spent.output_tokens += msg.usage.output_tokens or 0
                spent.usd += ai_budget.cost(msg.usage, batch.model_name, batch=True)  # billed even when declined
                target = batch.targets.get(result.custom_id)
                text = recap.message_text(msg)
                if not target or not text:
                    counts["declined"] += 1
                    continue
                title_id, season, episode, language = target
                if not Title.objects.filter(id=title_id).exists():
                    continue
                ShowRecap.objects.get_or_create(  # a live one written meanwhile wins
                    title_id=title_id, season=season, episode=episode, language=language,
                    defaults={"text": text, "model_name": batch.model_name},
                )
                counts["kept"] += 1
            ai_budget.record("recap_job", spent, batch.model_name, usd=spent.usd)
            batch.collected_at = timezone.now()
            batch.summary = ", ".join(f"{k} {v}" for k, v in counts.items()) + f", US${spent.usd:.3f}"
            batch.save(update_fields=["collected_at", "summary"])
            self.stdout.write(f"Batch {batch.batch_id}: {batch.summary}.")
        return running
