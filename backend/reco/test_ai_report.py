"""Does the AI help? (roadmap 8.7): the A/B groups (reco/experiments.py), "What to watch?" in each
group (reco/pick.py), and the report (reco/ai_report.py): shown -> clicked -> played, the time
windows, the verdicts, the statistics."""
import datetime as dt
from datetime import timedelta
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from users.models import Profile, Title, User

from . import ai_report, experiments
from .models import TitleAction, TitleImpression, TitleTags, WatchEvent

RUNNING = {"pick_moods": "2099-01-01"}


@override_settings(AI_EXPERIMENTS=RUNNING)
class ExperimentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a@example.com", "A", "pw-a-123456!")

    def test_half_and_half_and_always_the_same(self):
        profiles = [Profile.objects.create(user=self.user, name=f"P{i}", age_restriction="NC-17",
                                           language_preference="en") for i in range(200)]
        arms = [experiments.arm("pick_moods", p) for p in profiles]
        self.assertTrue(70 < arms.count("ai") < 130, arms.count("ai"))  # about half
        self.assertEqual(arms, [experiments.arm("pick_moods", p) for p in profiles])  # stable

    def test_everyone_gets_the_ai_once_over_or_off(self):
        profiles = [Profile.objects.create(user=self.user, name=f"P{i}", age_restriction="NC-17",
                                           language_preference="en") for i in range(20)]
        after = dt.date(2099, 1, 2)
        self.assertEqual({experiments.arm("pick_moods", p, today=after) for p in profiles}, {"ai"})
        with override_settings(AI_EXPERIMENTS={"pick_moods": ""}):
            self.assertEqual({experiments.arm("pick_moods", p) for p in profiles}, {"ai"})
        self.assertEqual(experiments.arm("unknown_test", profiles[0]), "ai")


@override_settings(AI_EXPERIMENTS=RUNNING)
class PickGroupsTests(TestCase):
    """The control half gets moods from genres alone (before 7.10), the other half the AI tags."""

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.user = User.objects.create_user("a@example.com", "A", "pw-a-123456!")
        self.api.force_authenticate(self.user)
        self.profiles = {}
        i = 0
        while len(self.profiles) < 2:  # one profile in each half
            p = Profile.objects.create(user=self.user, name=f"P{i}", age_restriction="NC-17", language_preference="en")
            self.profiles.setdefault(experiments.arm("pick_moods", p), p)
            i += 1

        def movie(name, genre):
            return Title.objects.create(type="movie", title=name, genre=genre, runtime_minutes=90, vote_count=5000,
                                        vote_average=7.5, poster="p.jpg", maturity=2, popularity=50,
                                        release_date="2000-01-01")

        TitleTags.objects.create(title=movie("Grim Comedy", "Comedy, Drama"), moods=",dark,sad,")
        TitleTags.objects.create(title=movie("Funny Drama", "Drama"), moods=",funny,")

    def funny(self, arm):
        r = self.api.get("/api/pick/", {"profileId": self.profiles[arm].id, "time": "any", "mood": "funny", "count": 12})
        self.assertEqual(r.status_code, 200)
        return r.data["arm"], {i["title"] for i in r.data["items"]}

    def test_each_half(self):
        self.assertEqual(self.funny("ai"), ("ai", {"Funny Drama"}))
        self.assertEqual(self.funny("control"), ("control", {"Grim Comedy"}))  # by genre, as before


class ReportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("a@example.com", "A", "pw-a-123456!")
        self.profile = Profile.objects.create(user=self.user, name="A", age_restriction="NC-17", language_preference="en")
        self.now = timezone.now()
        self.titles = [Title.objects.create(type="movie", title=f"T{i}") for i in range(4)]

    def shown(self, title, row_type, hours_ago):
        imp = TitleImpression.objects.create(profile=self.profile, title=title, row_type=row_type, session_id="s")
        TitleImpression.objects.filter(id=imp.id).update(created_at=self.now - timedelta(hours=hours_ago))

    def click(self, title, surface, hours_ago):
        a = TitleAction.objects.create(profile=self.profile, title=title, action="click", session_id="s",
                                       provider=f"row:x|pos:0|surface:{surface}")
        TitleAction.objects.filter(id=a.id).update(created_at=self.now - timedelta(hours=hours_ago))

    def play(self, title, hours_ago):
        at = self.now - timedelta(hours=hours_ago)
        WatchEvent.objects.create(profile=self.profile, title=title, watched_on=at.date(), watched_at=at)

    def group(self, key, group):
        comparison = next(c for c in ai_report.report(now=self.now) if c["key"] == key)
        return next(g for g in comparison["groups"] if g["group"] == group)

    def test_shown_clicked_played_with_their_windows(self):
        t0, t1, t2, t3 = self.titles
        for t in self.titles:
            self.shown(t, "pick:ai", hours_ago=60)
        self.shown(t0, "pick:ai", hours_ago=50)  # shown twice: counted once, from the first time
        self.click(t0, "pick", hours_ago=59)       # within 24 h
        self.play(t0, hours_ago=58)                # within 48 h
        self.click(t1, "pick", hours_ago=10)       # 50 h later: too late
        self.play(t2, hours_ago=70)                # before it was shown: not because of it
        self.click(t3, "home_row", hours_ago=59)   # clicked somewhere else
        g = self.group("pick_moods", "ai")
        self.assertEqual((g["shown"], g["clicked"], g["played"]), (4, 1, 1))
        self.assertEqual(g["play_rate"], 0.25)
        self.assertEqual(self.group("pick_moods", "control")["shown"], 0)

    def test_more_like_this_by_source(self):
        t0, t1, *_ = self.titles
        self.shown(t0, "more_like_this:tmdb", hours_ago=5)
        self.shown(t1, "more_like_this:embeddings", hours_ago=5)
        self.click(t0, "more_like_this", hours_ago=4)
        self.assertEqual(self.group("more_like_this", "tmdb")["clicked"], 1)
        self.assertEqual(self.group("more_like_this", "embeddings")["clicked"], 0)

    def test_old_data_left_out(self):
        self.shown(self.titles[0], "pick:ai", hours_ago=24 * 30)
        self.assertEqual(self.group("pick_moods", "ai")["shown"], 0)

    def test_verdicts(self):
        few = {"shown": 50, "played": 20}
        self.assertEqual(ai_report.verdict([("A", few), ("B", few)], "played")[0], "Not enough data yet")
        a, b = {"shown": 1000, "played": 120}, {"shown": 1000, "played": 60}
        text, p = ai_report.verdict([("AI tags", a), ("Genres only", b)], "played")
        self.assertTrue(text.startswith("AI tags does better than Genres only (12.0% vs 6.0%"), text)
        self.assertLess(p, 0.001)
        text, p = ai_report.verdict([("A", {"shown": 1000, "played": 61}), ("B", {"shown": 1000, "played": 60})], "played")
        self.assertTrue(text.startswith("No clear difference yet"), text)
        self.assertGreater(p, 0.5)

    def test_p_value(self):
        # 12 % vs 6 % of 1000: pooled 9 %, se = sqrt(.09 * .91 * 2 / 1000) = .0128, z = .06 / .0128 = 4.69
        self.assertAlmostEqual(ai_report.p_value(120, 1000, 60, 1000), 2.76e-6, places=8)
        # 52 % vs 48 % of 200: z = 0.8, p = 0.42 (a textbook value)
        self.assertAlmostEqual(ai_report.p_value(104, 200, 96, 200), 0.4237, places=3)
        self.assertEqual(ai_report.p_value(0, 0, 1, 10), 1.0)
        self.assertEqual(ai_report.p_value(0, 10, 0, 10), 1.0)

    def test_command_and_dashboard(self):
        self.shown(self.titles[0], "pick:ai", hours_ago=5)
        out = StringIO()
        call_command("ai_report", stdout=out)
        self.assertIn('"What to watch?" moods', out.getvalue())
        self.assertIn("Not enough data yet", out.getvalue())
        from django.conf import settings
        admin = User.objects.create_superuser("admin@example.com", "Admin", "pw-admin-123!")
        self.client.force_login(admin)
        html = self.client.get("/" + settings.ADMINADMIN_URL.strip("/") + "/dashboard/").content.decode()
        self.assertIn("Does the AI help?", html)
        self.assertIn("TMDB recommendations", html)
