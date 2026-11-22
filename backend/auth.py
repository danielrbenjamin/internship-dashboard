
import secrets
import time
from urllib.parse import urlencode

import httpx
from authlib.integrations.base_client import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from starlette.responses import RedirectResponse

from .pages import safe_page

SESSION_SECONDS = 8 * 3600


def install_auth(app, settings, db):
    oauth = OAuth()
    if settings.auth0_domain and settings.auth0_client_id and settings.auth0_client_secret:
        oauth.register(
            "auth0",
            client_id=settings.auth0_client_id,
            client_secret=settings.auth0_client_secret,
            server_metadata_url=f"https://{settings.auth0_domain}/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"},
        )

    @app.get("/auth/login")
    async def login(request: Request):
        if not oauth.create_client("auth0") or not settings.owner_subject:
            raise HTTPException(503, "Owner sign-in is not configured")
        request.session["return_page"] = safe_page(request.query_params.get("next"))
        return await oauth.auth0.authorize_redirect(
            request, settings.app_url + "/auth/callback", connection="google-oauth2"
        )

    @app.get("/auth/callback")
    async def callback(request: Request):
        if not oauth.create_client("auth0"):
            raise HTTPException(503, "Owner sign-in is not configured")
        try:
            token = await oauth.auth0.authorize_access_token(request)
        except OAuthError:
            raise HTTPException(401, "Sign-in could not be verified") from None
        except httpx.HTTPError:
            raise HTTPException(503, "Sign-in provider is temporarily unavailable") from None
        subject = token.get("userinfo", {}).get("sub")
        if not subject or subject != settings.owner_subject:
            raise HTTPException(403, "This account has no owner access")
        return_page = safe_page(request.session.get("return_page"))
        expire_session(request, db)
        session_id = secrets.token_urlsafe(32)
        db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (session_id, subject, time.time() + SESSION_SECONDS))
        request.session["sid"] = session_id
        claims=token.get("userinfo", {})
        request.session["account"]={key:str(claims.get(key) or "")[:240] for key in ("name","email")}
        picture=str(claims.get("picture") or "")
        if picture.startswith("https://lh3.googleusercontent.com/"):
            request.session["account"]["picture"]=picture[:1024]
        return RedirectResponse(return_page, 303)

    @app.post("/auth/logout")
    def logout(request: Request):
        expire_session(request, db)
        url = "/"
        if settings.auth0_domain and settings.auth0_client_id:
            query = urlencode({"client_id": settings.auth0_client_id, "returnTo": settings.app_url})
            url = f"https://{settings.auth0_domain}/v2/logout?{query}"
        return {"redirect": url}


def expire_session(request, db):
    session_id = request.session.get("sid")
    if session_id:
        db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    request.session.clear()


def current_owner(request):
    session_id = request.session.get("sid")
    settings = request.app.state.settings
    if not session_id or not settings.owner_subject:
        return None
    row = request.app.state.db.one(
        "SELECT owner FROM sessions WHERE id=? AND owner=? AND expires>?",
        (session_id, settings.owner_subject, time.time()),
    )
    return row["owner"] if row else None


def require_owner(request: Request):
    owner = current_owner(request)
    if not owner:
        raise HTTPException(401, "Owner sign-in required")
    return owner
