"""Learn employer board identifiers from public application links."""
import hashlib
import json
import re
from urllib.parse import parse_qs, urlsplit

HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "careers.smartrecruiters.com": "smartrecruiters",
}


def employer_board(link, company):
    if not isinstance(link, str) or not company:
        return None
    try:
        url = urlsplit(link)
        host = url.hostname or ""
        if url.scheme != "https" or url.netloc != host:
            return None
    except ValueError:
        return None
    parts = url.path.strip("/").split("/")
    kind = HOSTS.get(host)
    extra = {}
    if re.fullmatch(r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com", host):
        kind = "workday"
        if re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", parts[0], re.IGNORECASE):
            parts = parts[1:]
        extra = {"host": host, "query": "intern"}
    if not kind or not parts:
        return None
    slug = parts[0]
    if kind == "greenhouse" and slug == "embed":
        slug = parse_qs(url.query).get("for", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", slug) or slug.lower() in {"job", "jobs", "api", "embed"}:
        return None
    key = board_key({"type": kind, "host": extra.get("host", ""), "board": slug})
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    return {"id": f"ats:{kind}:{digest}", "type": kind, "board": slug, "company": company.strip(),
            "homepage": f"https://{host}/{slug}", "interval": 86400, **extra}


def board_key(source):
    return ":".join(source.get(k, "").lower() for k in ("type", "host", "board"))


def record_boards(db, origin, pairs):
    boards = {}
    for url, company in pairs:
        source = employer_board(url, company)
        if source:
            boards.setdefault(source["id"], source)
    with db.connect() as conn:
        conn.executemany("INSERT OR IGNORE INTO learned_boards VALUES (?,?,?)",
                         [(origin, key, json.dumps(source)) for key, source in boards.items()])
    return len(boards)


def learned_sources(db, configured):
    parents = {s["id"] for s in configured if s.get("discover_boards")}
    keys = {board_key(s) for s in configured if "board" in s}
    result = []
    for row in db.all("SELECT origin,config FROM learned_boards ORDER BY rowid"):
        if row["origin"] in parents:
            source = json.loads(row["config"])
            key = board_key(source)
            if key not in keys:
                result.append(source)
                keys.add(key)
    return result
