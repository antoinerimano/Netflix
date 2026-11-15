# reco/experiments.py
"""
A/B tests (roadmap 8.7): to know whether an AI feature helps, half the profiles keep the old way
for a few weeks and the two halves are compared (reco/ai_report.py, the dashboard's "Does the AI
help?" card).

  arm(name, profile) -> "ai" | "control"
A profile always lands in the same half (a hash of the test's name and the profile's id: no
table, nothing to clean up). After the test's end date (settings.AI_EXPERIMENTS, backend/.env)
everyone gets "ai", the feature as built.

Running now:
  pick_moods   "What to watch?" moods: AI tags (reco/tags.py) vs genres alone (before 7.10)
"""
import datetime as dt
import hashlib

from django.conf import settings
from django.utils import timezone

AI, CONTROL = "ai", "control"


def end_date(name):
    raw = (getattr(settings, "AI_EXPERIMENTS", {}) or {}).get(name)
    return dt.date.fromisoformat(raw) if raw else None


def running(name, today=None):
    end = end_date(name)
    return bool(end and (today or timezone.localdate()) < end)


def arm(name, profile, today=None):
    """"ai" or "control" for this profile in this test; "ai" for everyone once it's over."""
    if profile is None or not running(name, today):
        return AI
    digest = hashlib.sha1(f"{name}:{profile.id}".encode()).digest()
    return CONTROL if digest[0] % 2 else AI
