# reco/ai_budget.py
"""
The AI budget: at most US$5 a month for all Claude use (roadmap 8.9).

Every Claude call is recorded (AiUsage: feature, profile, tokens, cost from the response's usage).
Before a call, the caller asks:
  - a user-triggered feature (a button): allowed(feature, profile) -> (ok, reason)
      the month's total for everything < AI_MONTHLY_BUDGET_USD           (5.00)
      that feature's spend today        < its daily budget               (recap 0.05)
      that user's calls to it today     < its per-user limit             (recap 3)
  - a background job: jobs_budget_left() -> US$ it may still spend this month
      min(AI_JOBS_MONTHLY_BUDGET_USD - jobs this month, monthly budget - everything this month)
A cap reached: the feature says "back tomorrow", the rest of the site works as usual.
Not counted ("tags_setup"): the catalog's first tagging (tag batches sent before
AI_BUDGET_EXEMPT_UNTIL), a one-time setup the recommendations need.
At 80 % of the month's budget, staff accounts get one email.
"""
import datetime as dt
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Sum
from django.utils import timezone

log = logging.getLogger(__name__)

# US$ per million tokens (input, output), standard price; batches cost half
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
UNKNOWN_PRICE = PRICES["claude-opus-5-5"]  # an unlisted model: counted at the dearest price

EXEMPT = ("tags_setup",)           # not counted in any total
JOB_FEATURES = ("tags", "checkup", "recap_job")  # background jobs: share AI_JOBS_MONTHLY_BUDGET_USD
ALERT_FEATURE = "_budget_alert"    # a zero-cost row: the 80 % email was sent this month


def monthly_budget():
    return float(getattr(settings, "AI_MONTHLY_BUDGET_USD", 5.0))


def jobs_monthly_budget():
    return float(getattr(settings, "AI_JOBS_MONTHLY_BUDGET_USD", 1.0))


def feature_caps():
    """{feature: (US$ a day for the whole site, calls a day per user)}"""
    return getattr(settings, "AI_FEATURE_CAPS", {"recap": (0.05, 3)})


def exempt_until():
    raw = getattr(settings, "AI_BUDGET_EXEMPT_UNTIL", "2026-11-30")
    return dt.date.fromisoformat(raw) if raw else None


def is_setup(sent_at):
    """A tag batch sent before AI_BUDGET_EXEMPT_UNTIL: the catalog's first tagging (not counted)."""
    until = exempt_until()
    return bool(until and timezone.localtime(sent_at).date() < until)


def cost(usage, model, batch=False):
    """US$ for one response's usage (thinking is in output_tokens; cache reads / writes priced
    like the API: 0.1x / 1.25x input)."""
    p_in, p_out = PRICES.get(model, UNKNOWN_PRICE)
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read = getattr(usage, "cache_read_input_tokens", 0) or 0
    usd = ((inp + 1.25 * write + 0.1 * read) * p_in + out * p_out) / 1e6
    return usd / 2 if batch else usd


def _month_start(now=None):
    now = timezone.localtime(now or timezone.now())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_start(now=None):
    return timezone.localtime(now or timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)


def _spent(qs):
    return qs.exclude(feature__in=EXEMPT).aggregate(s=Sum("cost_usd"))["s"] or 0.0


def spent_this_month(features=None):
    from .models import AiUsage

    qs = AiUsage.objects.filter(created_at__gte=_month_start())
    if features:
        qs = qs.filter(feature__in=features)
    return _spent(qs)


def spent_today(feature):
    from .models import AiUsage

    return _spent(AiUsage.objects.filter(feature=feature, created_at__gte=_day_start()))


def allowed(feature, profile):
    """(True, "") when a user-triggered call fits every cap, else (False, "month" | "day" | "user")."""
    from .models import AiUsage

    if spent_this_month() >= monthly_budget():
        return False, "month"
    daily_usd, per_user = feature_caps().get(feature, (0.0, 0))
    if spent_today(feature) >= daily_usd:
        return False, "day"
    calls = AiUsage.objects.filter(feature=feature, profile__user_id=profile.user_id, created_at__gte=_day_start())
    if calls.count() >= per_user:
        return False, "user"
    return True, ""


def jobs_budget_left():
    jobs = jobs_monthly_budget() - spent_this_month(JOB_FEATURES)
    everything = monthly_budget() - spent_this_month()
    return max(0.0, min(jobs, everything))


def jobs_daily_allowance(now=None):
    """What a nightly job may spend tonight: the jobs' budget left this month spread over the days
    left (today included), so an early-month night can't use up the whole month."""
    now = timezone.localtime(now or timezone.now())
    next_month = (now.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    days_left = (next_month.date() - now.date()).days
    return jobs_budget_left() / max(1, days_left)


def record(feature, usage, model, profile=None, batch=False, usd=None):
    """Saves what a call cost (usd given: already computed, e.g. a whole batch). Returns it."""
    from .models import AiUsage

    usd = cost(usage, model, batch) if usd is None else usd
    AiUsage.objects.create(
        feature=feature, profile=profile, model_name=model, cost_usd=usd,
        input_tokens=getattr(usage, "input_tokens", 0) or 0, output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )
    if feature not in EXEMPT:
        _maybe_alert()
    return usd


def _maybe_alert():
    """One email to staff the first time the month passes 80 % of the budget."""
    from users.models import User
    from .models import AiUsage

    budget = monthly_budget()
    total = spent_this_month()
    if total < 0.8 * budget or AiUsage.objects.filter(feature=ALERT_FEATURE, created_at__gte=_month_start()).exists():
        return
    AiUsage.objects.create(feature=ALERT_FEATURE, cost_usd=0.0)
    emails = list(User.objects.filter(is_staff=True, is_active=True).exclude(email="").values_list("email", flat=True))
    if not emails:
        return
    try:
        send_mail(
            f"AI budget: US${total:.2f} of US${budget:.2f} used this month",
            f"Claude use this month has reached US${total:.2f}, {round(100 * total / budget)} % of the "
            f"US${budget:.2f} budget. At 100 % every AI feature pauses until next month; the rest of "
            f"the site keeps working. Details: the admin dashboard's AI spend card.",
            None, emails,
        )
    except Exception as exc:  # never break the feature for an email
        log.warning("AI budget alert email failed: %s", exc)
