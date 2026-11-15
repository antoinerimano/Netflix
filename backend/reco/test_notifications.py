"""New episode notifications (manage.py notify_new_episodes): the bell for every show a profile
tracks (followed, in My List, watched in the last 6 months), emails only for followed shows."""
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from users.models import Episode, Profile, Season, Title, User

from .models import MyListItem, Notification, ShowFollow, WatchProgress


class NotifyNewEpisodesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice@example.com", "Alice", "pw-alice-123!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="en")
        self.today = timezone.localdate()

        def show(name, days_ago=0):
            t = Title.objects.create(type="tv", title=name)
            season = Season.objects.create(tv=t, season_number=1)
            Episode.objects.create(season=season, episode_number=1, name="Old", air_date=self.today - timedelta(days=30))
            Episode.objects.create(season=season, episode_number=2, name="New", air_date=self.today - timedelta(days=days_ago))
            return t

        self.followed = show("Followed")
        self.listed = show("In My List")
        self.watching = show("Watching")
        self.stale = show("Watched long ago")
        self.untracked = show("Untracked")
        ShowFollow.objects.create(profile=self.profile, title=self.followed)
        MyListItem.objects.create(profile=self.profile, title=self.listed)
        WatchProgress.objects.create(profile=self.profile, title=self.watching, season_number=1, episode_number=1)
        old = WatchProgress.objects.create(profile=self.profile, title=self.stale, season_number=1, episode_number=1)
        WatchProgress.objects.filter(id=old.id).update(updated_at=timezone.now() - timedelta(days=200))

    def run_cmd(self):
        call_command("notify_new_episodes", stdout=StringIO())

    def test_bell_for_every_tracked_show(self):
        self.run_cmd()
        names = set(Notification.objects.values_list("title__title", flat=True))
        self.assertEqual(names, {"Followed", "In My List", "Watching"})
        # only the new episode, not last month's
        self.assertEqual(set(Notification.objects.values_list("episode_number", flat=True)), {2})

    def test_email_only_for_followed_shows(self):
        self.run_cmd()
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertIn("Followed", body)
        self.assertNotIn("In My List", body)
        self.assertNotIn("Watching", body)
        self.assertIsNotNone(Notification.objects.get(title=self.followed).emailed_at)
        self.assertIsNone(Notification.objects.get(title=self.listed).emailed_at)

        self.run_cmd()  # again: nothing new, no second email
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(Notification.objects.count(), 3)

    def test_followed_show_no_backlog(self):
        # followed today: an episode from 2 days ago (inside the lookback) is not "new" for it
        late = Title.objects.create(type="tv", title="Followed late")
        season = Season.objects.create(tv=late, season_number=1)
        Episode.objects.create(season=season, episode_number=1, air_date=self.today - timedelta(days=2))
        ShowFollow.objects.create(profile=self.profile, title=late)
        self.run_cmd()
        self.assertFalse(Notification.objects.filter(title=late).exists())

    def test_nobody_tracks(self):
        ShowFollow.objects.all().delete()
        MyListItem.objects.all().delete()
        WatchProgress.objects.all().delete()
        out = StringIO()
        call_command("notify_new_episodes", stdout=out)
        self.assertIn("Nobody tracks a show", out.getvalue())
