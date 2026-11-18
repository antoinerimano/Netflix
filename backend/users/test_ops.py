"""The server's files stay in step (ops/crontab, scripts/deploy.sh): every cron job's lock is one the
deploy waits for, or a deploy would kill that job again (the weekly clean_db, 2026-11-15)."""
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


class OpsFilesTests(SimpleTestCase):
    def test_deploy_waits_for_every_cron_job(self):
        crontab = (ROOT / "ops" / "crontab").read_text(encoding="utf-8")
        deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
        cron_locks = set(re.findall(r"flock -n (/tmp/[\w.-]+\.lock)", crontab))
        deploy_locks = set(re.findall(r"(/tmp/[\w.-]+\.lock)", deploy.split("LOCKS=(", 1)[1].split(")", 1)[0]))
        self.assertTrue(cron_locks)
        self.assertEqual(cron_locks - deploy_locks, set(), "cron jobs the deploy would kill: add their lock to deploy.sh")

    def test_deploy_script_has_unix_line_endings(self):
        self.assertNotIn(b"\r", (ROOT / "scripts" / "deploy.sh").read_bytes())

    def test_every_dashboard_job_is_recorded_by_something(self):
        # a JOBS name nothing records would always look "late" (or never be watched at all)
        from .dashboard import JOBS

        tracked = set()
        for path in (ROOT / "backend").glob("*/management/commands/*.py"):
            tracked |= set(re.findall(r'@tracked\("([\w-]+)"\)', path.read_text(encoding="utf-8")))
        scripts = "\n".join(p.read_text(encoding="utf-8") for p in
                            [ROOT / "scripts" / "backup_db.sh", ROOT / "ops" / "weekly-cleanup.sh"])
        recorded = set(re.findall(r"record_job ([\w-]+)", scripts))
        self.assertEqual({"backup_db", "weekly_cleanup"}, recorded)
        missing = {name for name, _label, _late in JOBS} - tracked - recorded
        self.assertEqual(missing, set(), "dashboard jobs nothing records: @tracked or record_job")

    def test_deploy_warns_when_a_server_file_is_not_the_one_in_ops(self):
        deploy = (ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
        for path in sorted((ROOT / "ops").iterdir()):
            if path.name != "README.md":
                self.assertIn(f"installed_differs ops/{path.name} ", deploy, f"ops/{path.name}: check it in deploy.sh")

    def test_server_scripts_have_unix_line_endings(self):
        for path in ("scripts/backup_db.sh", "ops/weekly-cleanup.sh", "ops/crontab", "ops/logrotate-taurus"):
            self.assertNotIn(b"\r", (ROOT / path).read_bytes(), path)
