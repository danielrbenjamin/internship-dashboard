import io
import json
import sqlite3
import uuid
import zipfile
from collections import defaultdict
from typing import Literal

from fastapi import HTTPException, Query, Request
from pydantic import Field

from .catalog import company_key
from .models import Input
from .people_search import search_people
from .workflows import Owner


class Contact(Input):
    name: str = Field(min_length=1, max_length=100)
    company: str = Field(min_length=1, max_length=160)
    email: str = Field(default="", max_length=250)
    linkedin: str = Field(default="", max_length=512, pattern=r"^(?:https://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^/?#\s]+/?(?:[?#][^\s]*)?)?$")
    phone: str = Field(default="", max_length=60)
    connection: str = Field(default="", max_length=500)
    stage: Literal["Not asked", "Warm", "Will refer", "No reply", "Avoid"] = "Not asked"


class Ask(Input):
    text: str = Field(min_length=1, max_length=4000)
    status: Literal["Draft", "Asked", "Referred", "Skipped"]


def install_referrals(app, db, settings):
    @app.get("/api/owner/referrals/people")
    async def find_people(owner: Owner, company: str = Query(min_length=1, max_length=160),
                          team: str = Query(default="", max_length=120)):
        if not company.strip():
            raise HTTPException(422, "Enter an employer.")
        profile = db.settings(owner)
        return await search_people(settings.exa_api_key, company.strip(), team.strip(),
                                   profile.get("referral_school", ""), profile.get("referral_experience", ""),
                                   profile.get("referral_priority", "team"))

    @app.get("/api/owner/referrals")
    def listings(owner: Owner):
        contacts = [
            {"id": r["id"], **json.loads(r["value"])}
            for r in db.all("SELECT * FROM contacts WHERE owner=? ORDER BY name", (owner,))
        ]
        jobs = db.all(
            """SELECT a.id,a.status,j.id AS job_id,j.company,j.title,j.url FROM applications a
                     JOIN jobs j ON j.id=a.job_id WHERE a.owner=? ORDER BY a.updated_at DESC""",
            (owner,),
        )
        saved = {
            (r["contact"], r["application"]): r
            for r in db.all("SELECT * FROM referral_asks WHERE owner=?", (owner,))
        }
        current = defaultdict(list)
        by_id = {j["id"]: j for j in jobs}
        for job in jobs:
            if job["status"] in ("shortlisted", "preparing", "ready"):
                current[company_key(job["company"])].append(job["id"])
        previous = defaultdict(list)
        for contact_id, app_id in saved:
            if app_id in by_id:
                previous[contact_id].append(app_id)
        asks = []
        for c in contacts:
            matches = current[company_key(c["company"])] if c["stage"] not in ("No reply", "Avoid") else []
            for app_id in dict.fromkeys([*matches, *previous[c["id"]]]):
                j = by_id[app_id]
                existing = saved.get((c["id"], app_id))
                text = f"Hi {c['name'].split()[0]}, I’m applying for the {j['title']} role at {j['company']}. Would you be comfortable referring me? I can send my résumé. Here’s the posting: {j['url']}"
                if c["stage"] == "Will refer":
                    text = (f"Hi {c['name'].split()[0]}, thanks for offering to refer me. I found the {j['title']} role "
                            f"at {j['company']} and would appreciate a referral. Here’s the posting: {j['url']}")
                elif c["stage"] == "Warm":
                    text = (f"Hi {c['name'].split()[0]}, it was good connecting with you. I’m applying for the "
                            f"{j['title']} role at {j['company']}. Would you be open to referring me? {j['url']}")
                asks.append(
                    {
                        "contact": c["id"],
                        "application": j["id"],
                        "job_id": j["job_id"],
                        "title": j["title"],
                        "company": j["company"],
                        "text": existing["text"] if existing else text,
                        "status": existing["status"] if existing else "Draft",
                    }
                )
        return {"contacts": contacts, "asks": asks}

    @app.get("/api/owner/priorities")
    def priorities(owner: Owner, limit: int = Query(default=8, ge=1, le=100)):
        items = []
        replies = db.all(
            """SELECT id,kind,subject,due FROM replies WHERE owner=? AND done=0 AND
                 (due IS NOT NULL OR kind IN ('Interview','Assessment','Offer')) ORDER BY due IS NULL,due,created DESC LIMIT ?""",
            (owner, limit),
        )
        items.extend(
            {
                "view": "Replies",
                "id": str(r["id"]),
                "title": r["subject"],
                "label": r["kind"],
                "due": r["due"],
            }
            for r in replies
        )
        referrals = listings(owner)
        names = {c["id"]: c["name"] for c in referrals["contacts"]}
        items.extend(
            {
                "view": "Referrals",
                "id": r["contact"] + r["application"],
                "label": "Referral request",
                "company": r["company"],
                "title": names[r["contact"]] + " · " + r["title"],
            }
            for r in referrals["asks"]
            if r["status"] == "Draft"
        )
        ready = db.all(
            """SELECT a.job_id,j.title,j.company FROM applications a JOIN jobs j ON j.id=a.job_id
                  WHERE a.owner=? AND a.status='ready' ORDER BY a.updated_at DESC LIMIT ?""",
            (owner, limit),
        )
        items.extend(
            {
                "view": "Materials",
                "id": r["job_id"],
                "title": r["company"] + " · " + r["title"],
                "label": "Ready to submit",
            }
            for r in ready
        )
        reports = db.all("""WITH completed AS (
                               SELECT application_id,status,CASE WHEN json_valid(result) THEN result ELSE '{}' END AS report
                               FROM ai_tasks WHERE owner=? AND status IN ('done','failed')
                           )
                           SELECT a.job_id,j.company,j.title,
                               max(coalesce(json_array_length(t.report,'$.edits'),0)>0) AS edits,
                               max(json_extract(t.report,'$.document_id') IS NULL AND coalesce(json_extract(t.report,'$.verdict'),'')='review') AS review,
                               max(t.status='failed') AS failed
                           FROM applications a JOIN jobs j ON j.id=a.job_id JOIN completed t ON a.id=t.application_id
                           WHERE a.owner=? AND a.status IN ('shortlisted','preparing') GROUP BY a.id
                           HAVING edits OR review OR failed ORDER BY a.updated_at DESC LIMIT ?""", (owner, owner, limit))
        items.extend({"view":"Materials","id":r["job_id"],"title":r["company"]+" · "+r["title"],
                      "label":"Review document edits" if r["edits"] else "Decide whether to apply" if r["review"] else "Check Codex task"}
                     for r in reports)
        return items[:limit]

    def write(conn, owner, c, uid):
        try:
            conn.execute(
                """INSERT INTO contacts VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                         name=excluded.name,company=excluded.company,value=excluded.value WHERE contacts.owner=excluded.owner""",
                (uid, owner, c.name.casefold(), company_key(c.company), c.model_dump_json()),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "This contact already exists at this company.") from exc

    @app.post("/api/owner/contacts")
    def add(c: Contact, owner: Owner):
        with db.connect() as conn:
            write(conn, owner, c, uuid.uuid4().hex)
        return {"ok": True}

    @app.put("/api/owner/contacts/{uid}")
    def update(uid: str, c: Contact, owner: Owner):
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute("SELECT id FROM contacts WHERE id=? AND owner=?", (uid, owner)).fetchone():
                raise HTTPException(404)
            write(conn, owner, c, uid)
        return {"ok": True}

    @app.delete("/api/owner/contacts/{uid}")
    def remove(uid: str, owner: Owner):
        with db.connect() as conn:
            conn.execute("DELETE FROM contacts WHERE id=? AND owner=?", (uid, owner))
            conn.execute("DELETE FROM referral_asks WHERE contact=? AND owner=?", (uid, owner))
        return {"ok": True}

    @app.put("/api/owner/referrals/{contact}/{application}")
    def save(contact: str, application: str, ask: Ask, owner: Owner):
        with db.connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM contacts c JOIN applications a ON a.owner=c.owner WHERE c.id=? AND a.id=? AND c.owner=?",
                (contact, application, owner),
            ).fetchone():
                raise HTTPException(404)
            conn.execute(
                "INSERT OR REPLACE INTO referral_asks VALUES(?,?,?,?,?)",
                (owner, contact, application, ask.text, ask.status),
            )
        return {"ok": True}

    @app.post("/api/owner/referrals/import")
    async def sheet(request: Request, owner: Owner):
        from openpyxl import load_workbook

        raw = io.BytesIO(await request.body())
        try:
            with zipfile.ZipFile(raw) as archive:
                if sum(f.file_size for f in archive.infolist()) > 8_000_000:
                    raise ValueError("Workbook too large")
            raw.seek(0)
            book = load_workbook(raw, read_only=True, data_only=True)
            try:
                rows = book.worksheets[0].iter_rows(values_only=True, max_col=64)
                headers = [str(h or "").strip().casefold() for h in next(rows)]
                if not {"name", "company"} <= set(headers):
                    raise ValueError("Missing columns")
                count = 0
                with db.connect() as conn:
                    for idx, row in enumerate(rows):
                        if idx >= 5000:
                            raise ValueError("Too many contacts")
                        v = {k: str(x or "").strip() for k, x in zip(headers, row, strict=True)}
                        if not v["name"] or not v["company"]:
                            continue
                        c = Contact(
                            name=v["name"],
                            company=v["company"],
                            linkedin=v.get("linkedin profile") or v.get("linkedin url") or v.get("linkedin",""),
                            phone=v.get("phone") or v.get("number", ""),
                            email=v.get("email", ""),
                            connection=v.get("connection", ""),
                        )
                        exists = conn.execute(
                            "SELECT id FROM contacts WHERE owner=? AND name=? AND company=?",
                            (owner, c.name.casefold(), company_key(c.company)),
                        ).fetchone()
                        if not exists:
                            write(conn, owner, c, uuid.uuid4().hex)
                            count += 1
            finally:
                book.close()
        except (ValueError, KeyError, StopIteration, zipfile.BadZipFile, OSError) as exc:
            raise HTTPException(
                422, "Use an XLSX sheet with Name and Company columns, up to 5,000 rows."
            ) from exc
        return {"added": count}
