from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import User, get_db

ROLES = ("super_admin", "admin", "manager", "member")
ROLE_LABELS = {
    "super_admin": "Super Admin",
    "admin": "Admin",
    "manager": "Manager",
    "member": "Member",
}


def normalize_role(role: Optional[str]) -> str:
    value = (role or "member").strip().lower()
    if value == "members":
        value = "member"
    if value == "superadmin":
        value = "super_admin"
    if value not in ROLES:
        return "member"
    return value


def get_user_role(user: User) -> str:
    return normalize_role(getattr(user, "role", None))


def is_super_admin(user: User) -> bool:
    return get_user_role(user) == "super_admin"


def is_admin_user(user: User) -> bool:
    from . import config

    role = get_user_role(user)
    if role in ("admin", "super_admin"):
        return True
    # Legacy fallback before role backfill
    return user.auth_type == "password" and user.username == config.ADMIN_USERNAME


def is_manager_or_admin(user: User) -> bool:
    return get_user_role(user) in ("super_admin", "admin", "manager") or is_admin_user(user)


def user_org_context(db: Session, user: User) -> dict:
    """Manager + team memberships for profile /api/me."""
    from .db import OrgTeam, OrgTeamMember

    manager = None
    manager_id = getattr(user, "reports_to_id", None)
    if manager_id:
        boss = db.get(User, manager_id)
        if boss:
            manager = {
                "id": boss.id,
                "name": boss.name or boss.email,
                "email": boss.email,
            }

    rows = (
        db.query(OrgTeamMember, OrgTeam)
        .join(OrgTeam, OrgTeam.id == OrgTeamMember.team_id)
        .filter(OrgTeamMember.user_id == user.id)
        .order_by(OrgTeam.name.asc())
        .all()
    )
    teams = [
        {"id": team.id, "name": team.name, "title": (member.title or "").strip()}
        for member, team in rows
    ]
    return {
        "manager": manager,
        "manager_name": manager["name"] if manager else None,
        "teams": teams,
        "team_name": ", ".join(t["name"] for t in teams) if teams else None,
    }


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
    super_admin = role == "super_admin"
    admin = role in ("admin", "super_admin") or is_admin_user(user)
    # Legacy password admin without role backfill → display as admin, not super_admin
    if admin and role not in ("admin", "super_admin"):
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
        "is_super_admin": super_admin,
        "is_manager": role == "manager" or admin,
        "can_view_org": True,
        "can_edit_org": role in ("super_admin", "admin", "manager") or admin,
        "has_password": bool(user.password_hash),
        "impersonating": False,
        "reports_to_id": getattr(user, "reports_to_id", None),
        "manager": None,
        "manager_name": None,
        "teams": [],
        "team_name": None,
    }
    if request is not None:
        impersonator_id = request.session.get("impersonator_id")
        data["impersonating"] = bool(impersonator_id)
    return data
