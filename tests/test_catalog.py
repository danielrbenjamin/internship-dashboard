
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from backend.catalog import canonical_url, import_jobs, public_job
from backend.db import Database

POSTING = {
    "posted_on": datetime.now(UTC).date().isoformat(),
    "title": "Mechanical Engineering Intern",
    "company": "Example Robotics",
    "location": "Vancouver, Canada",
    "url": "https://example.com/jobs/17?tracking=test",
    "requisition": "17",
    "description": "Summer 2027. Must be returning to school.",
}


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = Database(Path(self.directory.name) / "catalog.sqlite")
        self.db.execute("INSERT INTO sources(id,config) VALUES (?,?)", ("official", "{}"))
        self.db.execute("INSERT INTO owner_settings VALUES (?,?)", ("owner", json.dumps({
            "watchlist": [], "searches": [
                {"keywords": "Mechanical Engineering", "location": "Canada", "term": "Summer 2027", "alerts": True}
            ],
        })))

    def test_repeat_and_cross_source_import_preserve_one_job_and_alert(self):
        import_jobs(self.db, "official", [POSTING], "owner")
        import_jobs(self.db, "official", [POSTING], "owner")
        import_jobs(self.db, "boards:example", [{**POSTING, "requisition": ""}], "owner", complete=False)
        job = self.db.one("SELECT * FROM jobs")
        self.assertEqual(job["source"], "official")
        self.assertEqual(len(self.db.all("SELECT * FROM jobs")), 1)
        self.assertEqual(len(self.db.all("SELECT * FROM alerts")), 1)
        self.assertNotIn("description", public_job(job))
        self.assertNotIn("fingerprint", public_job(job))
        self.assertEqual(len(self.db.all("SELECT * FROM job_versions")), 1)
        import_jobs(self.db, "official", [{**POSTING, "description": "Fall 2027"}], "owner")
        self.assertEqual(len(self.db.all("SELECT * FROM job_versions")), 2)

    def test_search_update_controls_future_alerts(self):
        import_jobs(self.db, "official", [POSTING], "owner")
        self.db.execute("UPDATE owner_settings SET value=? WHERE owner=?", (
            json.dumps({"watchlist": ["Example Robotics"], "searches": []}), "owner",
        ))
        import_jobs(self.db, "official", [POSTING, {
            **POSTING, "title": "Hardware Intern", "location": "Texas",
            "url": "https://example.com/jobs/18", "requisition": "18",
        }], "owner")
        self.assertEqual(len(self.db.all("SELECT * FROM alerts")), 2)
        import_jobs(self.db, "official", [], "owner")
        self.assertEqual(self.db.one("SELECT SUM(active) AS open FROM jobs")["open"], 0)

    def test_alert_requires_a_recent_posting_date_and_can_be_created_when_it_is_found(self):
        today = datetime.now(UTC).date()
        import_jobs(self.db, "official", [
            {**POSTING, "posted_on": None},
            {**POSTING, "posted_on": today - timedelta(days=30), "requisition": "old",
             "url": "https://example.com/jobs/old"},
            {**POSTING, "posted_on": today + timedelta(days=1), "requisition": "future",
             "url": "https://example.com/jobs/future"},
        ], "owner")
        self.assertEqual(self.db.all("SELECT * FROM alerts"), [])
        for _ in range(2):
            import_jobs(self.db, "boards:list", [{**POSTING, "posted_on": today - timedelta(days=29)}], "owner")
        self.assertEqual(self.db.all("SELECT requisition FROM alerts JOIN jobs ON jobs.id=alerts.job_id"),
                         [{"requisition": POSTING["requisition"]}])

    def test_safe_public_links(self):
        self.assertIsNone(canonical_url("javascript:alert(1)"))
        self.assertIsNone(canonical_url("https://example.com@external.example/"))
        self.assertEqual(canonical_url(POSTING["url"]), "https://example.com/jobs/17")

    def test_employer_link_change_preserves_job_first_seen_on_a_board(self):
        import_jobs(self.db, "boards:list", [{**POSTING, "requisition": ""}])
        original = self.db.one("SELECT id FROM jobs")["id"]
        import_jobs(self.db, "official", [POSTING])
        import_jobs(self.db, "official", [{**POSTING, "url": "https://example.com/new-link"}])
        self.assertEqual(self.db.all("SELECT id,url FROM jobs"),
                         [{"id": original, "url": "https://example.com/new-link"}])

    def test_partial_source_expires_missing_rows_after_grace_period(self):
        start = datetime(2026, 11, 1, tzinfo=UTC)
        for day, jobs, active in ((0, [POSTING], 1), (6, [], 1), (8, [], 0), (9, [POSTING], 1)):
            with self.subTest(day=day), patch("backend.catalog.now", return_value=(start + timedelta(days=day)).isoformat()):
                import_jobs(self.db, "official", jobs, complete=False)
                self.assertEqual(self.db.one("SELECT active FROM jobs")["active"], active)

    def test_community_duplicate_cannot_reopen_an_officially_closed_job(self):
        import_jobs(self.db, "official", [POSTING])
        import_jobs(self.db, "boards:index", [POSTING])
        import_jobs(self.db, "official", [])
        import_jobs(self.db, "boards:index", [POSTING])
        self.assertEqual(self.db.one("SELECT active FROM jobs")["active"], 0)
        import_jobs(self.db, "official", [POSTING])
        self.assertEqual(self.db.one("SELECT active FROM jobs")["active"], 1)

    def test_posting_history_records_reversions(self):
        for description in ("A", "B", "A", "A"):
            import_jobs(self.db, "official", [{**POSTING, "description": description}])
        rows = self.db.all("""SELECT v.payload FROM job_changes c JOIN job_versions v
                              ON v.job_id=c.job_id AND v.fingerprint=c.fingerprint ORDER BY c.id DESC""")
        self.assertEqual([json.loads(row["payload"])["description"] for row in rows], ["A", "B", "A"])
