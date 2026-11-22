
import argparse
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .boards import learned_sources, record_boards
from .catalog import INTERNSHIP, RECENT, import_jobs
from .config import Settings
from .db import Database, now
from .employers import (
    EMPLOYER_ADAPTERS,
    SIMPLIFY_INDEX,
    community_link,
    fetch,
    posting,
    simplify_listings,
    text,
)

DEFAULT_SOURCES = [
    {"id": "google", "type": "google", "company": "Google"},
    {"id": "apple", "type": "apple", "company": "Apple"},
    {"id": "disney", "type": "disney", "company": "Disney"},
    {"id": "boards:simplify", "type": "simplify", "company": "SimplifyJobs", "interval": 3600},
    {"id": "boards:mechanical-2027", "type": "mechanical_index", "label": "2027 Mechanical Engineering Internships",
     "homepage": "https://github.com/thebargon/2027-Mechanical-Engineering-Internships",
     "url": "https://raw.githubusercontent.com/thebargon/2027-Mechanical-Engineering-Internships/main/data/listings.json",
     "interval": 21600},
    {"id": "amd", "type": "amd", "company": "AMD"},
    {"id": "amazon", "type": "amazon", "company": "Amazon", "interval": 1800},
    {"id": "nvidia", "type": "workday", "host": "nvidia.wd5.myworkdayjobs.com", "board": "NVIDIAExternalCareerSite",
     "company": "NVIDIA", "homepage": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", "interval": 3600},
    {"id": "gm", "type": "workday", "host": "generalmotors.wd5.myworkdayjobs.com", "board": "Careers_GM",
     "company": "General Motors", "homepage": "https://generalmotors.wd5.myworkdayjobs.com/Careers_GM", "interval": 3600},
    {"id": "bosch", "type": "smartrecruiters", "board": "BoschGroup", "company": "Bosch",
     "homepage": "https://jobs.bosch.com/", "interval": 3600},
    {"id": "neuralink", "type": "greenhouse", "board": "neuralink", "company": "Neuralink"},
    {"id": "zipline", "type": "greenhouse", "board": "flyzipline", "company": "Zipline"},
    {"id": "boards:jobright-engineering", "type": "jobright", "label": "Jobright engineering internships",
     "homepage": "https://github.com/jobright-ai/2026-Engineer-Internship", "interval": 21600},
    {"id": "boards:canadian-internships", "type": "canadian_list", "label": "Canadian Internship List",
     "homepage": "https://github.com/Bobwillrule/Canadian-Internship-List", "interval": 21600,
     "discover_boards": True},
]
BOARD_SEARCHES = [
    ("indeed", "Indeed", "Canada", "ca", "https://ca.indeed.com/jobs?q=mechanical+engineering+intern"),
    ("indeed", "Indeed", "USA", "us", "https://www.indeed.com/jobs?q=mechanical+engineering+intern"),
    ("glassdoor", "Glassdoor", "Canada", "ca", "https://www.glassdoor.ca/Job/index.htm"),
    ("glassdoor", "Glassdoor", "USA", "us", "https://www.glassdoor.com/Job/index.htm"),
    ("zip_recruiter", "ZipRecruiter", "USA", "us", "https://www.ziprecruiter.com/Jobs/Mechanical-Engineering-Intern"),
]
BOARD_SEARCHES += [
    (site, label, country, region, homepage)
    for site, label, homepage in (
        ("linkedin", "LinkedIn", "https://www.linkedin.com/jobs/"),
        ("google", "Google Jobs", "https://www.google.com/search?q=engineering+internship+jobs"),
    )
    for country, region in (("Canada", "ca"), ("USA", "us"))
]
SEARCH_TERMS = {
    "": "mechanical engineering intern",
    "-coop": "engineering co-op",
    "-hardware": "hardware engineering intern",
    "-robotics": "robotics intern",
    "-manufacturing": "manufacturing engineering intern",
}
DEFAULT_SOURCES += [
    {"id": f"directory:{slug}", "type": "board_index", "label": label, "url": url,
     "homepage": "https://github.com/" + "/".join(url.split("/")[3:5]),
     "discover_boards": True, "interval": 86400}
    for slug, label, url in (
        ("simplify", "Simplify employer boards", "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json"),
        ("speedy", "SpeedyApply employer boards", "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md"),
        ("jobops", "JobOps employer boards", "https://raw.githubusercontent.com/DaKheera47/job-ops/HEAD/orchestrator/src/server/config/career-boards-greenhouse.json"),
    )
]
DEFAULT_SOURCES += [
    {"id": f"boards:{site}-{region}{suffix}", "type": "jobspy", "sites": [site],
     "label": f"{name} · {region.upper()} · {query}",
     "query": query, "location": "Canada" if region == "ca" else "United States",
     "country": country, "homepage": homepage, "limit": 40, "interval": 21600}
    for suffix, query in SEARCH_TERMS.items()
    for site, name, country, region, homepage in BOARD_SEARCHES
]
DEFAULT_SOURCES += [
    {"id": f"boards:speedy-{discipline.lower()}-{region}", "type": "speedy", "region": region,
     "label": f"SpeedyApply {discipline} internships · {region.upper()}",
     "homepage": f"https://github.com/speedyapply/2027-{discipline}-College-Jobs",
     "url": f"https://raw.githubusercontent.com/speedyapply/2027-{discipline}-College-Jobs/main/{filename}",
     "interval": 21600}
    for discipline in ("AI", "SWE")
    for region, filename in (("us", "README.md"), ("ca", "INTERN_INTL.md"))
]


for source in DEFAULT_SOURCES:
    if source["type"] in {"simplify", "mechanical_index", "speedy", "jobspy"}:
        source["discover_boards"] = True


def structured_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from structured_nodes(item)
    elif isinstance(value, dict):
        if value.get("@type") == "JobPosting":
            yield value
        for key in ("@graph", "itemListElement", "item"):
            yield from structured_nodes(value.get(key))


def collect(client, source):
    kind = source["type"]
    company = source.get("company", "")
    if kind in EMPLOYER_ADAPTERS:
        return EMPLOYER_ADAPTERS[kind](client, source)
    if kind in {"lever", "ashby"}:
        board = quote(source["board"], safe="")
        if kind == "lever":
            raw = json.loads(fetch(client, f"https://api.lever.co/v0/postings/{board}?mode=json"))
            jobs = []
            for row in raw:
                categories = row.get("categories") or {}
                internship = (categories.get("commitment") or "").casefold() == "internship"
                if not internship and not INTERNSHIP.search(row["text"]):
                    continue
                posted = None
                link = row["hostedUrl"]
                if urlsplit(link).netloc == "jobs.lever.co":
                    try:
                        soup = BeautifulSoup(fetch(client, link), "html.parser")
                        for script in soup.select('script[type="application/ld+json"]'):
                            for node in structured_nodes(json.loads(script.get_text())):
                                posted = node.get("datePosted") or posted
                    except (httpx.HTTPError, ValueError):
                        pass
                jobs.append(posting(company, row["id"], row["text"], categories.get("location", ""), link,
                                    row.get("descriptionPlain", "")[:40000], internship=internship, posted_on=posted))
            return jobs
        raw = json.loads(fetch(client, f"https://api.ashbyhq.com/posting-api/job-board/{board}"))
        return [posting(company, row["jobUrl"].rstrip("/").split("/")[-1], row["title"],
                        row.get("location", ""), row["jobUrl"], row.get("descriptionPlain", "")[:40000],
                        internship=row.get("employmentType") == "Intern",
                        posted_on=row.get("publishedAt")) for row in raw["jobs"] if row.get("isListed") is not False]
    if kind == "jobspy":
        from jobspy import scrape_jobs
        google_options = {}
        if "google" in source["sites"]:
            google_options["google_search_term"] = f"{source['query']} jobs near {source['location']}"
        frame = scrape_jobs(site_name=source["sites"], search_term=source["query"],
                            location=source["location"], country_indeed=source.get("country", "USA"),
                            results_wanted=source.get("limit", 30), hours_old=720, **google_options)
        jobs = []
        for row in frame.astype(object).where(frame.notna(), "").to_dict("records"):
            if row.get("company") and row.get("title"):
                url, requisition = community_link(row.get("job_url_direct") or row.get("job_url"))
                if url:
                    jobs.append(posting(row["company"], requisition, row["title"], row.get("location", ""),
                                        url, text(row.get("description")), posted_on=row.get("date_posted")))
        if not jobs and (errors := frame.attrs.get("errors")):
            detail = " ".join(map(str, errors.values())) if isinstance(errors, dict) else str(errors)
            if "429" in detail:
                raise ValueError("Board rate limited the search (HTTP 429)")
            detail = re.sub(r"https?://\S+", "", detail)
            raise ValueError("Board search failed: " + " ".join(detail.split())[:180])
        if not jobs and ("errors" not in frame.attrs or not frame.empty):
            raise ValueError("board produced no usable results")
        return jobs
    if kind != "structured":
        raise ValueError("unsupported source type")
    listing = source["url"]
    soup = BeautifulSoup(fetch(client, listing), "html.parser")
    rows = read_structured_postings(soup, company, listing)
    if not rows:
        detail_pattern = {
            "disney": r"^/job/", "google": r"/jobs/results/\d", "apple": r"/details/\d",
            "amd": r"/jobs/\d",
        }.get(source["id"])
        if detail_pattern:
            links = {}
            for anchor in soup.select("a[href]"):
                url = urljoin(listing, anchor["href"])
                parsed = urlsplit(url)
                if (parsed.netloc == urlsplit(listing).netloc and parsed.scheme == "https"
                    and re.search(detail_pattern, parsed.path)
                    and re.search(r"intern|co[- ]?op", anchor.get_text(), re.IGNORECASE)):
                    links[url] = None
            for url in list(links)[:20]:
                detail = BeautifulSoup(fetch(client, url), "html.parser")
                rows.extend(read_structured_postings(detail, company, url, detail=True))
    if not rows:
        raise ValueError("no usable JobPosting structured data")
    return rows


def read_structured_postings(soup, company, page, detail=False):
    rows = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(script.get_text())
        except ValueError:
            continue
        for item in structured_nodes(parsed):
            address = item.get("jobLocation", [])
            if isinstance(address, dict):
                address = [address]
            places = []
            for place in address:
                value = place.get("address", {})
                if isinstance(value, dict):
                    places.append(", ".join(str(value[k]) for k in
                                            ("addressLocality", "addressRegion", "addressCountry") if value.get(k)))
            identifier = item.get("identifier") or {}
            requisition = identifier.get("value", "") if isinstance(identifier, dict) else str(identifier)
            rows.append(posting(company, requisition, item["title"], "; ".join(places),
                                urljoin(page, item.get("url") or page), text(item.get("description")),
                                posted_on=item.get("datePosted")))
    return rows if detail else [row for row in rows if row["url"] != page]


def load_sources(settings):
    config = settings.data_dir / "sources.json"
    return json.loads(config.read_text(encoding="utf-8")) if config.exists() else DEFAULT_SOURCES


def run_source(db, settings, source):
    source_id = source["id"]
    try:
        with httpx.Client(timeout=18, follow_redirects=False, trust_env=False,
                          headers={"User-Agent": "InternshipDashboard/0.1"}) as client:
            if source["type"] == "board_index":
                if source["url"].endswith(".md"):
                    jobs = EMPLOYER_ADAPTERS["speedy"](client, {**source, "region": "us"})
                    pairs = [(job["url"], job["company"]) for job in jobs]
                else:
                    raw = json.loads(fetch(client, source["url"]))
                    pairs = [(row.get("url") or row.get("greenhouseUrl"), row.get("company_name") or row.get("label"))
                             for row in raw]
                count = record_boards(db, source_id, pairs)
                if not count:
                    raise ValueError("No supported boards in employer index")
                stamp = now()
                db.execute("UPDATE sources SET last_attempt=?,last_success=?,error=NULL,count=? WHERE id=?",
                           (stamp, stamp, count, source_id))
                return source_id, f"{count} employer boards"
            if source["type"] == "simplify" and source.get("discover_boards"):
                raw = json.loads(fetch(client, SIMPLIFY_INDEX))
                jobs = simplify_listings(raw)
                pairs = ((row.get("url"), row.get("company_name")) for row in raw)
                record_boards(db, source_id, pairs)
            else:
                jobs = collect(client, source)
                if source.get("discover_boards"):
                    record_boards(db, source_id, ((job["url"], job["company"]) for job in jobs))
        count = import_jobs(db, source_id, jobs, settings.owner_subject,
                            complete=source["type"] in {"greenhouse", "lever", "ashby", "simplify",
                                                        "speedy", "mechanical_index", "canadian_list"},
                            stale_days=max(1, int(source.get("stale_days", 7))))
        return source_id, f"{count} internship postings"
    except (httpx.HTTPError, ValueError, TypeError, LookupError, AttributeError, ImportError, OSError,
            sqlite3.IntegrityError) as exc:
        error = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
        if type(exc) is ValueError:
            error = str(exc)
        if isinstance(exc, ImportError) and source["type"] == "jobspy":
            error = "JobSpy is not installed"
        db.execute("UPDATE sources SET last_attempt=?,error=? WHERE id=?", (now(), error, source_id))
        return source_id, error


def run_once(settings, db, force=False, selected=None):
    due = []
    sources = load_sources(settings)
    sources = [*sources, *learned_sources(db, sources)]
    for source in sources:
        if not re.fullmatch(r"[a-zA-Z0-9:_-]{1,80}", source["id"]):
            raise ValueError("Invalid source identifier")
    enabled = {source["id"] for source in sources}
    if len(enabled) != len(sources):
        raise ValueError("Duplicate source identifier")
    if selected and not set(selected) <= enabled:
        raise ValueError("Unknown source: " + ", ".join(sorted(set(selected) - enabled)))
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for row in conn.execute("SELECT id FROM sources WHERE enabled=1").fetchall():
            if row["id"] not in enabled:
                conn.execute("UPDATE sources SET enabled=0 WHERE id=?", (row["id"],))
                conn.execute("UPDATE job_sources SET active=0 WHERE source=?", (row["id"],))
                conn.execute("""UPDATE jobs SET active=0 WHERE active=1
                                AND id IN (SELECT job_id FROM job_sources WHERE source=?)
                                AND NOT EXISTS (SELECT 1 FROM job_sources
                                                WHERE job_id=jobs.id AND active=1)""", (row["id"],))
        for source in sources:
            conn.execute("""INSERT INTO sources(id,config) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET
                            last_attempt=CASE WHEN sources.config<>excluded.config OR sources.enabled=0
                                              THEN NULL ELSE sources.last_attempt END,
                            config=excluded.config,enabled=1""", (source["id"], json.dumps(source)))
    attempts = {row["id"]: row for row in db.all("SELECT id,last_attempt,error FROM sources WHERE enabled=1")}
    pending_boards = []
    clock = datetime.now(UTC)
    for source in sources:
        if source["type"] == "reference" or (selected and source["id"] not in selected):
            continue
        state = attempts[source["id"]]
        previous, error = state["last_attempt"], state["error"] or ""
        interval = max(300, int(source.get("interval", 1800 if source["type"] == "jobspy" else 600)))
        if "HTTP 429" in error:
            interval = max(interval, 12 * 3600)
        elif source["type"] == "jobspy" and ("status code 403" in error or "no job data returned" in error):
            interval = max(interval, 86400)
        elif source["id"].startswith("ats:") and error in {"HTTP 403", "HTTP 404", "HTTP 422"}:
            interval = max(interval, 3 * 86400)
        if force or not previous or (clock - datetime.fromisoformat(previous)).total_seconds() >= interval:
            if source["id"].startswith("ats:"):
                pending_boards.append(source)
            else:
                due.append(source)
    pending_boards.sort(key=lambda source: attempts[source["id"]]["last_attempt"] or "")
    if not (force or selected):
        productive = {row["source"] for row in db.all("""SELECT DISTINCT s.source
            FROM job_sources s JOIN jobs j ON j.id=s.job_id
            WHERE s.source LIKE 'ats:%' AND s.active=1 AND j.active=1 AND """ + RECENT)}
        proven = [source for source in pending_boards if source["id"] in productive]
        exploration = [source for source in pending_boards if source["id"] not in productive]
        pending_boards = proven[:80] + exploration[:40]
    # Keep large ATS sweeps from delaying the board and collection feeds. Run each
    # JobSpy provider's queries serially to avoid bursts against a single service.
    with ThreadPoolExecutor(max_workers=8) as pool, ThreadPoolExecutor(max_workers=6) as feeds:
        boards = pool.map(lambda source: run_source(db, settings, source), pending_boards)
        providers = {}
        for source in due:
            key = tuple(source["sites"]) if source["type"] == "jobspy" else source["id"]
            providers.setdefault(key, []).append(source)
        jobs = feeds.map(lambda group: [run_source(db, settings, source) for source in group], providers.values())
        return [result for group in jobs for result in group] + list(boards)


def main():

    from .ai import run_next, update_login
    from .codex_usage import refresh_usage

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--force", action="store_true", help="Poll every configured source immediately")
    parser.add_argument("--source", action="append", help="Limit a one-time check to these source IDs")
    args = parser.parse_args()
    if args.source and not args.once:
        parser.error("--source requires --once")
    settings = Settings()
    settings.validate_runtime()
    db = Database(Path(settings.data_dir) / "dashboard.sqlite3")
    def collect_due():
        for source, result in run_once(settings, db, force=args.force, selected=args.source):
            print(f"{now()} {source}: {result}", flush=True)

    if args.once:
        collect_due()
        return
    from .mail_accounts import sync_accounts
    from .workflows import auto_screen

    collection_finished = None
    login_at = workflow_at = 0.0
    login = "unknown"
    with ThreadPoolExecutor(max_workers=1) as pool:
        collection = None
        while True:
            if collection and collection.done():
                error = None
                try:
                    collection.result()
                except (OSError, ValueError, sqlite3.Error) as exc:
                    error = type(exc).__name__
                collection = None
                args.force = False
                collection_finished = time.monotonic()
                if settings.owner_subject:
                    db.execute("UPDATE worker_controls SET finished=?,error=? WHERE owner=?", (now(), error, settings.owner_subject))
                workflow_at = 0.0
            control = db.one("SELECT * FROM worker_controls WHERE owner=?", (settings.owner_subject,)) or {}
            interval = control.get("interval_minutes", 0) * 60 or settings.worker_interval
            if collection is None and (
                control.get("requested") or collection_finished is None or time.monotonic() - collection_finished >= max(60, interval)
            ):
                if settings.owner_subject:
                    db.execute("""INSERT INTO worker_controls(owner,interval_minutes,started) VALUES (?,?,?)
                                ON CONFLICT(owner) DO UPDATE SET requested=0,started=excluded.started,finished=NULL,error=NULL""",
                               (settings.owner_subject, max(5, settings.worker_interval // 60), now()))
                collection = pool.submit(collect_due)
            if time.monotonic() >= login_at:
                login = update_login(db, settings)
                login_at = time.monotonic() + 30
            if settings.owner_subject and time.monotonic() >= workflow_at:
                workflow_at = time.monotonic() + 300
                auto_screen(db, settings.owner_subject)
                sync_accounts(db, settings, settings.owner_subject)
            if login == "connected":
                refresh_usage(db, settings)
                run_next(db, settings)
            time.sleep(4)


if __name__ == "__main__":
    main()
