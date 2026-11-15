"""manage.py ai_report [--days 28]: "Does the AI help?" (reco/ai_report.py), the same as the
admin dashboard's card, in the terminal."""
from django.core.management.base import BaseCommand

from reco.ai_report import report


def pct(x):
    return "-" if x is None else f"{x:.1%}"


class Command(BaseCommand):
    help = "Compare what people do with AI vs non-AI suggestions (shown / clicked / played)."

    def add_arguments(self, p):
        p.add_argument("--days", type=int, default=28)

    def handle(self, *args, **o):
        for c in report(days=o["days"]):
            self.stdout.write(f"\n{c['label']} (decided on: {c['metric']}), last {o['days']} days")
            for g in c["groups"]:
                self.stdout.write(f"  {g['label']:<22} shown {g['shown']:>6}  clicked {g['clicked']:>5} "
                                  f"({pct(g['click_rate'])})  played {g['played']:>5} ({pct(g['play_rate'])})")
            self.stdout.write(f"  -> {c['verdict']}" + (f" (p = {c['p']:.3f})" if c["p"] is not None else ""))
