"""
Watch history from what was already recorded, so the page isn't empty on day one:
- each day a profile pressed Play on a title (TitleAction "outbound"): the title, episode unknown
- the last movie / episode opened per title (WatchProgress), with its episode
"""
from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    TitleAction = apps.get_model("reco", "TitleAction")
    WatchProgress = apps.get_model("reco", "WatchProgress")
    WatchEvent = apps.get_model("reco", "WatchEvent")

    events = {}  # (profile, title, season, episode, day) -> when (latest)

    def add(profile_id, title_id, season, episode, when):
        key = (profile_id, title_id, season or 0, episode or 0, timezone.localtime(when).date())
        if key not in events or when > events[key]:
            events[key] = when

    for wp in WatchProgress.objects.all().values("profile_id", "title_id", "season_number", "episode_number", "updated_at").iterator():
        add(wp["profile_id"], wp["title_id"], wp["season_number"], wp["episode_number"], wp["updated_at"])
    known = {(p, t, d) for p, t, s, e, d in events}
    for a in TitleAction.objects.filter(action="outbound").values("profile_id", "title_id", "created_at").iterator():
        day = timezone.localtime(a["created_at"]).date()
        if (a["profile_id"], a["title_id"], day) not in known:  # that day's episode is already there
            add(a["profile_id"], a["title_id"], 0, 0, a["created_at"])

    WatchEvent.objects.bulk_create(
        [
            WatchEvent(profile_id=p, title_id=t, season_number=s, episode_number=e, watched_on=d, watched_at=when)
            for (p, t, s, e, d), when in events.items()
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("reco", "0016_watch_event"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
