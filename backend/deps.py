from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import User, get_db

ROLES = ("admin", "manager", "member")
ROLE_LABELS = {
    "admin": "Admin",
    "manager": "Manager",
    "member": "Member",
}


def normalize_role(role: Optional[str]) -> str:
    value = (role or "member").strip().lower()
    if value == "members":
        value = "member"
    if value not in ROLES:
        return "member"
    return value


def get_user_role(user: User) -> str:
    return normalize_role(getattr(user, "role", None))


def is_admin_user(user: User) -> bool:
    from . import config

    if get_user_role(user) == "admin":
        return True
    # Legacy fallback before role backfill
    return user.auth_type == "password" and user.username == config.ADMIN_USERNAME


def is_manager_or_admin(user: User) -> bool:
    return get_user_role(user) in ("admin", "manager") or is_admin_user(user)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, user_id)
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def user_to_dict(user: User, request: Optional[Request] = None) -> dict:
    role = get_user_role(user)
    # Keep legacy admin flag in sync with role
    admin = role == "admin" or is_admin_user(user)
    if admin:
        role = "admin"
    data = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "auth_type": user.auth_type,
        "username": user.username,
        "role": role,
        "role_label": ROLE_LABELS.get(role, "Member"),
        "is_admin": admin,
        "is_manager": role == "manager" or admin,
        "can_edit_org": role in ("admin", "manager") or admin,
        "has_password": bool(user.password_hash),
        "impersonating": False,
        "reports_to_id": getattr(user, "reports_to_id", None),
    }
    if request is not None:
        impersonator_id = request.session.get("impersonator_id")
        data["impersonating"] = bool(impersonator_id)
    return data
