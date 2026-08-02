import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-session-secret-change-me")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8080").rstrip("/")
CHECKLIST_SEED_PATH = ROOT / "data" / "checklist.json"
USER1_EMAIL = os.getenv("USER1_EMAIL", "apasupuleti@copado.com")
USER1_GITHUB_LOGIN = os.getenv("USER1_GITHUB_LOGIN", "")
ENV = os.getenv("ENV", os.getenv("ENVIRONMENT", "development")).lower()
FEATURE_REALTIME_SSE = os.getenv("FEATURE_REALTIME_SSE", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
FEATURE_MENTIONS = os.getenv("FEATURE_MENTIONS", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
DEFAULT_WORKSPACE_SLUG = os.getenv("DEFAULT_WORKSPACE_SLUG", "default")
DEFAULT_WORKSPACE_TIMEZONE = os.getenv("DEFAULT_WORKSPACE_TIMEZONE", "Asia/Kolkata")


def normalize_database_url(url: str) -> str:
    """Render/Heroku use postgres://; SQLAlchemy + psycopg need postgresql+psycopg://."""
    value = (url or "").strip()
    if not value:
        return f"sqlite:///{ROOT / 'data' / 'app.db'}"
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("postgresql://") and "+psycopg" not in value and "+psycopg2" not in value:
        value = "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


DATABASE_URL = normalize_database_url(
    os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data' / 'app.db'}")
)

WEAK_SESSION_SECRETS = {
    "",
    "dev-session-secret-change-me",
    "change-me-to-a-long-random-string",
    "secret",
    "changeme",
}


def is_production() -> bool:
    if ENV in ("prod", "production"):
        return True
    host = BASE_URL.lower()
    if host.startswith("https://") and "localhost" not in host and "127.0.0.1" not in host:
        return True
    return False


HTTPS_ONLY = BASE_URL.lower().startswith("https://")


def session_secret_is_weak(secret: str = None) -> bool:
    value = SESSION_SECRET if secret is None else secret
    return value in WEAK_SESSION_SECRETS or len(value) < 24


def validate_runtime_secrets() -> None:
    if is_production() and session_secret_is_weak():
        raise RuntimeError(
            "SESSION_SECRET is missing or too weak for production. "
            "Set a random string of at least 24 characters in .env "
            "(and set ENV=production or use an https BASE_URL)."
        )
