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
    return ua[:255] if ua else None


def record_login(
    db: Session,
    *,
    request: Request,
    method: str,
    user: Optional[User] = None,
    success: bool = True,
    detail: Optional[str] = None,
) -> LoginHistory:
    row = LoginHistory(
        user_id=user.id if user else None,
        method=(method or "password").strip().lower()[:32],
        success=bool(success),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail=(detail or "")[:255] or None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def login_history_dict(row: LoginHistory, user: Optional[User] = None) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_name": (user.name or user.email) if user else None,
        "user_email": user.email if user else None,
        "method": row.method,
        "method_label": METHOD_LABELS.get(row.method, row.method),
        "success": bool(row.success),
        "ip": row.ip,
        "user_agent": row.user_agent,
        "detail": row.detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
