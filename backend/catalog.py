
import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .db import now

PUBLIC_FIELDS = (
    "id", "company", "requisition", "title", "location", "url", "source", "first_seen", "last_seen", "active",
)
INTERNSHIP = re.compile(
    r"\b(intern(ship)?s?|co[- ]?op|placement|working student|student trainee|werkstudent|praktikum|stagiaire)\b",
    re.IGNORECASE,
)
ALIASES = {"the walt disney company": "disney", "advanced micro devices": "amd", "apple inc": "apple"}
RECENT = "posted_on BETWEEN date('now','-29 days') AND date('now')"
DISCIPLINES = {
    "Mechanical": r"\b(mechanical|electromechanical|mechatronic\w*|thermal|fluid\w*|product design|CAD|chassis|powertrain|tooling)\b",
    "Hardware": r"\b(hardware|electronic\w*|electrical|embedded|firmware|silicon|ASIC|FPGA|PCB|RTL|semiconductor\w*)\b",
    "Robotics": r"\b(robot\w*|mechatronic\w*|autonom\w*|automation|controls?)\b",
    "Manufacturing": r"\b(manufactur\w*|production|industrial|tooling|process engineer\w*|assembly)\b",
    "Aerospace": r"\b(aerospace|aerodynamic\w*|avionics|propulsion|spacecraft|aircraft|flight)\b",
    "Software": r"\b(software|full[ -]?stack|back[ -]?end|front[ -]?end|SWE|developer|firmware)\b",
    "Data & AI": r"\b(data|machine learning|deep learning|AI|ML|artificial intelligence|computer vision)\b",
}


def posting_date(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, UTC).date().isoformat()
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value).date().isoformat()
            except ValueError:
                for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
                    try:
                        return datetime.strptime(value, fmt).date().isoformat()
                    except ValueError:
                        continue
    except (OverflowError, OSError, ValueError):
        pass
    return None


def canonical_url(url):
    if not isinstance(url, str) or "\\" in url or any(char.isspace() or ord(char) < 32 for char in url):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme == "https" and parts.hostname and not parts.username and not parts.password:
            tracking = {"gh_src", "tracking", "source", "ref", "trk"}
            keep_query = urlencode(sorted((key, value) for key, value in parse_qsl(parts.query)
                                          if not key.startswith("utm_") and key not in tracking))
            return urlunsplit(("https", parts.netloc, parts.path.rstrip("/") or "/", keep_query, ""))
    except ValueError:
        pass
    return None


def public_job(job):
    result = {key: job[key] for key in PUBLIC_FIELDS}
    result["posted_on"] = job.get("posted_on")
    term = re.search(r"\b(?:summer|fall|autumn|winter|spring)\s+20\d\d\b", job["title"], re.IGNORECASE)
    result["term"] = job.get("term_hint") or (term.group().title() if term else None)
    return result


def matches(job, search):
    text = f"{job['title']} {job['company']} {job['description']} {job.get('term_hint', '')}".casefold()
    groups = [part.strip().casefold() for part in search.get("keywords", "").split(",") if part.strip()]
    return (
        (not groups or any(all(word in text for word in group.split()) for group in groups))
        and search.get("location", "").casefold() in job["location"].casefold()
        and search.get("term", "").casefold() in text
    )


def company_key(name):
    key = name.strip().casefold().rstrip(".")
    return ALIASES.get(key, key)


def import_jobs(db, source, jobs, owner="", complete=True, stale_days=7):
    timestamp = now()
    options = db.settings(owner) if owner else {}
    watchlist = {company_key(name) for name in options.get("watchlist", [])}
    searches = [item for item in options.get("searches", []) if item["alerts"]]
    seen = set()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for job in jobs:
            url = canonical_url(job["url"])
            if not url or not (job.get("internship") or INTERNSHIP.search(job["title"])):
                continue
            company = company_key(job["company"])
            requisition = str(job["requisition"]).strip()
            identity = f"{company}:{requisition.casefold()}" if requisition else url
            key = hashlib.sha256(identity.encode()).hexdigest()[:24]
            posted = posting_date(job.get("posted_on"))
            duplicate = conn.execute("""SELECT j.id,j.source,j.fingerprint,j.description,j.posted_on,s.enabled FROM jobs j
                                        LEFT JOIN sources s ON j.source=s.id
                                        WHERE j.id=? OR j.url=? OR (j.company=? AND j.requisition=?)
                                        ORDER BY (j.company=? AND j.requisition=?) DESC,j.id=? DESC LIMIT 1""",
                                     (key, url, job["company"], requisition, job["company"], requisition, key)).fetchone()
            if duplicate:
                key = duplicate["id"]
                if duplicate["posted_on"]:
                    posted = min(posted or duplicate["posted_on"], duplicate["posted_on"])
            if key in seen:
                continue
            seen.add(key)
            conn.execute("""INSERT INTO job_sources VALUES (?,?,?,1)
                            ON CONFLICT(job_id,source) DO UPDATE SET last_seen=excluded.last_seen,active=1""",
                         (key, source, timestamp))
            if duplicate and duplicate["source"] != source and duplicate["enabled"] != 0:
                primary_is_board = duplicate["source"].startswith("boards:")
                prefer_new = primary_is_board and (not source.startswith("boards:")
                                                  or (not duplicate["description"] and job["description"]))
                if not prefer_new:
                    conn.execute("UPDATE jobs SET last_seen=?,posted_on=?,active=1 WHERE id=?", (timestamp, posted, key))
                    continue
            payload = {k: job[k] for k in ("company", "title", "location", "description")}
            if duplicate and not payload["description"] and job.get("detail_unavailable"):
                payload["description"] = duplicate["description"]
            payload.update(url=url, requisition=requisition or key)
            term_hint = job.get("term_hint", "")
            if term_hint:
                payload["term_hint"] = term_hint
            encoded = json.dumps(payload, sort_keys=True)
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
            conn.execute(
                """INSERT INTO jobs(id,company,requisition,title,location,url,description,source,
                                    first_seen,last_seen,fingerprint,active,term_hint,posted_on)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)
                   ON CONFLICT(id) DO UPDATE SET company=excluded.company,requisition=excluded.requisition,
                   title=excluded.title,location=excluded.location,
                   url=excluded.url,description=excluded.description,source=excluded.source,
                   last_seen=excluded.last_seen,fingerprint=excluded.fingerprint,active=1,
                   term_hint=excluded.term_hint,posted_on=excluded.posted_on""",
                (key, payload["company"], payload["requisition"], payload["title"], payload["location"],
                 url, payload["description"], source, timestamp, timestamp, fingerprint, term_hint, posted),
            )
            conn.execute("INSERT OR IGNORE INTO job_versions VALUES (?, ?, ?, ?)",
                         (key, fingerprint, encoded, timestamp))
            if not duplicate or duplicate["fingerprint"] != fingerprint:
                conn.execute("INSERT INTO job_changes(job_id,fingerprint,seen_at) VALUES (?,?,?)",
                             (key, fingerprint, timestamp))
            if owner and not duplicate and (company in watchlist or any(matches(payload, rule) for rule in searches)):
                conn.execute("INSERT OR IGNORE INTO alerts(owner,job_id,created_at) VALUES (?,?,?)",
                             (owner, key, timestamp))
        cutoff = timestamp if complete else (datetime.fromisoformat(timestamp) - timedelta(days=stale_days)).isoformat()
        conn.execute("UPDATE job_sources SET active=0 WHERE source=? AND active=1 AND last_seen<?", (source, cutoff))
        conn.execute("""UPDATE jobs SET active=0 WHERE active=1
                        AND id IN (SELECT job_id FROM job_sources WHERE source=?)
                        AND (NOT EXISTS (SELECT 1 FROM job_sources WHERE job_id=jobs.id AND active=1)
                             OR EXISTS (SELECT 1 FROM job_sources
                                        WHERE job_id=jobs.id AND source=jobs.source AND active=0
                                        AND source NOT LIKE 'boards:%'))""", (source,))
        conn.execute("UPDATE sources SET last_attempt=?,last_success=?,error=NULL,count=? WHERE id=?",
                     (timestamp, timestamp, len(seen), source))
    return len(seen)
