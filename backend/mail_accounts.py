import base64
import hashlib
import imaplib
import json
import re
import ssl
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from pydantic import Field

from .db import now
from .models import Input
from .posting_text import posting_markdown
from .workflows import Owner, Reply, store_reply, sync_mail

MS = "https://login.microsoftonline.com/common/oauth2/v2.0"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Mail.Read"


class Gmail(Input):
    email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=250)
    password: str = Field(min_length=8, max_length=128)


class Microsoft(Input):
    client_id: UUID


def cipher(settings):
    return Fernet(
        base64.urlsafe_b64encode(hashlib.sha256(("mail-v1:" + settings.session_secret).encode()).digest())
    )


def put(db, settings, owner, provider, address, value):
    encrypted = cipher(settings).encrypt(json.dumps(value).encode()).decode()
    db.execute("INSERT OR REPLACE INTO mail_accounts VALUES(?,?,?,?)", (owner, provider, address, encrypted))


def get(db, settings, owner, provider):
    row = db.one("SELECT * FROM mail_accounts WHERE owner=? AND provider=?", (owner, provider))
    if not row:
        return None
    return row["address"], json.loads(cipher(settings).decrypt(row["secret"].encode()))


def application_message(subject, body):
    return bool(
        re.search(
            r"\b(your application|application (?:for|received|update|status)|thank you for applying|"
            r"interview|assessment|coding challenge|offer letter|pleased to offer|moving forward with other candidates|"
            r"we received your|regarding your candidacy)\b",
            subject + " " + body[:5000],
            re.IGNORECASE,
        )
    )


def sync_graph(db, settings, owner, auth):
    address, token = auth
    with httpx.Client(timeout=20, trust_env=False) as client:
        r = client.post(
            MS + "/token",
            data={
                "grant_type": "refresh_token",
                "client_id": token["client_id"],
                "refresh_token": token["refresh_token"],
            },
        )
        r.raise_for_status()
        access = r.json()
        if access.get("refresh_token"):
            old = db.one("SELECT secret FROM mail_accounts WHERE owner=? AND provider='Outlook'", (owner,))
            if old and json.loads(cipher(settings).decrypt(old["secret"].encode())) == token:
                replacement = (
                    cipher(settings)
                    .encrypt(json.dumps({**token, "refresh_token": access["refresh_token"]}).encode())
                    .decode()
                )
                db.execute(
                    "UPDATE mail_accounts SET secret=? WHERE owner=? AND provider='Outlook' AND secret=?",
                    (replacement, owner, old["secret"]),
                )
        since = (datetime.now(UTC) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = GRAPH + "/me/mailFolders/inbox/messages"
        params = {"$filter": "receivedDateTime ge " + since, "$select": "id,subject,from,body,receivedDateTime", "$top": "100"}
        while url and url.startswith(GRAPH + "/"):
            response = client.get(
                url,
                params=params,
                headers={
                    "Authorization": "Bearer " + access["access_token"],
                    "Prefer": 'outlook.body-content-type="text"',
                },
            )
            response.raise_for_status()
            result = response.json()
            for m in result["value"]:
                body = m.get("body", {})
                text = body.get("content", "")
                if body.get("contentType", "").lower() == "html":
                    text = posting_markdown(text)
                subject = m.get("subject") or "Employer reply"
                if application_message(subject, text):
                    store_reply(
                        db,
                        owner,
                        Reply(
                            received=m.get("receivedDateTime"),
                            subject=subject[:500],
                            body=text[:32000],
                            sender=m.get("from", {}).get("emailAddress", {}).get("address", "")[:500],
                        ),
                        hashlib.sha256(("graph:" + address + m["id"]).encode()).hexdigest(),
                        automatic=True,
                    )
            params = None
            url = result.get("@odata.nextLink")


def sync_accounts(db, settings, owner):
    accounts = db.all(
        "SELECT provider FROM mail_accounts WHERE owner=? AND provider IN ('Gmail','Outlook')", (owner,)
    )
    failures = []
    sources = [a["provider"] for a in accounts]
    if all((settings.mail_host, settings.mail_user, settings.mail_password)):
        sources.append("Configured folder")
    for provider in sources:
        try:
            if provider == "Configured folder":
                sync_mail(db, settings, owner)
            elif provider == "Outlook":
                auth = get(db, settings, owner, provider)
                if auth:
                    sync_graph(db, settings, owner, auth)
            else:
                auth = get(db, settings, owner, provider)
                if auth:
                    address, secret = auth
                    sync_mail(
                        db,
                        settings.model_copy(
                            update={
                                "mail_host": "imap.gmail.com",
                                "mail_folder": "INBOX",
                                "mail_user": address,
                                "mail_password": secret["password"],
                            }
                        ),
                        owner,
                        filter_inbox=True,
                    )
        except (imaplib.IMAP4.error, OSError, ValueError, LookupError, InvalidToken, httpx.HTTPError):
            failures.append(provider)
    status = (
        ("Check connection: " + ", ".join(failures))
        if failures
        else ("Mailbox checked" if sources else "No inbox connected")
    )
    db.execute("INSERT OR REPLACE INTO mail_sync VALUES(?,?,?)", (owner, status, now()))
    return {"status": status}


def install_mail(app, db, settings):
    @app.get("/api/owner/mail")
    def accounts(owner: Owner):
        return {
            "accounts": db.all(
                "SELECT provider,address FROM mail_accounts WHERE owner=? AND provider IN ('Gmail','Outlook')",
                (owner,),
            ),
            "legacy": bool(settings.mail_host and settings.mail_user and settings.mail_password),
            "sync": db.one("SELECT status,checked FROM mail_sync WHERE owner=?", (owner,)),
        }

    @app.post("/api/owner/mail/gmail")
    def gmail(value: Gmail, owner: Owner):
        password = value.password.replace(" ", "")
        try:
            with imaplib.IMAP4_SSL(
                "imap.gmail.com", timeout=15, ssl_context=ssl.create_default_context()
            ) as mail:
                mail.login(value.email, password)
                if mail.select("INBOX", readonly=True)[0] != "OK":
                    raise ValueError()
        except (imaplib.IMAP4.error, OSError, ValueError):
            raise HTTPException(
                422, "Gmail could not open the inbox. Check the address, app password and IMAP access."
            ) from None
        put(db, settings, owner, "Gmail", value.email, {"password": password})
        return {"ok": True}

    @app.post("/api/owner/mail/microsoft")
    def microsoft(value: Microsoft, owner: Owner):
        try:
            response = httpx.post(
                MS + "/devicecode", data={"client_id": str(value.client_id), "scope": SCOPES}, timeout=15
            )
            response.raise_for_status()
            d = response.json()
        except httpx.HTTPError:
            raise HTTPException(
                422, "Microsoft could not start sign-in. Check the application ID and public client settings."
            ) from None
        put(
            db,
            settings,
            owner,
            "pending",
            "",
            {
                "device_code": d["device_code"],
                "client_id": str(value.client_id),
                "expires": time.time() + d["expires_in"],
            },
        )
        return {"code": d["user_code"], "url": d["verification_uri"], "interval": d.get("interval", 5)}

    @app.post("/api/owner/mail/microsoft/finish")
    def finish(owner: Owner):
        pending = get(db, settings, owner, "pending")
        if not pending or pending[1]["expires"] < time.time():
            raise HTTPException(410, "Sign-in expired. Start again.")
        value = pending[1]
        try:
            response = httpx.post(
                MS + "/token",
                data={
                    "client_id": value["client_id"],
                    "device_code": value["device_code"],
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=15,
            )
            d = response.json()
            if d.get("error") in {"authorization_pending", "slow_down"}:
                return {"pending": True}
            response.raise_for_status()
            profile = httpx.get(
                GRAPH + "/me", headers={"Authorization": "Bearer " + d["access_token"]}, timeout=15
            )
            profile.raise_for_status()
            user = profile.json()
            put(
                db,
                settings,
                owner,
                "Outlook",
                user.get("mail") or user["userPrincipalName"],
                {"client_id": value["client_id"], "refresh_token": d["refresh_token"]},
            )
        except (httpx.HTTPError, KeyError):
            raise HTTPException(422, "Microsoft sign-in was declined or expired. Start again.") from None
        db.execute("DELETE FROM mail_accounts WHERE owner=? AND provider='pending'", (owner,))
        return {"ok": True}

    @app.post("/api/owner/mail/check")
    def check(owner: Owner):
        return sync_accounts(db, settings, owner)

    @app.delete("/api/owner/mail/{provider}")
    def disconnect(provider: str, owner: Owner):
        db.execute("DELETE FROM mail_accounts WHERE owner=? AND provider=?", (owner, provider))
        return {"ok": True}
