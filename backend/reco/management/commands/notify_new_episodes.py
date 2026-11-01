# reco/management/commands/notify_new_episodes.py
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from reco.models import Notification, ShowFollow
from django.utils.translation import gettext, ngettext

from users.emails import send_templated_email
from users.i18n import language_of, to_app_language
from users.localize import title_names
from users.models import Episode
from users.jobs import tracked

LOOKBACK_DAYS = 3  # catches episodes even if a run was missed


class Command(BaseCommand):
    help = (
        "Create 'new episode' notifications for profiles following a show, then email each account "
        "once with its new episodes. Run it right after sync_tmdb_daily_episodes."
    )

    def add_arguments(self, parser):
        parser.add_argument("--no-email", action="store_true", help="Only create the in-app notifications.")

    @tracked("notify_new_episodes")  # JobRun: shown on the admin dashboard
    def handle(self, *args, **opts):
        today = timezone.localdate()
        follows = list(ShowFollow.objects.values_list("profile_id", "title_id", "created_at"))
        if not follows:
            self.stdout.write("Nobody follows a show.")
            return

        episodes = defaultdict(list)  # show id -> [(season, episode, air_date)]
        for show_id, season, episode, air_date in (
            Episode.objects
            .filter(
                season__tv_id__in={title_id for _, title_id, _ in follows},
                air_date__gte=today - timedelta(days=LOOKBACK_DAYS),
                air_date__lte=today,
                season__season_number__gt=0,  # not specials
            )
            .values_list("season__tv_id", "season__season_number", "episode_number", "air_date")
        ):
            episodes[show_id].append((season, episode, air_date))

        to_create = [
            Notification(profile_id=profile_id, title_id=title_id,
                         season_number=season, episode_number=episode, air_date=air_date)
            for profile_id, title_id, followed_at in follows
            for season, episode, air_date in episodes.get(title_id, [])
            if air_date >= timezone.localtime(followed_at).date()  # only episodes since the follow, no backlog
        ]
        before = Notification.objects.count()
        Notification.objects.bulk_create(to_create, ignore_conflicts=True)  # already notified: skipped
        self.stdout.write(f"{Notification.objects.count() - before} new notifications.")

        if not opts["no_email"]:
            self._send_emails()

    def _send_emails(self):
        pending = list(
            Notification.objects
            .filter(emailed_at__isnull=True, created_at__gte=timezone.now() - timedelta(days=LOOKBACK_DAYS))
            .select_related("profile__user", "title")
            .order_by("title__title", "season_number", "episode_number")
        )
        by_user = defaultdict(list)
        for n in pending:
            by_user[n.profile.user].append(n)

        sent = 0
        for user, notes in by_user.items():
            if user.email and user.is_active:
                # the account's email in the language of the profile that follows these shows
                lang = to_app_language(notes[0].profile.language_preference, "en")
                names = title_names([n.title_id for n in notes], lang)
                episodes = []
                seen = set()  # two profiles of one account following the same show: list it once
                for n in notes:
                    key = (n.title_id, n.season_number, n.episode_number)
                    if key in seen:
                        continue
                    seen.add(key)
                    episodes.append({
                        "show": names.get(n.title_id) or n.title.title,
                        "season": n.season_number,
                        "episode": n.episode_number,
                        "link": f"{settings.FRONTEND_URL.rstrip('/')}/watch/{n.title_id}"
                                f"?season={n.season_number}&episode={n.episode_number}",
                    })
                with language_of(lang):
                    if len(episodes) == 1:
                        subject = gettext("New episode of %(show)s") % {"show": episodes[0]["show"]}
                    else:
                        subject = ngettext(
                            "%(count)d new episode of shows you follow",
                            "%(count)d new episodes of shows you follow",
                            len(episodes),
                        ) % {"count": len(episodes)}
                try:
                    send_templated_email(subject, "new_episodes", {"user": user, "episodes": episodes}, [user.email], language=lang)
                    sent += 1
                except Exception as exc:  # keep going; these stay pending for the next run
                    self.stderr.write(f"email to {user.email} failed: {exc}")
                    continue
            Notification.objects.filter(id__in=[n.id for n in notes]).update(emailed_at=timezone.now())
        self.stdout.write(f"{sent} emails sent.")
