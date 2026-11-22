import hashlib
import imaplib
import json
import re
import ssl
import uuid
from datetime import UTC, datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query
from pydantic import AwareDatetime, Field

from .auth import require_owner
from .catalog import RECENT, canonical_url, company_key, matches
from .db import now
from .models import Input
from .posting_text import posting_markdown

Owner = Annotated[str, Depends(require_owner)]


class Preferences(Input):
    auto_shortlist: bool = False
    draft: bool = False
    smart: bool = False
    prepare: bool = False
    max_experience_years: int = Field(default=0, ge=0, le=20)
    reject_no_sponsorship: bool = False
    minimum_annual_pay: int = Field(default=0, ge=0, le=1_000_000)
    threshold: int = Field(default=75, ge=50, le=100)


class Reply(Input):
    received: AwareDatetime | None = None
    subject: str = Field(min_length=1, max_length=500)
    sender: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=32000)


class Triage(Input):
    kind: str | None = Field(
        default=None, pattern=r"^(Reply|Confirmation|Interview|Assessment|Offer|Rejected)$"
    )
    application_id: str = ""
    due: AwareDatetime | None = None
    link: str = Field(default="", max_length=2000)
    done: bool = False


def ranked(db, owner):
    profile = db.settings(owner)
    terms = profile.get("searches", [])
    watched = {company_key(name) for name in profile.get("watchlist", [])}
    if not terms and not watched:
        return []
    jobs = db.all(
        "SELECT j.* FROM jobs j WHERE active=1 AND "
        + RECENT
        + " AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.job_id=j.id AND a.owner=?)",
        (owner,),
    )
    results = []
    for job in jobs:
        rules = [s for s in terms if matches(job, s)]
        favorite = company_key(job["company"]) in watched
        if not rules and not favorite:
            continue
        score, reasons = (50, ["Watchlisted employer"]) if favorite else (0, [])
        if rules:
            reasons.append("Saved search: " + ", ".join(s["name"] for s in rules))
            score += 50
            best = (0, [])
            for rule in rules:
                evidence = []
                if rule["location"]:
                    evidence.append("Location: " + rule["location"])
                if rule["term"]:
                    evidence.append("Term: " + rule["term"])
                for group in rule["keywords"].split(","):
                    if group.strip() and all(w.casefold() in job["title"].casefold() for w in group.split()):
                        evidence.append("Title: " + group.strip())
                        break
                for word in rule["preferred"].split(","):
                    if word.strip() and word.strip().casefold() in job["description"].casefold():
                        evidence.append("Preferred: " + word.strip())
                points = min(50, 15 * len(evidence))
                if points > best[0]:
                    best = points, evidence
            score += best[0]
            reasons.extend(best[1])
        skills = (
            "CAD",
            "SolidWorks",
            "CATIA",
            "Fusion 360",
            "C++",
            "Python",
            "MATLAB",
            "GD&T",
            "FEA",
            "CFD",
            "PCB",
            "Altium",
            "FPGA",
            "Verilog",
            "ROS",
            "CNC",
            "Simulink",
            "PLC",
            "embedded systems",
        )
        overlap = [
            skill
            for skill in skills
            if all(
                re.search(r"(?<!\w)" + re.escape(skill) + r"(?!\w)", text, re.IGNORECASE)
                for text in (profile.get("experience", ""), job["title"] + " " + job["description"])
            )
        ]
        if overlap:
            score += min(30, 10 * len(overlap))
            reasons.append("In your experience and the posting: " + ", ".join(overlap))
        results.append((min(100, score), reasons, job))
    return sorted(results, key=lambda row: (row[0], row[2]["posted_on"], row[2]["id"]), reverse=True)


def prefs(db, owner):
    row = db.one("SELECT value FROM screening WHERE owner=?", (owner,))
    return Preferences.model_validate_json(row["value"]) if row else Preferences()


def excluded(job, config):
    title = job["title"]
    description = posting_markdown(job["description"])
    senior = re.search(r"\b(?:senior|staff|principal|director|manager)\s+(?!(?:intern|co-op)\b)", title, re.IGNORECASE)
    experience = re.findall(r"(\d+)\s*\+?\s+years? of (?:professional|relevant|required) experience", description, re.IGNORECASE)
    blocked = re.search(r"\b(?:no (?:visa )?sponsorship|unable to (?:offer|provide) (?:visa )?sponsorship|citizens only)\b",
                        description, re.IGNORECASE)
    annual_pay = re.search(r"(?:CA|US|CAD |USD )?\$([\d,]+)(?:\s*[-–]\s*(?:CA|US|CAD |USD )?\$([\d,]+))?\s*(?:/\s*(?:yr|year)\b|per year\b|annually\b)",
                           description, re.IGNORECASE)
    below_floor = False
    if config.minimum_annual_pay and annual_pay:
        upper = int((annual_pay[2] or annual_pay[1]).replace(",", ""))
        below_floor = 0 < upper < config.minimum_annual_pay
    return bool(senior or below_floor
                or (config.max_experience_years and any(int(years) > config.max_experience_years for years in experience))
                or (config.reject_no_sponsorship and blocked))


def auto_screen(db, owner):
    config = prefs(db, owner)
    if not config.auto_shortlist:
        return
    experience = db.settings(owner).get("experience", "").strip()
    if config.smart and not experience:
        return
    created = 0
    for score, reasons, job in ranked(db, owner):
        if score < config.threshold:
            break
        if config.smart:
            if created >= 10:
                break
            if not job["description"] or excluded(job, config):
                continue
        app_id = uuid.uuid4().hex
        with db.connect() as conn:
            inserted = conn.execute(
                """INSERT OR IGNORE INTO applications
                (id,owner,job_id,status,posting,updated_at) VALUES (?,?,?,'shortlisted',?,?)""",
                (app_id, owner, job["id"], json.dumps(job), now()),
            ).rowcount
            if inserted:
                conn.execute(
                    "INSERT INTO history(application_id,owner,event,at) VALUES(?,?,?,?)",
                    (app_id, owner, f"Shortlisted ({score}/100). " + ". ".join(reasons), now()),
                )
                created += 1
                if config.smart or (config.draft and job["description"]):
                    conn.execute("INSERT OR IGNORE INTO draft_requests VALUES (?,?)", (owner, app_id))
    if (config.draft or config.smart) and experience:
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            free = (
                3
                - conn.execute(
                    "SELECT count(*) FROM ai_tasks WHERE owner=? AND status IN ('queued','running')", (owner,)
                ).fetchone()[0]
            )
            for row in conn.execute(
                "SELECT app_id FROM draft_requests WHERE owner=? LIMIT ?", (owner, max(0, free))
            ).fetchall():
                conn.execute(
                    "INSERT INTO ai_tasks VALUES (?,?,?,?,?,?)",
                    (
                        uuid.uuid4().hex,
                        owner,
                        row[0],
                        "queued",
                        json.dumps({"document": None, "cover_letter": config.draft and not config.smart,
                                    "screen": config.smart, "prepare": config.prepare and config.smart,
                                    "threshold": config.threshold}),
                        now(),
                    ),
                )
                conn.execute("DELETE FROM draft_requests WHERE owner=? AND app_id=?", (owner, row[0]))


def store_reply(db, owner, reply, key="", automatic=False):
    digest = key or hashlib.sha256(reply.model_dump_json(exclude={"received"}).encode()).hexdigest()
    received = reply.received.astimezone(UTC).isoformat() if reply.received else now()
    content = (reply.subject + " " + reply.body).casefold()
    kind = next(
        (
            label
            for label, pattern in [
                ("Rejected", r"not moving forward|selected other candidates|unable to proceed"),
                ("Assessment", r"assessment|take.home|coding challenge"),
                ("Interview", r"interview|schedule a call"),
                ("Rejected", r"unfortunately|other candidates|not moving forward"),
                ("Offer", r"offer letter|pleased to offer"),
                ("Confirmation", r"application received|thank you for applying"),
            ]
            if re.search(pattern, content)
        ),
        "Reply",
    )
    apps = db.all(
        "SELECT a.id,j.company,j.title FROM applications a JOIN jobs j ON j.id=a.job_id WHERE owner=?",
        (owner,),
    )
    possible = [
        a
        for a in apps
        if re.search(
            r"\b" + re.escape(a["company"].casefold()) + r"\b", content + " " + reply.sender.casefold()
        )
    ]
    exact = [a for a in possible if a["title"].casefold() in content]
    possible = exact or possible
    matched = possible[0]["id"] if len(possible) == 1 else ""
    due = None
    stamp = re.search(
        r"(?i)\b(?:due|deadline|complete by|submit by)\s*(?:is\s+|on\s+|:\s*)?"
        r"(20\d\d-\d\d-\d\d[T ]\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d))",
        reply.body,
    )
    if stamp:
        try:
            due = datetime.fromisoformat(stamp[1]).astimezone(UTC).isoformat()
        except ValueError:
            pass
    if due is None:
        natural = re.search(
            r"(?i)\b(?:due|deadline|complete by|submit by)\s*(?:is |on |: *)?"
            r"([a-z]{3,9} \d{1,2},? 20\d{2})[ ,]+(?:at )?(\d{1,2}:\d{2} [AP]M) "
            r"(UTC|GMT|PST|PDT|EST|EDT|CST|CDT|MST|MDT)\b",
            reply.body,
        )
        if natural:
            offsets = {
                "UTC": 0,
                "GMT": 0,
                "PST": -8,
                "PDT": -7,
                "EST": -5,
                "EDT": -4,
                "CST": -6,
                "CDT": -5,
                "MST": -7,
                "MDT": -6,
            }
            for fmt in ("%B %d %Y %I:%M %p", "%b %d %Y %I:%M %p"):
                try:
                    local = datetime.strptime(natural[1].replace(",", "") + " " + natural[2], fmt)
                    due = (
                        local.replace(tzinfo=timezone(timedelta(hours=offsets[natural[3].upper()])))
                        .astimezone(UTC)
                        .isoformat()
                    )
                    break
                except ValueError:
                    continue
    links = {url.rstrip(".,;)") for url in re.findall(r"https://[^\s<>()]+", reply.body)}
    link = next(iter(links)) if len(links) == 1 and kind in {"Assessment", "Interview"} else ""
    with db.connect() as conn:
        inserted = conn.execute(
            """INSERT OR IGNORE INTO replies(owner,key,subject,sender,body,kind,application_id,created,due,link)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (owner, digest, reply.subject, reply.sender, reply.body, kind, matched, received, due, link),
        )
        if automatic and inserted.rowcount and matched:
            stage = {"Interview": "interview", "Confirmation": "applied", "Offer": "offer", "Rejected": "closed"}.get(kind)
            old = conn.execute(
                "SELECT status,updated_at FROM applications WHERE id=? AND owner=?", (matched, owner)
            ).fetchone()
            if (
                stage
                and old
                and (not reply.received or received >= old["updated_at"])
                and old["status"] not in (stage, "closed")
                and not (old["status"] == "interview" and stage == "applied")
                and not (old["status"] == "offer" and stage in ("applied", "interview"))
            ):
                conn.execute(
                    "UPDATE applications SET status=?,updated_at=? WHERE id=? AND owner=?",
                    (stage, now(), matched, owner),
                )
                event = conn.execute(
                    "INSERT INTO history(application_id,owner,event,at) VALUES(?,?,?,?)",
                    (matched, owner, f"Saved as {stage} · Matched employer email", now()),
                )
                conn.execute(
                    "INSERT INTO reply_actions VALUES(?,?,?,?,?)",
                    (inserted.lastrowid, owner, matched, old["status"], event.lastrowid),
                )


def sync_mail(db, settings, owner, filter_inbox=False):
    with imaplib.IMAP4_SSL(settings.mail_host, timeout=15, ssl_context=ssl.create_default_context()) as mail:
        mail.login(settings.mail_user, settings.mail_password)
        if mail.select('"' + settings.mail_folder.replace('"', "") + '"', readonly=True)[0] != "OK":
            raise ValueError("Check your mail folder name.")
        if filter_inbox:
            since = (datetime.now(UTC) - timedelta(days=14)).strftime("%d-%b-%Y")
            status, ids = mail.uid(
                "search",
                None,
                "SINCE",
                since,
                "OR",
                "OR",
                "OR",
                "OR",
                "OR",
                "SUBJECT",
                "application",
                "SUBJECT",
                "interview",
                "SUBJECT",
                "assessment",
                "SUBJECT",
                "offer",
                "SUBJECT",
                "applying",
                "SUBJECT",
                "candidacy",
            )
        else:
            status, ids = mail.uid("search", None, "ALL")
        if status != "OK":
            raise ValueError("Mailbox search failed.")
        epoch = mail.response("UIDVALIDITY")[1][0] or b""
        known = {row["key"] for row in db.all("SELECT key FROM replies WHERE owner=?", (owner,))}
        imported = 0
        for uid in reversed(ids[0].split()):
            key = hashlib.sha256(
                b"|".join(
                    [
                        settings.mail_host.encode(),
                        settings.mail_user.encode(),
                        settings.mail_folder.encode(),
                        epoch,
                        uid,
                    ]
                )
            ).hexdigest()
            if key in known:
                continue
            status, parts = mail.uid("fetch", uid, "(BODY.PEEK[]<0.1000000>)")
            if status != "OK" or not isinstance(parts[0], tuple):
                continue
            reply = read_message(parts[0][1])
            if filter_inbox:
                from .mail_accounts import application_message

                if not application_message(reply.subject, reply.body):
                    continue
            store_reply(db, owner, reply, key, automatic=filter_inbox)
            imported += 1
            if imported == 25:
                break


def read_message(data):
    msg = BytesParser(policy=policy.default).parsebytes(data)
    body = msg.get_body(preferencelist=("plain", "html"))
    content = body.get_content() if body else ""
    try:
        received = parsedate_to_datetime(str(msg.get("Date") or ""))
    except (TypeError, ValueError, OverflowError):
        received = None
    return Reply(
        received=received if received and received.tzinfo else None,
        subject=str(msg["subject"] or "Employer reply")[:500],
        sender=str(msg["from"] or "")[:500],
        body=posting_markdown(str(content))[:32000],
    )


def usage_status(db):
    row = db.one("SELECT checked,windows,available,pause_until FROM codex_usage WHERE id=1")
    if row:
        row["windows"] = json.loads(row["windows"])
    return row


def install_workflows(app, db, settings):
    @app.get("/api/owner/reminders")
    def reminders(owner: Owner):
        return db.all(
            """SELECT id,subject,due FROM replies WHERE owner=? AND done=0
                         AND julianday(due)<=julianday('now','+1 day') ORDER BY due""",
            (owner,),
        )

    @app.get("/api/owner/background")
    def background(owner: Owner):
        return {
            "worker": db.one("SELECT status,checked FROM worker_login WHERE id=1"),
            "usage": usage_status(db),
            "collection": db.one("SELECT interval_minutes,requested,started,finished,error FROM worker_controls WHERE owner=?", (owner,)),
            "tasks": db.all("""SELECT t.id,t.status,t.created_at,j.title,j.company,a.job_id
                               FROM ai_tasks t JOIN applications a ON a.id=t.application_id
                               JOIN jobs j ON j.id=a.job_id WHERE t.owner=?
                               ORDER BY CASE WHEN t.status IN ('running','queued','limited') THEN 0 ELSE 1 END,t.created_at DESC LIMIT 50""", (owner,)),
        }

    @app.post("/api/owner/background/run")
    def run_now(owner: Owner):
        db.execute("""INSERT INTO worker_controls(owner,requested) VALUES (?,1)
                      ON CONFLICT(owner) DO UPDATE SET requested=1""", (owner,))
        return {"queued": True}

    @app.put("/api/owner/background/schedule")
    def schedule(owner: Owner, minutes: int = Query(ge=5, le=1440)):
        db.execute("""INSERT INTO worker_controls(owner,interval_minutes) VALUES (?,?)
                      ON CONFLICT(owner) DO UPDATE SET interval_minutes=excluded.interval_minutes""", (owner, minutes))
        return {"interval_minutes": minutes}

    @app.get("/api/owner/screening")
    def screening(owner: Owner):
        return {
            "preferences": prefs(db, owner),
            "reviews": db.all("""WITH reports AS (
                    SELECT application_id,created_at,CASE WHEN json_valid(result) THEN result ELSE '{}' END AS report
                    FROM ai_tasks WHERE owner=? AND status='done'
                ) SELECT j.id,j.title,j.company,
                    json_extract(report,'$.verdict') AS verdict,
                    json_extract(report,'$.match_score') AS score,
                    json_extract(report,'$.recruiter_read') AS summary
                FROM reports JOIN applications a ON a.id=application_id JOIN jobs j ON j.id=a.job_id
                WHERE a.owner=? AND json_extract(report,'$.screen')=1
                ORDER BY created_at DESC LIMIT 50""", (owner,owner)),
            "roles": [
                {
                    **{k: j[k] for k in ("id", "title", "company", "location", "posted_on")},
                    "score": s,
                    "reasons": r,
                }
                for s, r, j in ranked(db, owner)[:100]
            ],
        }

    @app.put("/api/owner/screening")
    def save(config: Preferences, owner: Owner):
        db.execute("INSERT OR REPLACE INTO screening VALUES(?,?)", (owner, config.model_dump_json()))
        auto_screen(db, owner)
        return config

    @app.get("/api/owner/replies")
    def inbox(owner: Owner):
        return {
            "mail": bool(
                (settings.mail_host and settings.mail_user and settings.mail_password)
                or db.one(
                    "SELECT 1 FROM mail_accounts WHERE owner=? AND provider IN ('Gmail','Outlook')", (owner,)
                )
            ),
            "sync": db.one("SELECT status,checked FROM mail_sync WHERE owner=?", (owner,)),
            "items": db.all(
                "SELECT replies.*, EXISTS(SELECT 1 FROM reply_actions WHERE reply_id=replies.id) AS applied FROM replies WHERE owner=? ORDER BY done, due IS NULL, due, created DESC",
                (owner,),
            ),
        }

    @app.post("/api/owner/replies/{reply_id}/outcome")
    def outcome(reply_id: int, owner: Owner, undo: bool = False):
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM replies WHERE id=? AND owner=?", (reply_id, owner)).fetchone()
            if not row:
                raise HTTPException(404)
            prior = conn.execute(
                "SELECT * FROM reply_actions WHERE reply_id=? AND owner=?", (reply_id, owner)
            ).fetchone()
            if undo:
                if not prior:
                    return {"ok": True}
                app_id = prior["app_id"]
                last = conn.execute(
                    "SELECT max(id) FROM history WHERE application_id=? AND owner=?", (app_id, owner)
                ).fetchone()[0]
                if last != prior["history_id"]:
                    raise HTTPException(409, "The application has changed. Update its stage in Materials.")
                target = prior["old_status"]
                conn.execute("DELETE FROM reply_actions WHERE reply_id=?", (reply_id,))
            else:
                if prior:
                    return {"ok": True}
                app_id = row["application_id"]
                target = {"Confirmation": "applied", "Interview": "interview", "Offer": "offer", "Rejected": "closed"}.get(
                    row["kind"]
                )
                current = conn.execute(
                    "SELECT status FROM applications WHERE id=? AND owner=?", (app_id, owner)
                ).fetchone()
                if not current or not target:
                    raise HTTPException(422, "Choose an application and an outcome first.")
                if current["status"] == target or (
                    target == "applied" and current["status"] in ("interview", "offer", "closed")
                ):
                    raise HTTPException(409, "The application already reached this stage.")
            conn.execute(
                "UPDATE applications SET status=?, updated_at=? WHERE id=? AND owner=?",
                (target, now(), app_id, owner),
            )
            event = conn.execute(
                "INSERT INTO history(application_id,owner,event,at) VALUES(?,?,?,?)",
                (
                    app_id,
                    owner,
                    f"Saved as {target} · {'Undid' if undo else 'Confirmed'} reply outcome",
                    now(),
                ),
            )
            if not undo:
                conn.execute(
                    "INSERT INTO reply_actions VALUES(?,?,?,?,?)",
                    (reply_id, owner, app_id, current["status"], event.lastrowid),
                )
        return {"ok": True}

    @app.put("/api/owner/replies/{reply_id}")
    def edit(reply_id: int, value: Triage, owner: Owner):
        if value.link and not canonical_url(value.link):
            raise HTTPException(422, "Enter a web link.")
        if value.application_id and not db.one(
            "SELECT id FROM applications WHERE id=? AND owner=?", (value.application_id, owner)
        ):
            raise HTTPException(404, "Unknown application")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM reply_actions JOIN replies ON replies.id=reply_id WHERE reply_id=? AND replies.owner=? AND (application_id<>? OR kind<>coalesce(?,kind))",
                (reply_id, owner, value.application_id, value.kind),
            ).fetchone():
                raise HTTPException(409, "Undo the stage change before changing the outcome or application.")
            if value.kind:
                conn.execute(
                    "UPDATE replies SET kind=? WHERE id=? AND owner=?", (value.kind, reply_id, owner)
                )
            if not conn.execute(
                "UPDATE replies SET application_id=?,due=?,link=?,done=? WHERE id=? AND owner=?",
                (
                    value.application_id,
                    value.due.astimezone(UTC).isoformat() if value.due else None,
                    value.link,
                    value.done,
                    reply_id,
                    owner,
                ),
            ).rowcount:
                raise HTTPException(404)
        return {"ok": True}
