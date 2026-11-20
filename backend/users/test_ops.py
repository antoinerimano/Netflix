"""The server's files stay in step (ops/crontab, scripts/deploy.sh): every cron job's lock is one the
deploy waits for, or a deploy would kill that job again (the weekly clean_db, 2026-11-15)."""
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


class OpsFilesTests(SimpleTestCase):
    def test_deploy_waits_for_every_cron_job(self):
        crontab = (ROOT / "ops" / "crontab").read_text(encoding="utf-8")
        job_locks = (ROOT / "scripts" / "job_locks.sh").read_text(encoding="utf-8")
        cron_locks = set(re.findall(r"flock -n (/tmp/[\w.-]+\.lock)", crontab))
        deploy_locks = set(re.findall(r"(/tmp/[\w.-]+\.lock)", job_locks.split("LOCKS=(", 1)[1].split(")", 1)[0]))
        self.assertTrue(cron_locks)
        self.assertEqual(cron_locks - deploy_locks, set(), "cron jobs the deploy would kill: add their lock to scripts/job_locks.sh")
        # the deploy and the weekly reboot both take them
        for script in ("deploy.sh", "reboot_if_needed.sh"):
            text = (ROOT / "scripts" / script).read_text(encoding="utf-8")
            self.assertIn("job_locks.sh", text, script)
            self.assertIn("take_job_locks", text, script)

    def test_deploy_script_has_unix_line_endings(self):
        self.assertNotIn(b"\r", (ROOT / "scripts" / "deploy.sh").read_bytes())

    def test_every_dashboard_job_is_recorded_by_something(self):
        # a JOBS name nothing records would always look "late" (or never be watched at all)
        from .dashboard import JOBS

        tracked = set()
        for path in (ROOT / "backend").glob("*/management/commands/*.py"):
            tracked |= set(re.findall(r'@tracked\("([\w-]+)"\)', path.read_text(encoding="utf-8")))
        scripts = "\n".join(p.read_text(encoding="utf-8") for p in
                            [ROOT / "scripts" / "backup_db.sh", ROOT / "scripts" / "test_backup_restore.sh",
                             ROOT / "ops" / "weekly-cleanup.sh"])
        recorded = set(re.findall(r"record_job ([\w-]+)", scripts))
        self.assertEqual({"backup_db", "backup_restore_test", "weekly_cleanup"}, recorded)
        missing = {name for name, _label, _late in JOBS} - tracked - recorded
        self.assertEqual(missing, set(), "dashboard jobs nothing records: @tracked or record_job")

    def test_deploy_installs_every_server_file_in_ops(self):
        deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
        for path in sorted((ROOT / "ops").iterdir()):
            if path.name != "README.md":
                self.assertIn(f"install_ops_file ops/{path.name} ", deploy, f"ops/{path.name}: install it in deploy.sh")

    def test_server_scripts_have_unix_line_endings(self):
        for path in ("scripts/backup_db.sh", "scripts/test_backup_restore.sh", "ops/weekly-cleanup.sh", "ops/crontab",
                     "ops/logrotate-taurus", "scripts/job_locks.sh", "scripts/hc_ping.sh", "scripts/heartbeat.sh",
                     "scripts/reboot_if_needed.sh"):
            self.assertNotIn(b"\r", (ROOT / path).read_bytes(), path)

    def test_every_dashboard_job_says_when_and_what(self):
        from .dashboard import JOB_GROUPS, JOB_INFO, JOBS

        for name, _label, _late in JOBS:
            self.assertIn(name, JOB_INFO, f"{name}: add it to dashboard.JOB_INFO (group, when, what)")
            group, when, what = JOB_INFO[name]
            self.assertIn(group, JOB_GROUPS)
            self.assertTrue(when and what, name)

    def test_every_script_cron_runs_exists(self):
        crontab = (ROOT / "ops" / "crontab").read_text(encoding="utf-8")
        for script in set(re.findall(r"(?:/opt/taurus/|\s)(scripts/[\w.-]+\.sh)", crontab)):
            self.assertTrue((ROOT / script).exists(), script)


class HealthTests(SimpleTestCase):
    databases = {"default"}

    def test_ok_without_login(self):
        r = self.client.get("/api/health/")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True}))
        self.assertIn("no-cache", r.headers.get("Cache-Control", ""))

    def test_database_down(self):
        from unittest import mock
        with mock.patch("users.health.connection.cursor", side_effect=Exception("gone")):
            r = self.client.get("/api/health/")
        self.assertEqual((r.status_code, r.json()), (503, {"ok": False}))
