import json
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from backend.boards import employer_board, learned_sources, record_boards
from backend.db import Database
from backend.employers import greenhouse, mechanical_index, paged, simplify_index, speedy_index


def test_discovered_boards_persist_and_respect_config(tmp_path):
    db = Database(tmp_path / "jobs.sqlite3")
    origin = {"id": "collection", "discover_boards": True}
    links = [("https://jobs.lever.co/example/posting", "Example"),
             ("https://jobs.lever.co/example/second", "Example"),
             ("https://example.wd5.myworkdayjobs.com/en-US/Careers/job/post", "Example"),
             ("https://job-boards.greenhouse.io.evil.example/foo", "Invalid")]
    assert record_boards(db, "collection", links) == 2
    assert record_boards(db, "collection", links) == 2
    configured = {"board": "example", "type": "lever"}
    boards = learned_sources(Database(db.path), [origin, configured])
    assert [(s["type"], s["board"]) for s in boards] == [("workday", "Careers")]
    assert learned_sources(db, [configured]) == []
    assert employer_board("https://boards.greenhouse.io/embed/job_app?for=abc&token=123", "ABC")["board"] == "abc"


def test_greenhouse_only_fetches_internship_details():
    paths = []

    def fetch(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/jobs"):
            role = {"location": {"name": "Vancouver, BC"}, "absolute_url": "https://example.com/roles"}
            return httpx.Response(200, json={"jobs": [
                {**role, "id": 1, "title": "Mechanical Engineering Intern"},
                {**role, "id": 2, "title": "Staff Engineer"},
            ]})
        assert request.url.path.endswith("/jobs/1")
        return httpx.Response(200, json={"content": "<p>Must be enrolled in a degree program.</p>"})

    with httpx.Client(transport=httpx.MockTransport(fetch)) as client:
        rows = greenhouse(client, {"board": "fixture", "company": "Fixture"})
    assert len(paths) == 2
    assert rows[0]["description"] == "Must be enrolled in a degree program."


def test_collection_columns_and_application_links():
    table = b"""| Company | Position | Location | Posting | Age |
| <strong>Example</strong> | Robotics Co-op | Toronto, Canada | <a href="https://example.ca/1">Apply</a> | 2d |
| Other | Hardware Intern | London, UK | <a href="https://example.uk/2">Apply</a> | 1d |
| Closed | Design Intern | Ottawa, Canada | Closed | 5d |
"""
    with patch("backend.employers.fetch", return_value=table):
        jobs = speedy_index(None, {"url": "", "region": "ca"})
    assert [(job["company"], job["url"]) for job in jobs] == [("Example", "https://example.ca/1")]
    role = {"companyName": "Example", "title": "Mechanical Student", "location": "California",
            "url": "https://example.com/3", "status": "open"}
    feed = {"jobs": [role, {**role, "status": "closed"}]}
    with patch("backend.employers.fetch", return_value=json.dumps(feed).encode()):
        assert [job["title"] for job in mechanical_index(None, {"url": ""})] == ["Mechanical Student"]


def test_paged_tolerates_overlap_and_rejects_a_repeated_page():
    pages = {1: ([{"requisition": "1"}, {"requisition": "2"}], 4),
             2: ([{"requisition": "2"}, {"requisition": "3"}], 4)}
    assert [row["requisition"] for row in paged(pages.__getitem__)] == ["1", "2", "3"]
    with pytest.raises(ValueError, match="repeated"):
        list(paged(lambda _: pages[1]))


def test_simplify_keeps_hardware_and_tesla_with_valid_links_and_terms():
    now = datetime.now(UTC)
    new_term = f"Summer {now.year + 1}"
    base = {"active": True, "is_visible": True, "date_updated": int(now.timestamp()),
            "company_name": "Fixture", "locations": ["Vancouver, BC"], "terms": [new_term],
            "category": "Software", "title": "Mobile Application Developer Intern"}
    job = "https://example.com/jobs/1"
    tesla = "https://www.tesla.com/careers/search/job/284593"
    feed = [{**base, "title": "Mechanical Design Intern", "url": job},
            {**base, "title": "Controls Intern", "category": "Hardware", "url": job},
            {**base, "company_name": "Tesla", "url": tesla},
            {**base, "url": job}, {**base, "category": "Hardware", "url": job, "terms": ["Summer 2025"]},
            {**base, "company_name": "Tesla", "url": job}]
    with patch("backend.employers.fetch", return_value=json.dumps(feed).encode()):
        jobs = simplify_index(None, {})
    assert [role["company"] for role in jobs] == ["Fixture", "Fixture", "Tesla"]
    assert jobs[-1]["requisition"] == "284593" and jobs[-1]["term_hint"] == new_term
    assert all(role["description"] == "" for role in jobs)
