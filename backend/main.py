
import json
import subprocess
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from .analytics import ai_analytics, application_analytics, interview_history, local_timezone
from .auth import SESSION_SECONDS, current_owner, install_auth, require_owner
from .catalog import DISCIPLINES, RECENT, canonical_url, company_key, matches, public_job
from .config import Settings
from .db import Database, now
from .documents import (
    SOURCE_TYPES,
    compile_version,
    cover_letter_pdf,
    document_root,
    pdf_sync_status,
    preview_edit,
    project_source,
    store_version,
    sync_pdf,
)
from .mail_accounts import install_mail
from .mcp import install_mcp
from .models import ApplicationUpdate, CoverLetter, Edit, OwnerSettings, ProjectChanges
from .pages import PAGE_PATHS
from .posting_text import posting_markdown
from .referrals import install_referrals
from .workflows import install_workflows, matching_skills, usage_status

Owner = Annotated[str, Depends(require_owner)]


def create_app(settings=None):
    settings = settings or Settings()
    settings.validate_runtime()
    db = Database(settings.data_dir / "dashboard.sqlite3")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db, app.state.settings = db, settings
    install_mail(app,db,settings)
    install_referrals(app, db, settings)
    install_workflows(app, db, settings)
    app.add_middleware(GZipMiddleware, minimum_size=4096)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, max_age=SESSION_SECONDS,
                       https_only=settings.app_url.startswith("https:"), same_site="lax")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",")])

    @app.middleware("http")
    async def security(request: Request, next_handler):
        path = request.url.path
        browser_write = request.method in {"POST", "PUT", "PATCH", "DELETE"} and path != "/mcp"
        if browser_write and request.headers.get("origin") != settings.app_url:
            return JSONResponse({"detail": "Invalid request origin"}, 403)
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                length = int(request.headers.get("content-length", "-1"))
            except ValueError:
                length = -1
            max_body = 2_000_000 if path == "/api/owner/referrals/import" or (path.startswith("/api/owner/documents/") and path.endswith("/save")) else 180000
            if not 0 <= length <= max_body or request.headers.get("transfer-encoding"):
                return JSONResponse({"detail": "Request body size is invalid"}, 413)
        response = await next_handler(request)
        response.headers.update({
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "X-Frame-Options": "SAMEORIGIN",
            "Content-Security-Policy": ("default-src 'self'; object-src 'none'; base-uri 'none'; "
                                        "style-src 'self' 'unsafe-inline'; worker-src 'self'; img-src 'self' data: https://lh3.googleusercontent.com https://tile.openstreetmap.org; "
                                        "frame-ancestors 'self'; frame-src 'self' blob:; form-action 'self'"),
        })
        if path.startswith(("/api", "/auth", "/mcp")):
            response.headers["Cache-Control"] = "no-store"
        if settings.app_url.startswith("https:"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    install_auth(app, settings, db)
    install_mcp(app, settings, db)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/session")
    def session(request: Request):
        owner=current_owner(request)
        return {"owner": bool(owner), "account":request.session.get("account",{}) if owner else None, "login_available": bool(
            settings.owner_subject and settings.auth0_domain and settings.auth0_client_id and settings.auth0_client_secret
        )}

    @app.get("/api/sources")
    def catalog_sources(request: Request):
        result = []
        owner = current_owner(request)
        recent_counts = {row["source"]: row["count"] for row in db.all("""SELECT s.source,count(*) AS count
            FROM job_sources s JOIN jobs j ON j.id=s.job_id
            WHERE s.active=1 AND j.active=1 AND """ + RECENT + " GROUP BY s.source")}
        for row in db.all("SELECT * FROM sources WHERE enabled=1 ORDER BY id"):
            config = json.loads(row["config"])
            kind = config.get("type", "")
            status = ("reference" if kind == "reference" else "setup" if row["error"] == "JobSpy is not installed"
                      else "failed" if row["error"] else "current" if row["last_success"] else "waiting")
            result.append({"id": row["id"], "last_attempt": row["last_attempt"], "last_success": row["last_success"],
                           "count": row["count"], "recent_count": recent_counts.get(row["id"], 0),
                           "stale": status == "failed", "status": status,
                           "label": config.get("label") or config.get("company") or row["id"],
                           "homepage": canonical_url(config.get("homepage")), "kind": kind,
                           "note": config.get("note") if kind == "reference" else row["error"] if owner else None})
        return result

    @app.get("/api/owner/analytics")
    def owner_analytics(owner: Owner, days: int = Query(7), end: date | None = None,
                        zone: str = Query("", max_length=64), offset_minutes: int = Query(0, ge=-840, le=840)):
        if days not in (7, 28, 90, 365):
            raise HTTPException(422, "Select a 7, 28, 90 or 365 day period.")
        local = local_timezone(zone, offset_minutes)
        today = datetime.now(local).date()
        period_end = min(end or today, today)
        if period_end < date(2000, 1, 1):
            raise HTTPException(422, "Select a period ending in 2000 or later.")
        return {"applications": application_analytics(db, owner, local, period_end, days),
                "codex": ai_analytics(db, owner, local, period_end, days), "usage": usage_status(db)}

    @app.get("/api/owner/interviews")
    def interviews(owner: Owner):
        return interview_history(db, owner)

    @app.get("/api/analytics")
    def analytics(request: Request, offset_minutes: int = Query(0, ge=-840, le=840)):
        offset = timedelta(minutes=offset_minutes)
        local_now = datetime.now(UTC) + offset
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0) - offset
        since = (midnight - timedelta(days=13)).isoformat()
        sqlite_offset = f"{offset_minutes:+d} minutes"
        totals = db.one("""SELECT count(*) AS openings,count(DISTINCT company) AS employers,
                          count(CASE WHEN first_seen>=? THEN 1 END) AS week
                          FROM jobs WHERE active=1 AND """ + RECENT, ((midnight - timedelta(days=6)).isoformat(),))
        added = db.all("""SELECT date(first_seen,?) AS date,count(*) AS count
                        FROM jobs WHERE source<>'private:capture' AND first_seen>=? GROUP BY date""", (sqlite_offset, since))
        by_source = db.all("""SELECT source,count(*) AS count FROM jobs WHERE active=1 AND """ + RECENT + """
                            GROUP BY source ORDER BY count DESC,source""")
        result = {"totals": totals, "added": added, "sources": by_source}
        owner = current_owner(request)
        if owner:
            result["pipeline"] = db.all("""SELECT status,count(*) AS count FROM applications WHERE owner=?
                                           GROUP BY status""", (owner,))
            result["submitted"] = db.all("""SELECT date(first_applied,?) AS date,count(*) AS count FROM (
                SELECT min(at) AS first_applied FROM history WHERE owner=? AND
                (event='Saved as applied' OR event LIKE 'Saved as applied ·%') GROUP BY application_id)
                WHERE first_applied>=? GROUP BY date""", (sqlite_offset, owner, since))
        return result

    @app.get("/api/jobs")
    def jobs(request: Request, q: str = Query("", max_length=160), location: str = Query("", max_length=100),
             offset: int = Query(0, ge=0, le=100000),
             saved_search: int | None = Query(None, ge=0), watchlist: bool = False,
             term: str = Query("", max_length=80), source: str = Query("", max_length=80),
             discipline: str = Query("", max_length=40), map_view: bool = False,
             posted_within: int = Query(30, ge=1, le=30)):
        if discipline and discipline not in DISCIPLINES:
            raise HTTPException(422, "Unknown discipline")
        filters = (f"-{posted_within - 1} days", discipline, DISCIPLINES.get(discipline, ""), q, q,
                   location, source, source, term, term, term, term)
        sql = """FROM jobs WHERE active=1 AND posted_on BETWEEN date('now', ?) AND date('now')
                 AND (?='' OR title REGEXP ?)
                 AND (instr(lower(title),lower(?)) OR instr(lower(company),lower(?)))
                 AND instr(lower(location),lower(?))
                 AND (?='' OR source=?) AND (?='' OR instr(lower(title),lower(?))
                     OR instr(lower(description),lower(?)) OR instr(lower(term_hint),lower(?)))
                 ORDER BY posted_on DESC,id"""
        limit = 2500 if map_view else 100
        if saved_search is None and not watchlist:
            rows = db.all("SELECT count(*) OVER() AS total,id,company,requisition,title,location,url,source,first_seen,last_seen,active,term_hint,posted_on "
                          + sql + " LIMIT ? OFFSET ?", (*filters, limit + 1, offset))
            total = rows[0]["total"] if rows else 0
        else:
            owner = require_owner(request)
            profile = db.settings(owner)
            searches = profile["searches"]
            if saved_search is not None and saved_search >= len(searches):
                raise HTTPException(404, "Saved search does not exist")
            search = searches[saved_search] if saved_search is not None else {}
            companies = {company_key(name) for name in profile["watchlist"]}
            rows = [row for row in db.all("SELECT * " + sql, filters)
                    if matches(row, search) and (not watchlist or company_key(row["company"]) in companies)]
            preferred = search.get("preferred", "").strip()
            if preferred:
                rows.sort(key=lambda row: not matches(row, {"keywords": preferred}))
            total = len(rows)
            rows = rows[offset:offset + limit + 1]
        return {"jobs": [public_job(row) for row in rows[:limit]], "has_more": len(rows) > limit, "total": total,
                "disciplines": list(DISCIPLINES)}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str, request: Request):
        row = get_job(job_id)
        if row["source"] == "private:capture" and not current_owner(request):
            raise HTTPException(404)
        result = public_job(row)
        owner=current_owner(request)
        if owner:
            result["matched_skills"] = matching_skills(row, db.settings(owner).get("skills", []))
            result["contacts"]=[{"id":c["id"],"name":json.loads(c["value"])["name"]} for c in
                                db.all("SELECT id,value FROM contacts WHERE owner=? AND company=? ORDER BY name",(owner,company_key(row["company"])))]
            result.update(description=posting_markdown(row["description"]), fingerprint=row["fingerprint"],
                          versions=[{**v, "payload": json.loads(v["payload"])} for v in db.all(
                              """SELECT c.job_id,c.fingerprint,c.seen_at,v.payload FROM job_changes c
                                 JOIN job_versions v ON v.job_id=c.job_id AND v.fingerprint=c.fingerprint
                                 WHERE c.job_id=? ORDER BY c.id DESC LIMIT 5""", (job_id,))])
        return result

    def get_job(job_id):
        row = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row:
            raise HTTPException(404, "Posting does not exist")
        return row

    @app.get("/api/owner/sources")
    def sources(owner: Owner):
        return db.all("SELECT id,last_attempt,last_success,error,count FROM sources WHERE enabled=1 ORDER BY id")

    @app.get("/api/owner/worker-login")
    def worker_login(owner: Owner):
        return db.one("SELECT status,checked FROM worker_login WHERE id=1") or {"status": "unknown", "checked": None}

    @app.get("/api/owner/settings")
    def get_settings(owner: Owner):
        profile=db.settings(owner)
        if not profile.get("cover_repo"):
            profile.update(cover_repo=settings.cover_letter_repo,cover_branch=settings.cover_letter_branch,cover_entry=settings.cover_letter_entry)
        return profile

    @app.put("/api/owner/settings")
    def update_settings(value: OwnerSettings, owner: Owner):
        db.execute("INSERT INTO owner_settings VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET value=excluded.value",
                   (owner, value.model_dump_json()))
        return value

    @app.get("/api/owner/alerts")
    def alerts(owner: Owner):
        return db.all("""SELECT alerts.job_id,created_at,read,jobs.title,jobs.company FROM alerts
                      JOIN jobs ON jobs.id=alerts.job_id WHERE owner=? AND jobs.active=1 AND """ + RECENT + """ ORDER BY created_at DESC LIMIT 100""", (owner,))

    @app.post("/api/owner/alerts/read")
    def read_alerts(owner: Owner):
        db.execute("UPDATE alerts SET read=1 WHERE owner=?", (owner,))
        return {"ok": True}

    @app.get("/api/owner/applications")
    def applications(owner: Owner):
        return db.all("""SELECT applications.id,applications.job_id,status,notes,deadline,submitted_version,
                      jobs.title,jobs.company,jobs.location FROM applications JOIN jobs ON jobs.id=job_id
                      WHERE owner=? ORDER BY updated_at DESC LIMIT 500""", (owner,))

    def get_application(app_id, owner):
        row = db.one("SELECT * FROM applications WHERE id=? AND owner=?", (app_id, owner))
        if not row:
            raise HTTPException(404, "Application does not exist")
        return row

    @app.get("/api/owner/applications/{app_id}")
    def application_detail(app_id: str, owner: Owner):
        row = get_application(app_id, owner)
        posting = json.loads(row["posting"])
        posting["description"] = posting_markdown(posting["description"])
        return {**row, "posting": posting,
                "history": db.all("SELECT event,at FROM history WHERE application_id=? AND owner=? ORDER BY id DESC",
                                  (app_id, owner)),
                "documents": db.all("""SELECT d.*,p.document_id IS NOT NULL AS verified
                    FROM documents d LEFT JOIN prepared_documents p ON p.document_id=d.id
                    WHERE d.application_id=? AND d.owner=? ORDER BY d.created_at DESC,d.rowid DESC""",
                                    (app_id, owner)),
                "cover_letters": db.all("SELECT * FROM cover_letters WHERE application_id=? AND owner=? "
                                         "ORDER BY created_at DESC LIMIT 20", (app_id, owner)),
                "ai": db.all("SELECT id,status,result FROM ai_tasks WHERE application_id=? AND owner=? "
                             "ORDER BY created_at DESC LIMIT 8", (app_id, owner))}

    @app.put("/api/owner/jobs/{job_id}/application")
    def save_application(job_id: str, value: ApplicationUpdate, owner: Owner):
        job = get_job(job_id)
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT * FROM applications WHERE owner=? AND job_id=?", (owner, job_id)).fetchone()
            app_id = old["id"] if old else uuid.uuid4().hex
            submitted = value.submitted_version or (old["submitted_version"] if old else None)
            posting = old["posting"] if old else json.dumps(job)
            if value.submitted_version:
                document = conn.execute(
                    "SELECT id FROM documents WHERE id=? AND owner=? AND application_id=? AND compiled=1 AND kind='resume'",
                    (submitted, owner, app_id),
                ).fetchone()
                if not document:
                    raise HTTPException(400, "Select a compiled version from this application")
            timestamp = now()
            deadline = str(value.deadline or "")
            if old and (old["status"], old["notes"], old["deadline"], old["submitted_version"]) == (
                value.status, value.notes, deadline, submitted,
            ):
                return {"id": app_id}
            conn.execute("""INSERT INTO applications VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(owner,job_id)
                         DO UPDATE SET status=excluded.status,notes=excluded.notes,deadline=excluded.deadline,
                         submitted_version=excluded.submitted_version,updated_at=excluded.updated_at""",
                         (app_id, owner, job_id, value.status, value.notes, deadline,
                          posting, submitted, timestamp))
            changes = []
            if not old or old["status"] != value.status:
                changes.append(f"Saved as {value.status}")
            if old and old["notes"] != value.notes:
                changes.append("Notes updated")
            if old and old["deadline"] != deadline:
                changes.append(f"Deadline set to {deadline}" if deadline else "Deadline removed")
            if submitted and (not old or old["submitted_version"] != submitted):
                changes.append(f"submitted document {submitted}")
            event = " · ".join(changes)
            conn.execute("INSERT INTO history(application_id,owner,event,at) VALUES (?,?,?,?)",
                         (app_id, owner, event, timestamp))
        return {"id": app_id}

    def get_document(doc_id, owner):
        row = db.one("SELECT * FROM documents WHERE id=? AND owner=?", (doc_id, owner))
        if not row:
            raise HTTPException(404, "Document does not exist")
        return row

    @app.get("/api/owner/templates")
    def templates(owner:Owner):
        return db.all("SELECT * FROM documents WHERE owner=? AND application_id='templates' ORDER BY created_at DESC",(owner,))

    @app.post("/api/owner/templates/{kind}")
    def import_template(kind:str,owner:Owner):
        if kind not in ("resume","cover"):
            raise HTTPException(404)
        try:
            return {"id":store_version(db,settings,owner,"templates",kind=kind)}
        except (ValueError,OSError,httpx.HTTPError,zipfile.BadZipFile,subprocess.SubprocessError) as exc:
            raise HTTPException(422,str(exc) if isinstance(exc,ValueError) else "Could not read the GitHub template") from None

    @app.post("/api/owner/applications/{app_id}/from-template/{kind}")
    def copy_template(app_id:str,kind:str,owner:Owner):
        get_application(app_id,owner)
        doc=db.one("SELECT * FROM documents WHERE owner=? AND application_id='templates' AND kind=? ORDER BY created_at DESC LIMIT 1",(owner,kind))
        if not doc:raise HTTPException(404,"Import a base template in My templates first.")
        return {"id":store_version(db,settings,owner,app_id,previous=doc)}

    @app.post("/api/owner/applications/{app_id}/resume")
    @app.post("/api/owner/applications/{app_id}/cover-template")
    def import_resume(app_id: str, request: Request, owner: Owner):
        get_application(app_id, owner)
        try:
            kind = "cover" if request.url.path.endswith("/cover-template") else "resume"
            return {"id": store_version(db, settings, owner, app_id, kind=kind)}
        except (ValueError, OSError, zipfile.BadZipFile, httpx.HTTPError, subprocess.SubprocessError) as exc:
            detail = str(exc) if type(exc) is ValueError else "Could not import the template. Check the repository, branch and GitHub read access."
            raise HTTPException(422, detail) from None

    @app.post("/api/owner/documents/{doc_id}/edit")
    def edit_document(doc_id: str, edit: Edit, owner: Owner):
        doc = get_document(doc_id, owner)
        try:
            return {"id": store_version(db, settings, owner, doc["application_id"], doc, edit)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/api/owner/documents/{doc_id}/compile")
    def compile_document(doc_id: str, owner: Owner):
        try:
            compile_version(db, settings, get_document(doc_id, owner))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except subprocess.TimeoutExpired:
            raise HTTPException(422, "LaTeX compilation timed out") from None
        return {"ok": True, "sync": pdf_sync_status(document_root(settings, doc_id)),
                "checks": db.one("SELECT pages,overfull FROM document_checks WHERE document_id=?", (doc_id,))}

    @app.post("/api/owner/documents/{doc_id}/preview")
    def preview_document(doc_id: str, edit: Edit, owner: Owner):
        try:
            return Response(preview_edit(settings, get_document(doc_id, owner), edit), media_type="application/pdf")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except subprocess.TimeoutExpired:
            raise HTTPException(422, "LaTeX compilation timed out") from None
        except OSError:
            raise HTTPException(422, "Could not generate the résumé preview") from None

    @app.post("/api/owner/documents/{doc_id}/save")
    def save_project(doc_id: str, changes: ProjectChanges, owner: Owner):
        doc=get_document(doc_id,owner)
        try:
            return {"id":store_version(db,settings,owner,doc["application_id"],doc,changes=changes.files,created=changes.created)}
        except (ValueError,OSError) as exc:
            raise HTTPException(422,"Could not save these project files") from exc

    @app.get("/api/owner/documents/{doc_id}/source")
    def source_file(doc_id: str, owner: Owner, name: str | None = None):
        doc = get_document(doc_id, owner)
        root = document_root(settings, doc_id) / "source"
        try:
            path = project_source(root, name or doc["entry"])
            ancestors=db.all("""WITH RECURSIVE family(id) AS (SELECT parent FROM document_parents WHERE child=?
                        UNION SELECT parent FROM document_parents JOIN family ON child=id)
                        SELECT family.id FROM family JOIN documents ON documents.id=family.id WHERE documents.owner=?""",(doc_id,owner))
            tree = [{"path":p.relative_to(root).as_posix(),"editable":p.suffix.lower() in SOURCE_TYPES and p.stat().st_size<=160000}
                    for p in sorted(root.rglob("*")) if p.is_file()]
            comparison = db.one("SELECT parent FROM document_parents WHERE child=?", (doc_id,))
            return {"files": sorted(p.relative_to(root).as_posix() for p in root.rglob("*.tex") if p.is_file()),
                    "tree":tree, "checks":db.one("SELECT pages,overfull FROM document_checks WHERE document_id=?", (doc_id,)),
                    "ancestors":[r["id"] for r in ancestors], "parent": comparison["parent"] if comparison else None,
                    "name": path.relative_to(root).as_posix(), "content": path.read_text(encoding="utf-8"),
                    "sync": pdf_sync_status(root.parent) if doc["compiled"] else None}
        except (ValueError, OSError):
            raise HTTPException(422, "Could not read this LaTeX file") from None

    @app.get("/api/owner/documents/{doc_id}/sync")
    def document_sync(
        doc_id: str, owner: Owner, name: str | None = Query(None, max_length=512),
        line: int = Query(1, ge=1, le=160000), column: int = Query(1, ge=1, le=160000),
        page: int = Query(1, ge=1, le=10000),
        x: float = Query(0, ge=-100000, le=100000), y: float = Query(0, ge=-100000, le=100000),
    ):
        doc = get_document(doc_id, owner)
        root = document_root(settings, doc_id)
        if not doc["compiled"] or not pdf_sync_status(root):
            raise HTTPException(404, "Recompile this version to enable SyncTeX.")
        try:
            return sync_pdf(root, doc["entry"], name=name, line=line, column=column, page=page, x=x, y=y)
        except (ValueError, OSError, subprocess.TimeoutExpired):
            raise HTTPException(422, "Could not find the matching source or PDF position.") from None

    @app.get("/api/owner/documents/{doc_id}/{kind}")
    def download(doc_id: str, kind: str, owner: Owner):
        doc = get_document(doc_id, owner)
        path = document_root(settings, doc_id)
        if kind == "tex":
            return FileResponse(path / "source" / doc["entry"], media_type="text/plain")
        if kind == "zip":
            return FileResponse(path / "source.zip", filename=f"{doc['kind']}-source.zip", media_type="application/zip")
        if kind == "pdf" and doc["compiled"]:
            return FileResponse(path / "resume.pdf", media_type="application/pdf")
        raise HTTPException(404, "Export does not exist")

    @app.post("/api/owner/applications/{app_id}/ai", status_code=202)
    def enqueue(app_id: str, owner: Owner, doc_id: str | None = None, cover_letter: bool = False, source_file: str | None = None):
        application = get_application(app_id, owner)
        worker = db.one("SELECT status FROM worker_login WHERE id=1")
        if worker and worker["status"] != "connected":
            raise HTTPException(409, "Connect the worker in Settings → Codex connection, then retry.")
        if not json.loads(application["posting"])["description"]:
            raise HTTPException(422, "The saved posting does not include employer requirements")
        if cover_letter and not db.settings(owner)["experience"].strip():
            raise HTTPException(422, "Add your verified experience in Settings before drafting a cover letter")
        if doc_id and get_document(doc_id, owner)["application_id"] != app_id:
            raise HTTPException(404)
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute("SELECT COUNT(*) FROM ai_tasks WHERE owner=? AND status IN ('queued','running')",
                                 (owner,)).fetchone()[0]
            if count >= 3:
                raise HTTPException(429, "Wait for queued Codex tasks to finish")
            task_id = uuid.uuid4().hex
            conn.execute("INSERT INTO ai_tasks VALUES (?,?,?,?,?,?)",
                         (task_id, owner, app_id, "queued",
                          json.dumps({"document": doc_id, "source_file": source_file, "cover_letter": cover_letter}), now()))
        return {"id": task_id}

    @app.post("/api/owner/applications/{app_id}/prepare", status_code=202)
    def prepare_application(app_id: str, owner: Owner):
        application = get_application(app_id, owner)
        worker = db.one("SELECT status FROM worker_login WHERE id=1")
        if worker and worker["status"] != "connected":
            raise HTTPException(409, "Connect the Codex worker first.")
        if not json.loads(application["posting"])["description"] or not db.settings(owner)["experience"].strip():
            raise HTTPException(422, "A full posting and verified experience are required.")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            templates = conn.execute("""SELECT count(DISTINCT kind) FROM documents WHERE owner=?
                AND application_id IN ('templates',?) AND kind IN ('resume','cover')""", (owner, app_id)).fetchone()[0]
            if templates != 2:
                raise HTTPException(422, "Import a résumé and cover-letter template in Application materials.")
            if conn.execute("""SELECT 1 FROM ai_tasks WHERE owner=? AND application_id=?
                AND status IN ('queued','running','limited')""", (owner, app_id)).fetchone():
                raise HTTPException(409, "This application already has queued Codex work.")
            if conn.execute("""SELECT count(*) FROM ai_tasks WHERE owner=?
                AND status IN ('queued','running','limited')""", (owner,)).fetchone()[0] >= 3:
                raise HTTPException(429, "Wait for queued Codex tasks to finish.")
            task_id = uuid.uuid4().hex
            conn.execute("INSERT INTO ai_tasks VALUES (?,?,?,?,?,?)",
                         (task_id, owner, app_id, "queued", '{"prepare_only":true}', now()))
        return {"id": task_id}

    @app.post("/api/owner/applications/{app_id}/cover-letters", status_code=201)
    def save_cover_letter(app_id: str, value: CoverLetter, owner: Owner):
        get_application(app_id, owner)
        letter_id = uuid.uuid4().hex
        db.execute("INSERT INTO cover_letters VALUES (?,?,?,?,?)", (letter_id, owner, app_id, value.content, now()))
        return {"id": letter_id}

    @app.get("/api/owner/applications/{app_id}/cover-letters/{letter_id}/{kind}")
    def download_cover_letter(app_id: str, letter_id: str, kind: str, owner: Owner):
        letter = db.one("SELECT content FROM cover_letters WHERE id=? AND application_id=? AND owner=?",
                        (letter_id, app_id, owner))
        if not letter or kind not in {"txt", "pdf"}:
            raise HTTPException(404, "Cover letter export does not exist")
        content, media_type = letter["content"], "text/plain"
        if kind == "pdf":
            try:
                content, media_type = cover_letter_pdf(content), "application/pdf"
            except (ValueError, OSError, subprocess.TimeoutExpired):
                raise HTTPException(422, "Could not generate the cover letter PDF") from None
        return Response(content, media_type=media_type,
                        headers={"Content-Disposition": f'attachment; filename="cover-letter.{kind}"'})

    static = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if static.is_dir():
        def dashboard_page():
            return FileResponse(static / "index.html", headers={"Cache-Control": "no-cache"})

        for page in PAGE_PATHS:
            app.add_api_route(page, dashboard_page, methods=["GET", "HEAD"], include_in_schema=False)
            if page not in ("/", "/demo"):
                app.add_api_route("/demo" + page, dashboard_page, methods=["GET", "HEAD"], include_in_schema=False)
        app.mount("/", StaticFiles(directory=static, html=True), name="frontend")
    return app
