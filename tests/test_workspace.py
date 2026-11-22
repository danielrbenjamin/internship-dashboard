
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from test_catalog import POSTING

from backend import documents
from backend.catalog import import_jobs
from backend.config import Settings
from backend.discovery import run_source
from backend.main import create_app
from backend.mcp import SCOPE

SECRET = "test-only-session-key-that-is-at-least-32"
ORIGIN = {"Origin": "http://localhost:8000"}


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path, session_secret=SECRET, owner_subject="google|owner",
                               auth0_domain="example.auth0.com"))


def signed_session(app, client, subject, sid="session"):
    import base64
    import json

    app.state.db.execute("INSERT INTO sessions VALUES (?,?,?)", (sid, subject, time.time() + 3600))
    value = base64.b64encode(json.dumps({"sid": sid}).encode())
    client.cookies.set("session", TimestampSigner(SECRET).sign(value).decode())


def test_catalog_posting_window_and_overlapping_disciplines(app):
    today = datetime.now(UTC).date()
    rows = []
    for i, days in enumerate((0, 29, 30, None, -1)):
        rows.append({**POSTING, "title": "Mechanical Hardware Intern", "requisition": str(i),
                     "url": f"https://example.com/{i}",
                     "posted_on": today - timedelta(days=days) if days is not None else None})
    import_jobs(app.state.db, "official", rows)
    client = TestClient(app)
    for discipline in ("Mechanical", "Hardware"):
        for map_view in ("true", "false"):
            result = client.get("/api/jobs", params={"discipline": discipline, "map_view": map_view}).json()
            assert [job["requisition"] for job in result["jobs"]] == ["0", "1"]
    assert client.get("/api/jobs?discipline=Software").json()["jobs"] == []
    assert client.get("/api/analytics").json()["totals"]["openings"] == 2


def test_owner_boundary_and_revocation(app):
    db = app.state.db
    import_jobs(db, "fixture", [POSTING])
    guest, owner, other = (TestClient(app) for _ in range(3))
    job = guest.get("/api/jobs").json()["jobs"][0]["id"]
    assert "description" not in guest.get(f"/api/jobs/{job}").json()
    assert guest.get("/api/owner/settings").status_code == 401
    assert guest.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401
    signed_session(app, other, "google|other", "another")
    assert other.get("/api/owner/settings").status_code == 401
    signed_session(app, owner, "google|owner")
    assert "description" in owner.get(f"/api/jobs/{job}").json()
    path = f"/api/owner/jobs/{job}/application"
    assert owner.put(path, json={"status": "shortlisted"}).status_code == 403
    assert owner.put(path, headers=ORIGIN, json={"status": "shortlisted", "notes": "Private"}).status_code == 200
    assert guest.get("/api/owner/applications").status_code == 401
    cookie = owner.cookies.get("session")
    assert owner.post("/auth/logout", headers=ORIGIN, content=b"").status_code == 200
    other.cookies.set("session", cookie)
    assert other.get("/api/owner/applications").status_code == 401


def test_submitted_files_survive_restart(app, monkeypatch):
    db = app.state.db
    import_jobs(db, "fixture", [POSTING])
    owner = TestClient(app)
    signed_session(app, owner, "google|owner")
    job = owner.get("/api/jobs").json()["jobs"][0]["id"]
    save = "/api/owner/jobs/" + job + "/application"
    app_id = owner.put(save, headers=ORIGIN, json={"status": "shortlisted"}).json()["id"]
    app_path = "/api/owner/applications/" + app_id

    def fixture_repo(directory, profile, token):
        (directory / "main.tex").write_text("  Original bullet\n", encoding="utf-8")
        return "a" * 40, "main.tex"

    monkeypatch.setattr(documents, "fetch_resume", fixture_repo)
    first = owner.post(app_path + "/resume", headers=ORIGIN, content=b"").json()["id"]
    doc_base = "/api/owner/documents/"
    pdf = b"%PDF-1.4\nfixture"

    def render(work, entry):
        assert (work / entry).read_text(encoding="utf-8") == "  Reviewed bullet\n"
        path = work / "preview.pdf"
        path.write_bytes(pdf)
        return path

    monkeypatch.setattr(documents, "render_pdf", render)
    edit = {"before": "  Original bullet\n", "after": "  Reviewed bullet\n"}
    preview_path = doc_base + first + "/preview"
    assert TestClient(app).post(preview_path, headers=ORIGIN, json=edit).status_code == 401
    preview = owner.post(preview_path, headers=ORIGIN, json=edit)
    assert preview.headers["content-type"] == "application/pdf" and preview.content == pdf
    assert len(owner.get(app_path).json()["documents"]) == 1
    second = owner.post(doc_base + first + "/edit", headers=ORIGIN,
                        json=edit).json()["id"]
    assert owner.get(doc_base + first + "/tex").text.splitlines() == ["  Original bullet"]
    assert owner.get(doc_base + second + "/tex").text.splitlines() == ["  Reviewed bullet"]
    assert owner.post(doc_base + second + "/compile", headers=ORIGIN, content=b"").status_code == 200
    assert owner.put(save, headers=ORIGIN, json={"status": "applied", "submitted_version": second}).status_code == 200
    restarted = TestClient(create_app(app.state.settings))
    restarted.cookies.set("session", owner.cookies.get("session"))
    assert restarted.get(app_path).json()["submitted_version"] == second
    assert restarted.get(doc_base + second + "/pdf").content == pdf
    assert restarted.get(doc_base + second + "/zip").content.startswith(b"PK")
    assert TestClient(app).get(doc_base + second + "/pdf").status_code == 401


def test_source_failure_keeps_previous_result(app, monkeypatch):
    from backend import discovery

    db = app.state.db
    db.execute("INSERT INTO sources(id,config) VALUES (?,?)", ("fixture", "{}"))
    import_jobs(db, "fixture", [POSTING])
    before = db.one("SELECT last_success FROM sources")["last_success"]

    def failure(*args):
        raise ValueError("no usable JobPosting structured data")

    monkeypatch.setattr(discovery, "collect", failure)
    run_source(db, app.state.settings, {"id": "fixture", "type": "structured"})
    assert db.one("SELECT active FROM jobs")["active"] == 1
    assert db.one("SELECT last_success FROM sources")["last_success"] == before
    assert db.one("SELECT error FROM sources")["error"]


def test_mcp_scope_and_authenticated_lookup(app, monkeypatch):
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(jwt.PyJWKClient, "get_signing_key_from_jwt",
                        lambda *args: type("SigningKey", (), {"key": key.public_key()})())
    owner = TestClient(app)
    signed_session(app, owner, "google|owner")
    import_jobs(app.state.db, "fixture", [POSTING])
    job = owner.get("/api/jobs").json()["jobs"][0]["id"]
    app_id = owner.put(f"/api/owner/jobs/{job}/application", headers=ORIGIN,
                       json={"status": "shortlisted"}).json()["id"]

    def call(method, params=None, scope=SCOPE, subject="google|owner"):
        stamp = int(time.time())
        token = jwt.encode({"sub": subject, "iat": stamp, "exp": stamp + 60, "scope": scope,
                            "iss": "https://example.auth0.com/", "aud": app.state.settings.mcp_audience},
                           key, algorithm="RS256")
        return owner.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
                          headers={"Authorization": "Bearer " + token})

    assert call("tools/list", scope="wrong").status_code == 403
    assert call("tools/list", subject="google|other").status_code == 403
    assert len(call("tools/list").json()["result"]["tools"]) == 2
    response = call("tools/call", {"name": "get_application", "arguments": {"id": app_id}})
    assert "shortlisted" in response.json()["result"]["content"][0]["text"]


def test_analytics_and_cover_letters_remain_owner_scoped(app, monkeypatch):
    guest, owner = TestClient(app), TestClient(app)
    signed_session(app, owner, "google|owner")
    import_jobs(app.state.db, "fixture", [POSTING])
    job = guest.get("/api/jobs").json()["jobs"][0]["id"]
    path = "/api/owner/jobs/" + job + "/application"
    app_id = owner.put(path, headers=ORIGIN, json={"status": "applied"}).json()["id"]
    public = guest.get("/api/analytics").json()
    assert public["totals"]["openings"] == 1 and "pipeline" not in public and "submitted" not in public
    private = owner.get("/api/analytics").json()
    assert private["pipeline"] == [{"status": "applied", "count": 1}]
    owner.put(path, headers=ORIGIN, json={"status": "applied", "notes": "Checked"})
    assert owner.get("/api/analytics").json()["submitted"][0]["count"] == 1
    route = f"/api/owner/applications/{app_id}"
    letter = {"content": "Dear team,\n\nI built a test fixture."}
    result = owner.post(route + "/cover-letters", headers=ORIGIN, json=letter)
    assert result.status_code == 201
    download = route + "/cover-letters/" + result.json()["id"]
    assert owner.get(download + "/txt").text == letter["content"]
    assert guest.get(download + "/txt").status_code == 401
    monkeypatch.setattr("backend.main.cover_letter_pdf", lambda _: b"%PDF-1.4\nfixture")
    assert owner.get(download + "/pdf").content.startswith(b"%PDF")
    assert owner.get(route).json()["cover_letters"][0]["content"] == letter["content"]
    assert owner.post(route + "/ai?cover_letter=true", headers=ORIGIN, content=b"").status_code == 422

def test_rank_to_application_reply_and_deadline(app):
    from backend.workflows import Reply, store_reply

    owner = TestClient(app)
    subject = "google|owner"
    signed_session(app, owner, subject)
    db = app.state.db
    import_jobs(db, "fixture", [{**POSTING,"company":"Test Robotics","title":"Mechanical Intern"}])
    assert owner.put("/api/owner/settings", headers=ORIGIN, json={
        "watchlist":["Test Robotics"],"experience":"CAD design",
        "searches":[{"name":"Mechanical","keywords":"mechanical"}]}).is_success
    match = owner.get("/api/owner/screening").json()["roles"][0]
    assert match["score"] == 100 and "Title: mechanical" in match["reasons"]
    config = {"auto_shortlist": True, "draft":True,"threshold":100}
    for _ in range(2):
        assert owner.put("/api/owner/screening",headers=ORIGIN,json=config).is_success
    assert len(db.all("SELECT id FROM ai_tasks")) == 1
    application, = owner.get("/api/owner/applications").json()
    owner.put("/api/owner/jobs/"+application["job_id"]+"/application", headers=ORIGIN, json={"status": "applied"}).raise_for_status()
    due = (datetime.now(UTC)+timedelta(hours=2)).isoformat(timespec="minutes")
    msg={"subject":"Test Robotics assessment", "body":f"Due: {due} https://example.org/assessment"}
    for _ in range(2):
        store_reply(db, subject, Reply(**msg), "mailbox-fixture")
    reply, = owner.get("/api/owner/replies").json()["items"]
    assert reply["application_id"] == application["id"] and reply["link"].endswith("/assessment")
    assert len(owner.get("/api/owner/reminders").json()) == 1
    path="/api/owner/replies/"+str(reply["id"])
    owner.put(path,headers=ORIGIN,json={"kind":"Interview","done":True,"application_id":application["id"]}).raise_for_status()
    assert owner.get("/api/owner/reminders").json() == []
    owner.post(path+"/outcome",headers=ORIGIN,json={}).raise_for_status()
    assert owner.get("/api/owner/applications").json()[0]["status"] == "interview"
    owner.post(path+"/outcome?undo=true",headers=ORIGIN,json={}).raise_for_status()
    assert owner.get("/api/owner/applications").json()[0]["status"] == "applied"


def track_fixture(app, owner, company, title, url):
    import_jobs(app.state.db, "fixture", [{**POSTING, "company": company, "title": title, "url": url}])
    job = app.state.db.one("SELECT id FROM jobs WHERE url=?", (url,))
    response = owner.put(f"/api/owner/jobs/{job['id']}/application", headers=ORIGIN, json={"status": "shortlisted"})
    return response.raise_for_status().json()


def test_legacy_captured_posting_stays_private(app):
    guest, owner = TestClient(app), TestClient(app)
    signed_session(app, owner, "google|owner")
    application = track_fixture(app, owner, "Acme", "Intern", "https://example.com/careers/42")
    app.state.db.execute("UPDATE jobs SET source='private:capture', active=0")
    item, = owner.get("/api/owner/applications").json()
    assert item["id"] == application["id"]
    assert owner.get("/api/jobs/" + item["job_id"]).is_success
    assert guest.get("/api/jobs/" + item["job_id"]).status_code == 404
    assert guest.get("/api/jobs").json()["jobs"] == []


def test_mailbox_email_deadline_parsing(app):
    from backend.workflows import read_message, store_reply

    client = TestClient(app)
    signed_session(app, client, "google|owner")
    email = b"From: hiring@example.org\r\nSubject: Example assessment\r\n\r\nDue October 25, 2026 at 8:41 PM PDT."
    store_reply(app.state.db, "google|owner", read_message(email), "mailbox-fixture")
    item, = client.get("/api/owner/replies").json()["items"]
    assert item["due"] == "2026-10-26T03:41:00+00:00"


def test_project_tree_multi_file_save_and_copy(app,monkeypatch):
    import zipfile

    from backend.documents import document_root

    owner=TestClient(app)
    signed_session(app,owner,"google|owner")
    def template(directory,profile,token):
        (directory/"styles").mkdir()
        (directory/"styles"/"resume.sty").write_text("% Original",encoding="utf-8")
        (directory/"main.tex").write_text("Original",encoding="utf-8")
        return "b"*40,"main.tex"
    monkeypatch.setattr(documents,"fetch_resume",template)
    base=owner.post("/api/owner/templates/resume",headers=ORIGIN,json={}).json()["id"]
    path="/api/owner/documents/"+base
    listing=owner.get(path+"/source").json()
    assert {i["path"] for i in listing["tree"]}=={"main.tex","styles/resume.sty"}
    assert owner.post(path+"/save",headers=ORIGIN,json={"files":{"../escape.tex":"text"}}).status_code==422
    updated=owner.post(path+"/save",headers=ORIGIN,json={"files":{"main.tex":"  Edited\n","styles/resume.sty":"% Updated"}}).json()["id"]
    assert owner.get("/api/owner/documents/"+updated+"/source").json()["ancestors"]==[base]
    assert owner.get(path+"/source").json()["content"]=="Original"
    assert owner.get("/api/owner/documents/"+updated+"/source").json()["content"]=="  Edited\n"
    app_id=track_fixture(app, owner, "Fixture", "Engineering Intern", "https://example.com/role")["id"]
    copied=owner.post("/api/owner/applications/"+app_id+"/from-template/resume",headers=ORIGIN,json={}).json()["id"]
    with zipfile.ZipFile(document_root(app.state.settings,copied)/"source.zip") as archive:
        assert archive.read("styles/resume.sty")==b"% Updated"


def test_referrals_match_edit_import_and_stage(app):
    import io

    from openpyxl import Workbook
    owner=TestClient(app)
    signed_session(app,owner,"google|owner")
    role=track_fixture(app, owner, "Acme", "Hardware Intern", "https://example.com/hw")
    wb=Workbook()
    wb.active.append(["Name","Company","Phone","LinkedIn"])
    wb.active.append(["Taylor Smith","ACME","555 0100","https://www.linkedin.com/in/fixture"])
    buf=io.BytesIO()
    wb.save(buf)
    for count in (1,0):
        assert owner.post("/api/owner/referrals/import",headers=ORIGIN,content=buf.getvalue()).json()=={"added":count}
    items=owner.get("/api/owner/referrals").json()
    contact,=items["contacts"]
    assert contact["linkedin"]=="https://www.linkedin.com/in/fixture"
    ask,=items["asks"]
    assert "Hardware Intern" in ask["text"] and "Taylor" in ask["text"]
    assert any(a["label"]=="Referral request" for a in owner.get("/api/owner/priorities").json())
    path=f"/api/owner/referrals/{contact['id']}/{role['id']}"
    assert owner.put(path,headers=ORIGIN,json={"text":"Personal request","status":"Asked"}).is_success
    assert owner.get("/api/owner/referrals").json()["asks"][0]["text"]=="Personal request"
    assert owner.get("/api/owner/priorities").json()==[]
    assert owner.delete("/api/owner/contacts/"+contact["id"],headers=ORIGIN).is_success
    assert owner.get("/api/owner/referrals").json()=={"contacts":[],"asks":[]}


def test_mail_connect_filter_and_undo(app,monkeypatch):
    from unittest.mock import MagicMock

    from backend import mail_accounts
    from backend.workflows import Reply, store_reply

    owner=TestClient(app)
    signed_session(app,owner,"google|owner")
    mailbox=MagicMock()
    mailbox.return_value.__enter__.return_value.select.return_value=("OK",[])
    monkeypatch.setattr(mail_accounts.imaplib,"IMAP4_SSL",mailbox)
    secret="dummy-mail-app-password"
    assert owner.post("/api/owner/mail/gmail",headers=ORIGIN,json={"email":"owner@example.org","password":secret}).is_success
    config=owner.get("/api/owner/mail").json()
    assert config["accounts"]==[{"address":"owner@example.org","provider":"Gmail"}]
    assert secret not in app.state.db.one("SELECT secret FROM mail_accounts")["secret"]
    assert not mail_accounts.application_message("Dinner tonight?","At our usual spot")
    role=track_fixture(app, owner, "Example", "CAD Intern", "https://example.com/cad")
    sample=Reply(subject="Example interview for CAD Intern",body="Engineering team interview")
    store_reply(app.state.db,"google|owner",sample,"fixture",automatic=True)
    item,=owner.get("/api/owner/replies").json()["items"]
    assert item["applied"] and item["application_id"]==role["id"]
    assert owner.post(f"/api/owner/replies/{item['id']}/outcome?undo=true",headers=ORIGIN,json={}).is_success
    store_reply(app.state.db,"google|owner",sample,"fixture",automatic=True)
    assert owner.get("/api/owner/applications").json()[0]["status"]=="shortlisted"
    assert owner.delete("/api/owner/mail/Gmail",headers=ORIGIN).is_success
    assert owner.get("/api/owner/mail").json()["accounts"]==[]

def test_microsoft_signin_and_filtered_sync(app, monkeypatch):
    import httpx

    from backend import mail_accounts

    owner=TestClient(app)
    signed_session(app,owner,"google|owner")
    steps=iter([{"device_code":"test-device","user_code":"USER-CODE","verification_uri":"https://microsoft.com/devicelogin","expires_in":600},
                {"error":"authorization_pending"},{"access_token":"test-access","refresh_token":"test-refresh"}])
    def fake_post(url,**kwargs):
        payload=next(steps)
        return httpx.Response(400 if "error" in payload else 200,json=payload,request=httpx.Request("POST",url))
    monkeypatch.setattr(mail_accounts.httpx,"post",fake_post)
    monkeypatch.setattr(mail_accounts.httpx,"get",lambda url,**kw:httpx.Response(200,json={"mail":"fixture@example.org"},request=httpx.Request("GET",url)))
    connected=owner.post("/api/owner/mail/microsoft",headers=ORIGIN,json={"client_id":"00000000-0000-0000-0000-000000000001"})
    assert connected.json()["code"]=="USER-CODE"
    finish="/api/owner/mail/microsoft/finish"
    assert owner.post(finish,headers=ORIGIN,json={}).json()=={"pending":True}
    assert owner.post(finish,headers=ORIGIN,json={}).json()=={"ok":True}
    def graph(req):
        if req.url.path.endswith("/token"):
            return httpx.Response(200,json={"access_token":"new-access","refresh_token":"new-refresh"})
        return httpx.Response(200,json={"value":[{"id":"job","subject":"Your application","body":{"content":"Your application for the role was received."}},
                                                {"id":"personal","subject":"Dinner","body":{"content":"See you at 8."}}]})
    original=httpx.Client
    monkeypatch.setattr(mail_accounts.httpx,"Client",lambda **kw:original(transport=httpx.MockTransport(graph)))
    for _ in range(2):
        assert owner.post("/api/owner/mail/check",headers=ORIGIN,json={}).json()["status"]=="Mailbox checked"
    items=owner.get("/api/owner/replies").json()["items"]
    assert [i["subject"] for i in items]==["Your application"]


def test_referral_people_are_private_and_ranked(app, monkeypatch):
    from backend import people_search

    owner = TestClient(app)
    guest = TestClient(app)
    signed_session(app, owner, "google|owner")
    path = "/api/owner/referrals/people?company=Acme&team=Mechanical+Engineering+Intern+Summer+2027"
    assert guest.get(path).status_code == 401
    app.state.settings.brave_search_api_key = ""
    assert owner.get(path).status_code == 503
    app.state.settings.brave_search_api_key = "fixture-key"
    mock_rows = [
        {"url": "https://www.linkedin.com/in/general", "title": "General Person - Acme"},
        {"url": "https://ca.linkedin.com/in/alumni", "title": "Alumni Person - Acme", "description": "University of British Columbia"},
        {"url": "https://www.linkedin.com/in/team", "title": "Team Person - Acme Mechanical Engineer"},
        {"url": "https://www.linkedin.com/in/team/?trk=duplicate", "title": "Team Person - Acme", "extra_snippets": ["UBC"]},
        {"url": "https://linkedin.com.example.org/in/unrelated", "title": "Mechanical Engineer at Acme"},
    ]
    import httpx

    client = httpx.AsyncClient
    def search(request):
        assert request.headers["X-Subscription-Token"] == "fixture-key"
        return httpx.Response(200, json={"web": {"results": mock_rows}})

    monkeypatch.setattr(people_search.httpx, "AsyncClient",
                        lambda **kwargs: client(transport=httpx.MockTransport(search), **kwargs))
    result = owner.get(path).json()["people"]
    assert [p["name"] for p in result] == ["Team Person", "Alumni Person", "General Person"]
    assert result[0]["team_match"] and result[0]["ubc"]
    reply = owner.post("/api/owner/contacts", headers=ORIGIN, json={
        "name": result[0]["name"], "linkedin": result[0]["url"], "company": "Acme",
    })
    assert reply.is_success

def test_automated_screening_prepares_both_templates(app, monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from backend import ai
    from backend.documents import document_root

    owner = TestClient(app)
    signed_session(app, owner, "google|owner")
    db = app.state.db
    import_jobs(db, "fixture", [{**POSTING, "company": "Test Robotics", "title": "Mechanical Intern"}])
    owner.put("/api/owner/settings", headers=ORIGIN, json={
        "experience": "Mechanical design", "watchlist": ["Test Robotics"],
        "searches": [{"name": "Mechanical", "keywords": "mechanical"}],
    }).raise_for_status()
    for kind in ("resume", "cover"):
        source = document_root(app.state.settings, kind) / "source"
        source.mkdir(parents=True)
        (source / "main.tex").write_text("Fixture source", encoding="utf-8")
        db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                   (kind, "google|owner", "templates", "fixture", "main.tex", "2026-01-01", 0, kind))

    def run(argv, **kwargs):
        Path(argv[argv.index("-o")+1]).write_text(json.dumps({
            "verdict": "apply", "match_score": 90, "engineering_fit": "Mechanical design",
            "assessment": [], "edits": [],
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(ai.subprocess, "run", run)
    monkeypatch.setattr(ai.shutil, "which", lambda name: "fixture-codex")

    owner.put("/api/owner/screening", headers=ORIGIN, json={
        "auto_shortlist": True, "smart": True, "prepare": True, "threshold": 75,
    }).raise_for_status()
    ai.run_next(db, app.state.settings)
    application, = owner.get("/api/owner/applications").json()
    assert application["status"] == "preparing"
    detail = owner.get("/api/owner/applications/"+application["id"]).json()
    assert {doc["kind"] for doc in detail["documents"]} == {"resume", "cover"}
    assert sum(task["status"] == "queued" for task in detail["ai"]) == 2
    owner.put("/api/owner/background/schedule?minutes=60", headers=ORIGIN, json={}).raise_for_status()
    owner.post("/api/owner/background/run", headers=ORIGIN, json={}).raise_for_status()
    background = owner.get("/api/owner/background").json()
    assert background["collection"]["requested"] and background["collection"]["interval_minutes"] == 60
