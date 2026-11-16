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
