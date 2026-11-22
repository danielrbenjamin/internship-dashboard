import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime


def now():
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, company TEXT NOT NULL, requisition TEXT NOT NULL,
              title TEXT NOT NULL, location TEXT NOT NULL, url TEXT NOT NULL,
              description TEXT NOT NULL, source TEXT NOT NULL, first_seen TEXT NOT NULL,
              last_seen TEXT NOT NULL, fingerprint TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
              term_hint TEXT NOT NULL DEFAULT '',
              UNIQUE(company,requisition));
            CREATE TABLE IF NOT EXISTS job_versions (
              job_id TEXT, fingerprint TEXT, payload TEXT, seen_at TEXT,
              PRIMARY KEY(job_id,fingerprint));
            CREATE TABLE IF NOT EXISTS job_changes (
              id INTEGER PRIMARY KEY, job_id TEXT NOT NULL, fingerprint TEXT NOT NULL, seen_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS job_changes_job ON job_changes(job_id,id);
            INSERT INTO job_changes(job_id,fingerprint,seen_at)
              SELECT job_id,fingerprint,seen_at FROM job_versions AS v
              WHERE NOT EXISTS (SELECT 1 FROM job_changes AS c WHERE c.job_id=v.job_id)
              ORDER BY seen_at, rowid;
            CREATE TABLE IF NOT EXISTS job_sources (
              job_id TEXT NOT NULL, source TEXT NOT NULL, last_seen TEXT NOT NULL, active INTEGER NOT NULL,
              PRIMARY KEY(job_id,source));
            CREATE INDEX IF NOT EXISTS job_sources_source ON job_sources(source,active,last_seen);
            INSERT OR IGNORE INTO job_sources
              SELECT id,source,last_seen,active FROM jobs;
            CREATE TABLE IF NOT EXISTS learned_boards (origin TEXT, id TEXT, config TEXT NOT NULL, PRIMARY KEY(origin,id));
            CREATE TABLE IF NOT EXISTS sources (
              id TEXT PRIMARY KEY, config TEXT NOT NULL, last_attempt TEXT,
              last_success TEXT, error TEXT, count INTEGER DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS owner_settings (owner TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS applications (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, job_id TEXT NOT NULL,
              status TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '', deadline TEXT NOT NULL DEFAULT '',
              posting TEXT NOT NULL, submitted_version TEXT, updated_at TEXT NOT NULL,
              UNIQUE(owner,job_id));
            CREATE TABLE IF NOT EXISTS history (
              id INTEGER PRIMARY KEY, application_id TEXT, owner TEXT, event TEXT, at TEXT);
            CREATE TABLE IF NOT EXISTS alerts (
              owner TEXT, job_id TEXT, created_at TEXT, read INTEGER DEFAULT 0,
              PRIMARY KEY(owner,job_id));
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY, owner TEXT, application_id TEXT, commit_sha TEXT,
              entry TEXT, created_at TEXT, compiled INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS cover_letters (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, application_id TEXT NOT NULL,
              content TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS cover_letters_app ON cover_letters(application_id,owner,created_at);
            CREATE TABLE IF NOT EXISTS worker_login(id INTEGER PRIMARY KEY,status TEXT,checked TEXT);
            CREATE TABLE IF NOT EXISTS codex_usage(id INTEGER PRIMARY KEY, checked TEXT NOT NULL,
              windows TEXT NOT NULL, available INTEGER NOT NULL, pause_until TEXT);
            CREATE TABLE IF NOT EXISTS codex_calls(id INTEGER PRIMARY KEY, owner TEXT NOT NULL,
              task_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, at TEXT NOT NULL,
              duration_ms INTEGER NOT NULL, input_tokens INTEGER, cached_input_tokens INTEGER, output_tokens INTEGER);
            CREATE INDEX IF NOT EXISTS codex_calls_owner_at ON codex_calls(owner,at);
            CREATE TABLE IF NOT EXISTS prepared_documents(document_id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS worker_controls(owner TEXT PRIMARY KEY,interval_minutes INTEGER NOT NULL DEFAULT 5,
              requested INTEGER NOT NULL DEFAULT 0, started TEXT, finished TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS document_checks(document_id TEXT PRIMARY KEY,pages INTEGER,overfull INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_retries(task_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ai_tasks (
              id TEXT PRIMARY KEY, owner TEXT, application_id TEXT, status TEXT,
              result TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS document_parents(child TEXT PRIMARY KEY,parent TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY,owner TEXT,name TEXT,company TEXT,value TEXT,UNIQUE(owner,name,company));
            CREATE TABLE IF NOT EXISTS referral_asks(owner TEXT,contact TEXT,application TEXT,text TEXT,status TEXT,PRIMARY KEY(owner,contact,application));
            CREATE TABLE IF NOT EXISTS mail_accounts(owner TEXT,provider TEXT,address TEXT,secret TEXT,PRIMARY KEY(owner,provider));
            CREATE TABLE IF NOT EXISTS screening(owner TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reply_actions(reply_id INTEGER PRIMARY KEY,owner TEXT,app_id TEXT,old_status TEXT,history_id INTEGER);
            CREATE TABLE IF NOT EXISTS mail_sync(owner TEXT PRIMARY KEY,status TEXT,checked TEXT);
            CREATE TABLE IF NOT EXISTS draft_requests(owner TEXT,app_id TEXT,PRIMARY KEY(owner,app_id));
            CREATE TABLE IF NOT EXISTS replies(id INTEGER PRIMARY KEY,owner TEXT,key TEXT,subject TEXT,sender TEXT,
              body TEXT,kind TEXT,application_id TEXT DEFAULT '',due TEXT,link TEXT DEFAULT '',done INTEGER DEFAULT 0,
              created TEXT, UNIQUE(owner,key));
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
            """)
            db.execute("BEGIN IMMEDIATE")
            if "kind" not in {col["name"] for col in db.execute("PRAGMA table_info(documents)")}:
                db.execute("ALTER TABLE documents ADD COLUMN kind TEXT NOT NULL DEFAULT 'resume'")
            if "enabled" not in {column["name"] for column in db.execute("PRAGMA table_info(sources)")}:
                db.execute("ALTER TABLE sources ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
            if "term_hint" not in {column["name"] for column in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN term_hint TEXT NOT NULL DEFAULT ''")
            if "posted_on" not in {column["name"] for column in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN posted_on TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS jobs_posted ON jobs(active,posted_on DESC)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.create_function("regexp", 2, lambda pattern, value: bool(re.search(pattern, value, re.IGNORECASE)),
                           deterministic=True)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect() as db:
            db.execute(sql, args)

    def settings(self, owner):
        row = self.one("SELECT value FROM owner_settings WHERE owner=?", (owner,))
        return json.loads(row["value"]) if row else {
            "watchlist": [], "searches": [], "experience": "", "resume_repo": "",
            "resume_branch": "main", "resume_entry": "main.tex",
        }
