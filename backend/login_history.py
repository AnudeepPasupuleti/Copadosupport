"""Record and query sign-in events."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from .db import LoginHistory, User

METHOD_LABELS = {
    "password": "Password",
    "github": "GitHub",
    "google": "Google",
    "login_as": "Login as",
    "login_as_end": "Return to Admin",
}


def _client_ip(request: Request) -> Optional[str]:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return None


def _user_agent(request: Request) -> Optional[str]:
    ua = (request.headers.get("user-agent") or "").strip()
    return ua[:512] if ua else None


def summarize_user_agent(ua: Optional[str]) -> str:
    if not ua:
        return "Unknown device"
    text = ua
    browser = "Browser"
    if "Edg/" in text:
        browser = "Edge"
    elif "Chrome/" in text and "Chromium" not in text:
        browser = "Chrome"
    elif "Firefox/" in text:
        browser = "Firefox"
    elif "Safari/" in text and "Chrome/" not in text:
        browser = "Safari"
    elif "Opera" in text or "OPR/" in text:
        browser = "Opera"

    os_name = "Unknown OS"
    if "iPhone" in text or "iPad" in text:
        os_name = "iOS"
    elif "Android" in text:
        os_name = "Android"
    elif "Mac OS X" in text or "Macintosh" in text:
        os_name = "macOS"
    elif "Windows" in text:
        os_name = "Windows"
    elif "Linux" in text:
        os_name = "Linux"

    device = "Mobile" if any(x in text for x in ("Mobile", "Android", "iPhone", "iPad")) else "Desktop"
    return f"{browser} on {os_name} ({device})"


def record_login(
    db: Session,
    *,
    request: Request,
    method: str,
    user: Optional[User] = None,
    actor: Optional[User] = None,
    success: bool = True,
    detail: Optional[str] = None,
) -> LoginHistory:
    row = LoginHistory(
        user_id=user.id if user else None,
        actor_id=actor.id if actor else None,
        method=(method or "password").strip().lower()[:32],
        success=bool(success),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail=(detail or "")[:512] or None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def login_history_dict(
    row: LoginHistory,
    user: Optional[User] = None,
    actor: Optional[User] = None,
) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_name": (user.name or user.email) if user else None,
        "user_email": user.email if user else None,
        "actor_id": row.actor_id,
        "actor_name": (actor.name or actor.email) if actor else None,
        "actor_email": actor.email if actor else None,
        "method": row.method,
        "method_label": METHOD_LABELS.get(row.method, row.method),
        "success": bool(row.success),
        "ip": row.ip,
        "user_agent": row.user_agent,
        "device": summarize_user_agent(row.user_agent),
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
