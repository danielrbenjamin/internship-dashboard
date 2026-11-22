import re
from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_url: str = "http://localhost:8000"
    data_dir: Path = Path("data")
    session_secret: str
    auth0_domain: str = ""
    auth0_client_id: str = ""
    auth0_client_secret: str = ""
    owner_subject: str = ""
    mcp_audience: str = "http://localhost:8000/mcp"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    codex_home: Path = Path("data/codex")
    cover_letter_repo: str = ""
    cover_letter_branch: str = "main"
    cover_letter_entry: str = "cover-letter.tex"
    github_token: str = ""
    brave_search_api_key: str = ""
    mail_host: str = ""
    mail_user: str = ""
    mail_password: str = ""
    mail_folder: str = "Applications"
    worker_interval: int = 300

    def validate_runtime(self):
        if len(self.session_secret) < 32:
            raise ValueError("SESSION_SECRET must have at least 32 characters")
        origin = urlparse(self.app_url)
        host = origin.hostname
        if (not host or origin.scheme not in {"http", "https"} or origin.path or origin.params
                or origin.query or origin.fragment or origin.username or origin.password):
            raise ValueError("APP_URL must be an HTTP(S) origin without a trailing slash")
        if host not in {"localhost", "127.0.0.1"} and origin.scheme != "https":
            raise ValueError("Non-local APP_URL requires HTTPS")
        if "*" in self.allowed_hosts:
            raise ValueError("ALLOWED_HOSTS must list explicit hostnames")
        if self.auth0_domain and not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+",
            self.auth0_domain, re.IGNORECASE,
        ):
            raise ValueError("AUTH0_DOMAIN must be a hostname")
        self.data_dir.mkdir(parents=True, exist_ok=True)
