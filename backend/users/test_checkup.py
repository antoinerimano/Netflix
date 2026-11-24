"""The daily check-up (users/checkup.py, manage.py daily_checkup): every problem it looks for, no
email and no AI when all is well, the AI summary within the jobs' budget, and the email without it
when the AI can't be used. A fake Claude client: nothing is sent to the real API."""
from collections import namedtuple
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace as NS
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from reco.models import AiUsage, RecoHomeSnapshot, TagBatch

from . import checkup, dashboard
from .dashboard import JOBS
from .models import JobRun, Profile, Title, User

Disk = namedtuple("Disk", "total used free")
REAL_CERT_DAYS_LEFT = checkup.cert_days_left  # setUp mocks it


def reply(text="Home pages failed: run cron_build_home.sh.", stop_reason="end_turn"):
    return NS(stop_reason=stop_reason, content=[NS(type="text", text=text)],
              usage=NS(input_tokens=2000, output_tokens=300))


class CheckupTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("admin@example.com", "Admin", "pw-admin-123!", is_staff=True)
        User.objects.create_user("member@example.com", "Member", "pw-member-123!")  # not staff: no email
        # every scheduled job ran fine just now: a healthy site
        # (a minute ago: a run a test creates afterwards is the newer one, never a tie)
        for name, _label, late_after in JOBS:
            if late_after:
                JobRun.objects.create(name=name, ok=True, finished_at=timezone.now(), summary="done")
        JobRun.objects.update(started_at=timezone.now() - timedelta(minutes=1))
        self.claude = mock.MagicMock()
        self.claude.messages.create.return_value = reply()
        patcher = mock.patch("users.checkup._client", return_value=self.claude)
        patcher.start()
        self.addCleanup(patcher.stop)
        disk = mock.patch("users.checkup.shutil.disk_usage", return_value=Disk(100e9, 50e9, 50e9))
        disk.start()
        self.addCleanup(disk.stop)
        cert = mock.patch("users.checkup.cert_days_left", return_value=60)  # never the network
        cert.start()
        self.addCleanup(cert.stop)
        config = mock.patch("users.config_check.config_problems", return_value=[])  # tested in test_config_check
        config.start()
        self.addCleanup(config.stop)

    def run_cmd(self, *args):
        out = StringIO()
        call_command("daily_checkup", *args, stdout=out)
        return out.getvalue()

    def kinds(self):
        return [p["kind"] for p in checkup.find_problems()]

    # ---- nothing wrong ----
    def test_all_ok_no_email_no_ai(self):
        before = JobRun.objects.filter(name="daily_checkup", ok=True).count()
        self.assertIn("All OK", self.run_cmd())
        self.assertEqual(mail.outbox, [])
        self.claude.messages.create.assert_not_called()
        self.assertEqual(JobRun.objects.filter(name="daily_checkup", ok=True).count(), before + 1)  # on the dashboard

    # ---- what it finds ----
    def test_failed_job_with_its_error_and_fix(self):
        JobRun.objects.create(name="build_home_snapshots", ok=False, error="OperationalError: MySQL gone away")
        [p] = checkup.find_problems()
        self.assertEqual(p["kind"], "job_failed")
        self.assertIn("MySQL gone away", p["detail"])
        self.assertEqual(p["fix"], "/opt/taurus/scripts/cron_build_home.sh")

    def test_late_and_never_ran(self):
        JobRun.objects.filter(name="notify_new_episodes").update(started_at=timezone.now() - timedelta(days=2))
        JobRun.objects.filter(name="tag_titles").delete()
        problems = {p["kind"] + ":" + p["what"].split("(")[1].split(")")[0] for p in checkup.find_problems()}
        self.assertEqual(problems, {"job_late:notify_new_episodes", "job_late:tag_titles"})

    def test_stuck_job(self):
        JobRun.objects.filter(name="sync_tmdb_daily_episodes").delete()  # its last run is the stuck one
        stuck = JobRun.objects.create(name="sync_tmdb_daily_episodes", ok=None)
        JobRun.objects.filter(id=stuck.id).update(started_at=timezone.now() - timedelta(hours=7))
        self.assertEqual(self.kinds(), ["job_stuck"])
        JobRun.objects.filter(id=stuck.id).update(started_at=timezone.now() - timedelta(minutes=20))
        self.assertEqual(self.kinds(), [])  # just running

    def test_home_pages(self):
        p = Profile.objects.create(user=self.admin, name="A", age_restriction="NC-17", language_preference="en")
        snap, _ = RecoHomeSnapshot.objects.get_or_create(profile=p, defaults={"payload": {}, "expires_at": timezone.now()})
        self.assertEqual(self.kinds(), [])  # built fine
        RecoHomeSnapshot.objects.filter(id=snap.id).update(last_error="KeyError: rows")
        self.assertEqual(self.kinds(), ["snapshots_failed"])
        RecoHomeSnapshot.objects.filter(id=snap.id).update(last_error="", built_at=timezone.now() - timedelta(hours=13))
        self.assertEqual(self.kinds(), ["snapshots_stale"])

    def test_tag_batch_not_collected(self):
        b = TagBatch.objects.create(batch_id="msgbatch_slow", model_name="claude-haiku-5-5", hashes={})
        self.assertEqual(self.kinds(), [])  # sent recently: fine
        TagBatch.objects.filter(id=b.id).update(created_at=timezone.now() - timedelta(hours=27))
        [p] = checkup.find_problems()
        self.assertEqual((p["kind"], p["detail"]), ("tag_batch_late", "msgbatch_slow"))

    def test_disk(self):
        with mock.patch("users.checkup.shutil.disk_usage", return_value=Disk(100e9, 96e9, 4e9)):
            [p] = checkup.find_problems()
        self.assertEqual(p["kind"], "disk")
        self.assertIn("4.0 GB free", p["what"])

    def test_backup_and_mini_pc_like_the_other_jobs(self):
        # shell scripts (record_job) and the mini PC's imports are jobs too: failed or late
        call_command("record_job", "backup_db", "--failed", "--summary", "ERROR: mysqldump failed (exit 1)",
                     stdout=StringIO())
        JobRun.objects.filter(name="trailer_worker").update(started_at=timezone.now() - timedelta(hours=31))
        problems = {p["kind"]: p for p in checkup.find_problems()}
        self.assertEqual(set(problems), {"job_failed", "job_late"})
        self.assertIn("mysqldump failed", problems["job_failed"]["detail"])
        self.assertEqual(problems["job_failed"]["fix"], checkup.FIX_COMMANDS["backup_db"])
        self.assertIn("mini PC", problems["job_late"]["fix"])

    def test_record_job(self):
        call_command("record_job", "weekly_cleanup", "--summary", "12G free (60% used)", stdout=StringIO())
        run = JobRun.objects.filter(name="weekly_cleanup").latest("started_at")
        self.assertEqual((run.ok, run.summary, run.error), (True, "12G free (60% used)", ""))
        self.assertIsNotNone(run.finished_at)

    def test_record_job_start_progress_end(self):
        # the mini PC's trailer worker runs ~21 h: running on the dashboard, its progress, then the end
        JobRun.objects.filter(name="trailer_worker").delete()
        call_command("record_job", "trailer_worker", "--start", stdout=StringIO())
        call_command("record_job", "trailer_worker", "--progress", "--summary", "954 clips made since 01:00",
                     stdout=StringIO())
        [run] = JobRun.objects.filter(name="trailer_worker")
        self.assertEqual((run.ok, run.finished_at, run.summary), (None, None, "954 clips made since 01:00"))
        [job] = [j for j in dashboard._jobs(timezone.now()) if j["name"] == "trailer_worker"]
        self.assertEqual((job["state"], job["result"]), ("running", "954 clips made since 01:00"))
        # running 20 h is normal for this one (not for the others: test_stuck_job)
        JobRun.objects.filter(id=run.id).update(started_at=timezone.now() - timedelta(hours=20))
        self.assertEqual(self.kinds(), [])
        JobRun.objects.filter(id=run.id).update(started_at=timezone.now() - timedelta(hours=24))
        self.assertEqual(self.kinds(), ["job_stuck"])

        call_command("record_job", "trailer_worker", "--failed", "--summary", "Couldn't give the results",
                     stdout=StringIO())
        [run] = JobRun.objects.filter(name="trailer_worker")  # the same run, closed
        self.assertEqual((run.ok, run.error), (False, "Couldn't give the results"))
        self.assertIsNotNone(run.finished_at)
        # progress without a --start (the server was down then): a running run all the same
        call_command("record_job", "trailer_worker", "--progress", "--summary", "12 clips", stdout=StringIO())
        self.assertEqual(JobRun.objects.filter(name="trailer_worker", ok=None).count(), 1)

    def test_https_certificate(self):
        with mock.patch("users.checkup.cert_days_left", return_value=20):
            self.assertEqual(self.kinds(), [])  # certbot renews at 30: not yet worrying
        with mock.patch("users.checkup.cert_days_left", return_value=9):
            [p] = checkup.find_problems()
        self.assertEqual(p["kind"], "cert")
        self.assertIn("9 days", p["what"])
        with mock.patch("users.checkup.cert_days_left", return_value=None):
            self.assertEqual(self.kinds(), [])  # can't read it: nothing said

    def test_cert_days_left_skips_local_sites(self):
        with mock.patch("users.checkup.socket.create_connection") as connect:
            for url in ("http://example.com", "https://localhost:8000", "https://127.0.0.1", ""):
                self.assertIsNone(REAL_CERT_DAYS_LEFT(url))
        connect.assert_not_called()

    def test_ai_budget(self):
        AiUsage.objects.create(feature="recap", cost_usd=4.1)
        self.assertEqual(self.kinds(), ["ai_budget"])

    # ---- the email ----
    def test_email_with_the_ai_summary(self):
        JobRun.objects.create(name="build_home_snapshots", ok=False, error="KeyError: rows")
        out = self.run_cmd()
        self.assertIn("with the AI summary", out)
        [email] = mail.outbox
        self.assertEqual(email.to, ["admin@example.com"])  # staff only
        self.assertEqual(email.subject, "Check-up: 1 problem on the site")
        self.assertIn("Home pages failed: run cron_build_home.sh.", email.body)
        self.assertIn("The facts:", email.body)
        self.assertIn("KeyError: rows", email.body)
        self.assertIn("/dashboard/", email.body)
        # Claude is given the facts and the only commands it may suggest
        sent = self.claude.messages.create.call_args.kwargs
        self.assertEqual(sent["model"], checkup.MODEL)
        self.assertIn("Never invent", sent["system"])
        prompt = sent["messages"][0]["content"]
        self.assertIn("KeyError: rows", prompt)
        self.assertIn("/opt/taurus/scripts/cron_build_home.sh", prompt)
        # paid from the background jobs' budget
        usage = AiUsage.objects.get(feature="checkup")
        self.assertAlmostEqual(usage.cost_usd, (2000 * 0.10 + 300 * 0.50) / 1e6)

    def test_email_without_ai_when_the_budget_is_used_up(self):
        AiUsage.objects.create(feature="tags", cost_usd=1.0)  # the jobs' US$1 this month
        JobRun.objects.create(name="tag_titles", ok=False, error="AuthenticationError")
        self.assertIn("facts only", self.run_cmd())
        self.claude.messages.create.assert_not_called()
        [email] = mail.outbox
        self.assertIn("AuthenticationError", email.body)
        self.assertNotIn("The facts:", email.body)

    def test_email_without_ai_when_claude_fails(self):
        import anthropic

        self.claude.messages.create.side_effect = anthropic.APIConnectionError(request=mock.MagicMock())
        JobRun.objects.create(name="tag_titles", ok=False, error="boom")
        self.run_cmd()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("boom", mail.outbox[0].body)
        self.assertFalse(AiUsage.objects.filter(feature="checkup").exists())

    def test_refusal_is_billed_but_not_used(self):
        self.claude.messages.create.return_value = reply("", stop_reason="refusal")
        JobRun.objects.create(name="tag_titles", ok=False, error="boom")
        self.assertIn("facts only", self.run_cmd())
        self.assertTrue(AiUsage.objects.filter(feature="checkup").exists())

    def test_dry_run_and_no_ai(self):
        JobRun.objects.create(name="tag_titles", ok=False, error="boom")
        self.assertIn("1 problem(s)", self.run_cmd("--dry-run"))
        self.assertEqual(mail.outbox, [])
        self.run_cmd("--no-ai")
        self.assertEqual(len(mail.outbox), 1)
        self.claude.messages.create.assert_not_called()

    def test_several_problems_most_listed(self):
        JobRun.objects.create(name="tag_titles", ok=False, error="boom")
        AiUsage.objects.create(feature="recap", cost_usd=4.5)
        self.run_cmd("--no-ai")
        self.assertEqual(mail.outbox[0].subject, "Check-up: 2 problems on the site")

    def test_old_failure_not_repeated(self):
        """A failure is reported the morning after, not every day until the job runs again (a
        weekly job killed by a deploy alerted for a week, 2026-11-15)."""
        run = JobRun.objects.create(name="clean_db", ok=False, error="killed by a deploy")
        JobRun.objects.filter(id=run.id).update(finished_at=timezone.now() - timedelta(hours=10))
        self.assertEqual(self.kinds(), ["job_failed"])  # this morning: reported
        JobRun.objects.filter(id=run.id).update(finished_at=timezone.now() - timedelta(hours=30))
        self.assertEqual(self.kinds(), [])  # tomorrow: not again


    # ---- trailer preview clips ----
    def clip_title(self, tmdb_id, clip, kind="movie", trailer_key="AAAAAAAAAAA"):
        return Title.objects.create(type=kind, tmdb_id=tmdb_id, title=f"T{tmdb_id}", trailer_clip_url=clip,
                                    trailer_url=f"https://www.youtube.com/watch?v={trailer_key}" if trailer_key else "")

    def test_preview_clip_counts(self):
        cdn = "https://cdn.example.com"
        self.clip_title(1, f"{cdn}/previews/movie/1-AAAAAAAAAAA.mp4")             # right
        self.clip_title(2, f"{cdn}/trailers/2.mp4")                              # old format
        self.clip_title(3, f"{cdn}/previews/movie/3-BBBBBBBBBBB.mp4")             # an older trailer's
        self.clip_title(4, f"{cdn}/previews/movie/4-AAAAAAAAAAA.mp4", kind="tv")  # the movie's folder
        self.clip_title(5, f"{cdn}/previews/movie/5-AAAAAAAAAAA.mp4", trailer_key="")  # trailer gone
        self.clip_title(6, "")                                                   # no clip: not counted
        self.assertEqual(checkup.preview_clip_counts(), {"legacy": 1, "mismatch": 3})

    def test_preview_clips_reported_when_a_count_goes_up(self):
        self.assertIn("Preview clips: 0 old-format, 0 not their trailer's clip", self.run_cmd())
        self.assertEqual(mail.outbox, [])
        self.clip_title(2, "https://cdn.example.com/trailers/2.mp4")
        [p] = checkup.find_problems()
        self.assertEqual(p["kind"], "preview_clips")
        self.assertIn("1 old-format (was 0)", p["what"])
        self.assertIn("export_trailer_jobs", p["fix"])
        self.run_cmd("--dry-run")  # a dry run is not the baseline: still to report
        self.assertEqual(self.kinds(), ["preview_clips"])
        self.run_cmd("--no-ai")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("1 old-format (was 0)", mail.outbox[0].body)
        self.assertEqual(self.kinds(), [])  # the same backlog the next morning: no email
        self.clip_title(3, "https://cdn.example.com/previews/movie/3-BBBBBBBBBBB.mp4")
        self.assertIn("1 not the clip of the title's trailer (was 0)", checkup.find_problems()[0]["what"])
        self.run_cmd("--no-ai")
        Title.objects.filter(tmdb_id=3).delete()
        self.assertEqual(self.kinds(), [])  # going down: nothing to say


class EveryTests(TestCase):
    def test_words(self):
        self.assertEqual(checkup.every(timedelta(hours=1)), "hour")
        self.assertEqual(checkup.every(timedelta(hours=8)), "8 hours")
        self.assertEqual(checkup.every(timedelta(hours=30)), "30 hours")
        self.assertEqual(checkup.every(timedelta(days=1)), "day")
        self.assertEqual(checkup.every(timedelta(days=35)), "35 days")

