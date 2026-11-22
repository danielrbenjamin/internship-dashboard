import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_catalog import POSTING

from backend import ai, codex_usage
from backend.analytics import ai_analytics, application_analytics, interview_history
from backend.catalog import import_jobs
from backend.config import Settings
from backend.db import Database
from backend.documents import document_root
from backend.models import Edit


def workspace(tmp_path):
    settings = Settings(data_dir=tmp_path, owner_subject="owner")
    db = Database(tmp_path / "dashboard.sqlite3")
    import_jobs(db, "fixture", [{**POSTING, "title": "Mechanical Engineering Intern"}])
    job = db.one("SELECT * FROM jobs")
    db.execute("""INSERT INTO applications(id,owner,job_id,status,posting,updated_at)
        VALUES('role','owner',?,'shortlisted',?,?)""", (job["id"], json.dumps(job), datetime.now(UTC).isoformat()))
    return db, settings


def test_automatic_preparation_repairs_pdf_and_preserves_originals(tmp_path, monkeypatch):
    db, settings = workspace(tmp_path)
    for kind in ("resume", "cover"):
        source = document_root(settings, kind) / "source"
        source.mkdir(parents=True)
        (source / "main.tex").write_text("Original paragraph", encoding="utf-8")
        (source / "reference.tex").write_text("Reference text " * 90, encoding="utf-8")
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                   (kind, "owner", "templates", "commit", "main.tex", "2026-01-01", 0, kind))

    def render(work, entry):
        source = (work / entry).read_text(encoding="utf-8")
        pdf = work / "generated.pdf"
        pdf.write_bytes(b"%PDF-fixture")
        failed = source == "Tailored paragraph"
        pdf.with_suffix(".log").write_text(
            "Overfull \\hbox (3pt too wide) at line 1\nOutput written on generated.pdf (2 pages, 12 bytes)."
            if failed else "Output written on generated.pdf (1 page, 12 bytes).", encoding="utf-8"
        )
        return pdf

    def codex(argv, **kwargs):
        repairs = "Fix the supplied LaTeX diagnostic" in kwargs["input"]
        edits = ([{"before": "Tailored paragraph", "after": "Tailored"}] if repairs else
                 [{"before": "Original paragraph", "after": "Tailored paragraph"}])
        output = Path(argv[argv.index("-o") + 1])
        output.write_text(json.dumps(edits if repairs else {"engineering_fit": "", "assessment": [], "edits": edits}),
                          encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 20, "cached_input_tokens": 4, "output_tokens": 8,
        }}))

    monkeypatch.setattr(ai, "render_pdf", render)
    monkeypatch.setattr(ai.shutil, "which", lambda name: "fixture-codex")
    monkeypatch.setattr(ai.subprocess, "run", codex)
    ai.prepare_documents(db, settings, {"owner": "owner", "application_id": "role", "id": "batch"})
    ai.run_next(db, settings)
    assert db.one("SELECT status FROM applications")["status"] == "preparing"
    ai.run_next(db, settings)
    assert db.one("SELECT status FROM applications")["status"] == "ready"
    verified = db.all("SELECT id,kind FROM documents JOIN prepared_documents ON document_id=id")
    assert {row["kind"] for row in verified} == {"resume", "cover"}
    for row in verified:
        root = document_root(settings, row["id"])
        assert (root / "source" / "main.tex").read_text(encoding="utf-8") == "Tailored"
        assert (root / "resume.pdf").is_file()
        assert (document_root(settings, row["kind"]) / "source" / "main.tex").read_text(
            encoding="utf-8") == "Original paragraph"
    usage = ai_analytics(db, "owner", UTC, datetime.now(UTC).date(), 7)
    assert usage["totals"]["requests"] == 4
    assert usage["totals"]["cached_input_tokens"] == 16
    assert ai_analytics(db, "other", UTC, datetime.now(UTC).date(), 7)["totals"]["requests"] == 0


def test_background_pause_uses_latest_blocking_reset(tmp_path, monkeypatch):
    db, settings = workspace(tmp_path)
    clock = datetime.now(UTC)
    short, long = (int((clock + timedelta(hours=hours)).timestamp()) for hours in (2, 8))
    monkeypatch.setattr(codex_usage, "read_limits", lambda settings: {"rateLimits": {
        "primary": {"usedPercent": 95, "windowDurationMins": 300, "resetsAt": short},
        "secondary": {"usedPercent": 99, "windowDurationMins": 10080, "resetsAt": long},
    }})
    assert codex_usage.refresh_usage(db, settings) == datetime.fromtimestamp(long, UTC).isoformat()
    db.execute("INSERT INTO ai_tasks VALUES('task','owner','role','queued','{}',?)", (clock.isoformat(),))
    ai.run_next(db, settings)
    assert db.one("SELECT status FROM ai_tasks")["status"] == "queued"


def test_interview_history_retains_closed_roles_and_analytics_is_owner_scoped(tmp_path):
    db, _ = workspace(tmp_path)
    clock = datetime.now(UTC)
    for days_ago, event in ((5, "Saved as applied"), (3, "Saved as interview"), (1, "Saved as closed")):
        db.execute("INSERT INTO history(application_id,owner,event,at) VALUES('role','owner',?,?)",
                   (event, (clock - timedelta(days=days_ago)).isoformat()))
    db.execute("UPDATE applications SET status='closed' WHERE id='role'")
    report = application_analytics(db, "owner", UTC, clock.date(), 7)
    assert report["current"] == {"applied": 1, "interview": 1, "closed": 1}
    assert report["cohort_interviews"] == 1
    assert report["median_response_days"] == 2
    assert report["series"][-1]["active"] == 0
    assert report["families"][0]["name"] == "Mechanical"
    assert interview_history(db, "owner")[0]["status"] == "closed"
    assert interview_history(db, "other") == []


def test_automatic_patch_requires_unchanged_latex_structure():
    with pytest.raises(ValueError, match="LaTeX structure"):
        ai.patch_prose("Original paragraph", [Edit(before="Original paragraph", after=r"\textbf{Tailored}")])
