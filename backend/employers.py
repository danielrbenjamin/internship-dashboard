import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from math import ceil
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

from .catalog import INTERNSHIP
from .posting_text import posting_markdown


def posting(company, requisition, title, location, url, description, **fields):
    return {"company": company, "requisition": requisition, "title": title, "location": location,
            "url": url, "description": description, **fields}


def text(html):
    return posting_markdown(html)


def fetch(client, url, params=None, *, payload=None):
    method = "POST" if payload is not None else "GET"
    origin = urlsplit(url)
    for _ in range(5):
        with client.stream(method, url, params=params or None, json=payload, follow_redirects=False) as response:
            if response.is_redirect and "location" in response.headers:
                url = urljoin(str(response.url), response.headers["location"])
                target = urlsplit(url)
                if (target.scheme != "https" or target.netloc != origin.netloc or method != "GET"):
                    raise ValueError("unexpected source redirect")
                params = None
                continue
            response.raise_for_status()
            body = bytearray()
            for part in response.iter_bytes():
                body.extend(part)
                if len(body) > 25_000_000:
                    raise ValueError("source exceeds response limit")
            return bytes(body)
    raise ValueError("too many source redirects")


def paged(read_page, max_pages=20):
    seen = set()
    expected_pages = None
    for page in range(1, max_pages + 1):
        rows, total = read_page(page)
        if not rows and total == 0 and page == 1:
            return
        unique = {row["requisition"]: row for row in rows if row["requisition"] not in seen}
        if not unique:
            raise ValueError("incomplete or repeated search page")
        if expected_pages is None:
            expected_pages = ceil(total / len(rows))
        seen.update(unique)
        yield from unique.values()
        if page >= expected_pages:
            return
    raise ValueError("search exceeded page limit")


def greenhouse(client, source):
    board = quote(source["board"], safe="")
    base = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    if source.get("id", "").startswith("ats:"):
        try:
            raw = json.loads(fetch(client, base, {"content": "true"}))
        except ValueError as exc:
            if str(exc) != "source exceeds response limit":
                raise
        else:
            return [posting(source["company"], row.get("internal_job_id") or row["id"], row["title"],
                            (row.get("location") or {}).get("name", ""), row["absolute_url"],
                            text(row.get("content")), posted_on=row.get("first_published"))
                    for row in raw["jobs"] if INTERNSHIP.search(row["title"])]
    rows = json.loads(fetch(client, base))["jobs"]
    matching = [row for row in rows if INTERNSHIP.search(row["title"])]

    def load(row):
        info = json.loads(fetch(client, f"{base}/{int(row['id'])}"))
        return posting(source["company"], row.get("internal_job_id") or row["id"], row["title"],
                       (row.get("location") or {}).get("name") or "", row["absolute_url"],
                       text(info.get("content")), posted_on=info.get("first_published") or row.get("first_published"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(load, matching))


def google(client, source):
    base = "https://www.google.com/about/careers/applications/"
    company = source["company"]

    def read(page):
        html = BeautifulSoup(fetch(client, base + "jobs/results/", {"q": "intern", "page": page}), "html.parser")
        script = next((tag.string for tag in html.find_all("script")
                       if (tag.string or "").startswith("AF_initDataCallback({key: 'ds:1'")), None)
        if not script:
            raise ValueError("Google search data missing")
        data, _ = json.JSONDecoder().raw_decode(script.split("data:", 1)[1].lstrip())
        links = {}
        for anchor in html.select("a[href]"):
            match = re.search(r"jobs/results/(\d+)[^?]*", anchor["href"])
            if match:
                links[match[1]] = urljoin(base, match[0])
        rows = []
        for row in data[0] or []:
            description = "\n\n".join(text(row[i][1]) for i in (4, 10, 15, 3)
                                        if len(row) > i and row[i] and row[i][1])
            rows.append(posting(company, row[0], row[1],
                                "; ".join(value[0] for value in row[9] or [] if value[0]),
                                links.get(row[0], base + "jobs/results/" + row[0]), description))
        return rows, int(data[2])

    return list(paged(read))


def apple(client, source):
    base = "https://jobs.apple.com/en-us/"
    company = source["company"]

    def read(page):
        html = BeautifulSoup(fetch(client, base + "search", {
            "team": "internships-STDNT-INTRN", "page": page,
        }), "html.parser")
        for script in html.find_all("script"):
            content = script.string or ""
            if content.startswith("window.__staticRouterHydrationData") and "searchResults" in content:
                encoded, _ = json.JSONDecoder().raw_decode(content.split("JSON.parse(", 1)[1])
                data = json.loads(encoded)["loaderData"]["search"]
                break
        else:
            raise ValueError("Apple search data missing")
        rows = []
        for row in data["searchResults"]:
            locations = []
            for loc in row["locations"]:
                labels = (loc.get("city") or loc.get("name"), loc.get("stateProvince"), loc.get("countryName"))
                locations.append(", ".join(dict.fromkeys(label for label in labels if label)))
            position = quote(str(row["positionId"]), safe="")
            slug = quote(row["transformedPostingTitle"], safe="")
            rows.append(posting(company, row["positionId"], row["postingTitle"],
                                "; ".join(dict.fromkeys(locations)), f"{base}details/{position}/{slug}",
                                text(row.get("jobSummary")), internship=True, posted_on=row.get("postDateInGMT")))
        return rows, int(data["totalRecords"])

    return list(paged(read))


def amd(client, source):
    base = "https://careers.amd.com/"

    def read(page):
        payload = json.loads(fetch(client, base + "api/jobs", {
            "keywords": "intern", "limit": 100, "page": page,
        }))
        rows = []
        for entry in payload["jobs"]:
            row = entry["data"]
            parts = (row.get("city"), row.get("state"), row.get("country"))
            location = ", ".join(dict.fromkeys(part for part in parts if part))
            role = quote(str(row["slug"]), safe="")
            rows.append(posting(source["company"], row["req_id"], row["title"], location,
                                f"{base}careers-home/jobs/{role}", text(row.get("description")),
                                posted_on=row.get("posted_date")))
        return rows, int(payload["totalCount"])

    return list(paged(read))


def disney(client, source):
    base = "https://www.disneycareers.com"
    anchors = {}
    for keyword in ("intern", "imagineering"):
        listing = BeautifulSoup(fetch(client, f"{base}/en/search-jobs/{keyword}/"), "html.parser")
        results = listing.select_one("#search-results[data-total-job-results]")
        if results is None:
            raise ValueError("Disney search results missing")
        pages = min(4, int(results["data-total-pages"]))
        for page in range(1, pages + 1):
            if page > 1:
                payload = json.loads(fetch(client, base + "/en/search-jobs/results", {
                    "CurrentPage": page, "RecordsPerPage": results["data-records-per-page"], "Keywords": keyword,
                    "SearchResultsModuleName": "Search Results", "SearchFiltersModuleName": "Search Filters",
                    "SearchType": 1, "SortCriteria": 0, "SortDirection": 1, "ResultsType": 1,
                }))
                listing = BeautifulSoup(payload["results"], "html.parser")
            entries = [anchor for anchor in listing.select("a[data-job-id][href]") if anchor.select_one("h2")]
            if not entries and int(results["data-total-job-results"]):
                raise ValueError("Disney listing content missing")
            for anchor in entries:
                if INTERNSHIP.search(anchor.h2.get_text(strip=True)):
                    anchors[anchor["data-job-id"]] = anchor

    def load(anchor):
        url = urljoin(base, anchor["href"])
        if not url.startswith(base + "/en/job/"):
            raise ValueError("unexpected Disney posting URL")
        h = BeautifulSoup(fetch(client, url), "html.parser")
        detail = h.select_one(".ats-description__content")
        if detail is None:
            raise ValueError("Disney posting description missing")
        brand = anchor.select_one(".job-brand").get_text(strip=True)
        company = "Walt Disney Imagineering" if brand == "Walt Disney Imagineering" else source["company"]
        date_label = h.select_one(".job-date")
        posted = date_label.get_text(" ", strip=True).removeprefix("Date posted").strip() if date_label else ""
        return posting(company, anchor["data-job-id"], anchor.h2.get_text(strip=True),
                       anchor.select_one(".job-location").get_text(" ", strip=True), url, text(str(detail)),
                       posted_on=posted.replace(".", ""))

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(load, anchors.values()))


def amazon(client, source):
    base = "https://www.amazon.jobs"
    results = {}
    for query in ("mechanical engineering intern", "hardware development intern"):
        payload = json.loads(fetch(client, base + "/en/search.json", {"base_query": query, "result_limit": 25}))
        for row in payload["jobs"]:
            if row.get("is_intern") or INTERNSHIP.search(row["title"]):
                description = "\n\n".join(text(row.get(key)) for key in (
                    "description", "basic_qualifications", "preferred_qualifications",
                ) if row.get(key))
                results[row["id"]] = posting(source["company"], row["id"], row["title"],
                                             row.get("location") or "", urljoin(base, row["job_path"]),
                                             description, internship=bool(row.get("is_intern")), posted_on=row.get("posted_date"))
    return list(results.values())


def workday(client, source):
    host = source["host"]
    if not re.fullmatch(r"[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com", host):
        raise ValueError("Invalid Workday host")
    site = quote(source["board"], safe="")
    base = f"https://{host}"
    endpoint = f"{base}/wday/cxs/{host.split('.', 1)[0]}/{site}"
    queries = ("intern", "co-op") if source.get("id", "").startswith("ats:") else (source.get("query", "mechanical intern"),)
    listings = {}
    for query in queries:
        seen = set()
        for offset in range(0, 60, 20):
            page = json.loads(fetch(client, endpoint + "/jobs", payload={
                "appliedFacets": {}, "limit": 20, "offset": offset, "searchText": query,
            }))
            rows = page["jobPostings"]
            paths = {row["externalPath"] for row in rows}
            listings.update((row["externalPath"], row) for row in rows)
            if len(rows) < 20 or paths <= seen:
                break
            seen.update(paths)
    matches = []
    details_available = True
    for row in listings.values():
        title, path = row["title"], row["externalPath"]
        if not INTERNSHIP.search(title):
            continue
        if not path.startswith("/job/"):
            raise ValueError("Unexpected Workday posting path")
        description = ""
        posted = None
        age = re.fullmatch(r"Posted (Today|Yesterday|(\d+) Days? Ago)", row.get("postedOn", ""), re.IGNORECASE)
        if age:
            days = int(age[2]) if age[2] else int(age[1].casefold() == "yesterday")
            posted = datetime.now(UTC).date() - timedelta(days=days)
        if details_available:
            try:
                detail = json.loads(fetch(client, endpoint + path))["jobPostingInfo"]
                description = text(detail.get("jobDescription"))
                posted = detail.get("startDate") or posted
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    continue
                if exc.response.status_code not in {403, 429}:
                    raise
                details_available = False
        location = row.get("locationsText") or ""
        if re.match(r"^(US|CA), [A-Z]{2}, ", location):
            country, region, city = location.split(", ", 2)
            location = f"{city}, {region}, {'United States' if country == 'US' else 'Canada'}"
        req = next(iter(row.get("bulletFields") or []), "")
        matches.append(posting(source["company"], req, title, location, f"{base}/{site}{path}", description,
                               detail_unavailable=not details_available, posted_on=posted))
    return matches


def smartrecruiters(client, source):
    board = quote(source["board"], safe="")
    endpoint = f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
    results = {}
    for country in source.get("countries", ["us", "ca"]):
        data = json.loads(fetch(client, endpoint, {"q": "intern", "country": country, "limit": 50}))
        for row in data["content"]:
            employment = (row.get("typeOfEmployment") or {}).get("label", "").casefold()
            if employment == "internship" or INTERNSHIP.search(row["name"]):
                results[row["id"]] = row

    def load(row):
        detail = json.loads(fetch(client, f"{endpoint}/{quote(str(row['id']), safe='')}"))
        sections = detail["jobAd"]["sections"]
        description = "\n\n".join(text(sections[key].get("text")) for key in (
            "jobDescription", "qualifications", "additionalInformation",
        ) if sections.get(key))
        location = row["location"]
        place = ", ".join(filter(None, (location.get("city"), location.get("region"), location.get("country"))))
        url = detail.get("postingUrl") or f"https://jobs.smartrecruiters.com/{board}/{row['id']}"
        return posting(source["company"], row.get("refNumber") or row["id"], row["name"],
                       place, url, description, internship=True, posted_on=row.get("releasedDate"))

    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(load, results.values()))


SIMPLIFY_INDEX = ("https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/"
                  "dev/.github/scripts/listings.json")
MECHANICAL = re.compile(
    r"\b(mechanical|mechatronics|robotics?|hardware|manufacturing|industrial engineering|thermal|"
    r"product design engineer(?:ing)?|systems integration|validation|test engineering|aerospace|"
    r"avionics|materials engineering|machining|tooling|automation engineer(?:ing)?|CAD|CFD|FEA|"
    r"engineering physics|reliability engineer(?:ing)?|vehicle dynamics|propulsion|packaging engineer(?:ing)?)\b",
    re.IGNORECASE,
)
TERM_SEASONS = {"winter": 0, "spring": 1, "summer": 2, "fall": 3, "autumn": 3}


def simplify_terms(terms, today):
    current = (today.year, (today.month - 1) // 3)
    future = []
    for term in terms:
        season, _, year = term.lower().partition(" ")
        if season in TERM_SEASONS and year.isdecimal() and (int(year), TERM_SEASONS[season]) >= current:
            future.append(term)
    return future


def community_link(value):
    if not isinstance(value, str):
        return "", ""
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        return "", ""
    host, path = url.hostname, url.path.rstrip("/")
    requisition = ""
    if host in {"jobs.lever.co", "jobs.ashbyhq.com"}:
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and re.fullmatch(r"[\da-f-]{36}", parts[1], re.IGNORECASE):
            path, requisition = "/" + "/".join(parts[:2]), parts[1]
    elif host == "www.tesla.com":
        match = re.fullmatch(r"/careers/search/job/(?:[\w-]+-)?(\d+)", path)
        if match:
            requisition = match[1]
    elif host == "jobs.apple.com":
        match = re.search(r"/details/(\d+)", path)
        if match:
            requisition = match[1]
    elif host.endswith(".google.com"):
        match = re.search(r"/jobs/results/(\d+)", path)
        if match:
            requisition = match[1]
    elif host == "www.amazon.jobs":
        match = re.search(r"/jobs/(\d+)", path)
        if match:
            requisition = match[1]
    return urlunsplit((url.scheme, url.netloc, path, url.query, "")), requisition


def simplify_index(client, source):
    return simplify_listings(json.loads(fetch(client, SIMPLIFY_INDEX)))


def simplify_listings(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("SimplifyJobs listing data missing")
    today = datetime.now(UTC)
    cutoff = (today - timedelta(days=60)).timestamp()
    results = []
    for row in rows:
        company = row["company_name"]
        if not row["active"] or not row["is_visible"] or not company or not row["title"]:
            continue
        tesla = company.casefold() == "tesla"
        if not (tesla or row["category"] == "Hardware" or MECHANICAL.search(row["title"])):
            continue
        terms = simplify_terms(row["terms"], today)
        has_named_term = any(term.split(" ", 1)[0].lower() in TERM_SEASONS for term in row["terms"])
        if not terms and (has_named_term or row["date_updated"] < cutoff):
            continue
        url, requisition = community_link(row["url"])
        if not url or (tesla and urlsplit(url).hostname != "www.tesla.com"):
            continue
        results.append(posting(company, requisition, row["title"], "; ".join(row["locations"]),
                               url, "", internship=True, term_hint=", ".join(terms), posted_on=row.get("date_posted")))
    return results


def mechanical_index(client, source):
    feed = json.loads(fetch(client, source["url"]))
    jobs = []
    for row in feed["jobs"]:
        if row["status"] != "open":
            continue
        url, requisition = community_link(row["url"])
        if url:
            jobs.append(posting(row["companyName"], requisition, row["title"], row["location"],
                                url, "", internship=True, posted_on=row.get("postedAt")))
    return jobs


def canadian_list(client, source):
    markdown = fetch(client, "https://raw.githubusercontent.com/Bobwillrule/Canadian-Internship-List/HEAD/README.md").decode()
    if "| Company | Role | Location | Apply | Posted |" not in markdown:
        raise ValueError("Canadian internship listing table missing")
    jobs = []
    for line in markdown.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            continue
        company, title, location, apply, posted = cells
        link = re.fullmatch(r"\[Apply\]\((https://.+)\)", apply)
        if link:
            url, requisition = community_link(link[1])
            if url:
                jobs.append(posting(company, requisition, title, location, url, "", internship=True, posted_on=posted))
    return jobs


def jobright_index(client, source):
    repo = "jobright-ai/2026-Engineer-Internship"
    commits = json.loads(fetch(client, f"https://api.github.com/repos/{repo}/commits", {"path": "README.md", "per_page": 1}))
    head = commits[0]
    snapshot = datetime.fromisoformat(head["commit"]["committer"]["date"]).date()
    markdown = fetch(client, f"https://raw.githubusercontent.com/{repo}/{head['sha']}/README.md").decode()
    if "| Date Posted |" not in markdown:
        raise ValueError("Jobright posting table missing")
    company = ""
    jobs = []
    for line in markdown.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            continue
        label, title, location, _, day = cells
        employer = re.fullmatch(r"\[(.+)\]\(https?://.+\)", label)
        if label != "↳":
            company = employer[1] if employer else label
        link = re.fullmatch(r"\[(.+)\]\((https://jobright\.ai/jobs/info/[a-zA-Z0-9]+)(?:\?[^)]*)?\)", title)
        if not link or not company:
            continue
        try:
            posted = datetime.strptime(f"{day} {snapshot.year}", "%b %d %Y").date()
            if posted > snapshot:
                posted = posted.replace(year=snapshot.year - 1)
        except ValueError:
            continue
        jobs.append(posting(company, "", link[1], location, link[2], "", internship=True, posted_on=posted))
    if not jobs:
        raise ValueError("Jobright returned no usable postings")
    return jobs


def speedy_index(client, source):
    url = source["url"]
    snapshot_day = None
    match = re.fullmatch(r"https://raw\.githubusercontent\.com/([\w-]+/[\w.-]+)/main/([\w.-]+)", url)
    if match:
        repo, filename = match.groups()
        commits = json.loads(fetch(client, f"https://api.github.com/repos/{repo}/commits",
                                   {"path": filename, "sha": "main", "per_page": 1}))
        commit = commits[0]
        snapshot_day = datetime.fromisoformat(commit["commit"]["committer"]["date"]).date()
        url = f"https://raw.githubusercontent.com/{repo}/{commit['sha']}/{filename}"
    markdown = fetch(client, url).decode("utf-8")
    columns = {}
    found_table = False
    jobs = []
    for line in markdown.splitlines():
        if not line.startswith("|"):
            columns = {}
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if {"Company", "Position", "Location", "Posting"}.issubset(cells):
            columns = {name: idx for idx, name in enumerate(cells)}
            found_table = True
            continue
        if not columns or len(cells) != len(columns):
            continue
        title = cells[columns["Position"]]
        location = cells[columns["Location"]]
        if source["region"] == "ca" and not re.search(r"\bCanada\b", location, re.IGNORECASE):
            continue
        link = BeautifulSoup(cells[columns["Posting"]], "html.parser").select_one("a[href]")
        if not link:
            continue
        url, requisition = community_link(link["href"])
        company = BeautifulSoup(cells[columns["Company"]], "html.parser").get_text(strip=True)
        if url and company:
            age = re.fullmatch(r"(\d{1,4})d", cells[columns["Age"]]) if "Age" in columns else None
            posted = snapshot_day - timedelta(days=int(age[1])) if snapshot_day and age else None
            jobs.append(posting(company, requisition, title, location, url, "", internship=True, posted_on=posted))
    if not found_table:
        raise ValueError("SpeedyApply internship table missing")
    return jobs


EMPLOYER_ADAPTERS = {"greenhouse": greenhouse, "google": google, "apple": apple, "amd": amd,
                     "speedy": speedy_index, "mechanical_index": mechanical_index, "jobright": jobright_index,
                     "canadian_list": canadian_list,
                     "disney": disney, "simplify": simplify_index, "amazon": amazon,
                     "workday": workday, "smartrecruiters": smartrecruiters}
