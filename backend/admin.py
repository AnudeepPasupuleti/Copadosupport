import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import config
from .db import User, UserState, WorkspaceMember, get_db, get_setting, set_setting
from .deps import (
    get_current_user,
    is_admin_user,
    is_super_admin,
    normalize_role,
    user_to_dict,
)
from .seed import empty_state, hash_password, verify_password
from .workspaces import get_default_workspace

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def _super_admin_count(db: Session) -> int:
    return db.query(User).filter(User.role == "super_admin").count()


def _admin_level_count(db: Session) -> int:
    return db.query(User).filter(User.role.in_(("admin", "super_admin"))).count()


class SettingsUpdate(BaseModel):
    google_login_enabled: Optional[bool] = None
    github_login_enabled: Optional[bool] = None


class CreateUserBody(BaseModel):
    email: str
    name: str = ""
    auth_type: str = Field(default="oauth")
    username: Optional[str] = None
    password: Optional[str] = None
    copy_from_admin: bool = False
    role: str = "member"


class SetRoleBody(BaseModel):
    role: str


class ResetPasswordBody(BaseModel):
    new_password: str = Field(min_length=8)
    username: Optional[str] = None


def _settings_payload(db: Session) -> dict:
    return {
        "google_login_enabled": get_setting(db, "google_login_enabled", "false").lower()
        in ("1", "true", "yes", "on"),
        "github_login_enabled": get_setting(db, "github_login_enabled", "true").lower()
        in ("1", "true", "yes", "on"),
        "google_configured": bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET),
        "github_configured": bool(config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET),
    }


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    return _settings_payload(db)


@router.put("/settings")
def update_settings(
    body: SettingsUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    if body.google_login_enabled is not None:
        set_setting(db, "google_login_enabled", "true" if body.google_login_enabled else "false")
    if body.github_login_enabled is not None:
        set_setting(db, "github_login_enabled", "true" if body.github_login_enabled else "false")
    db.commit()
    return _settings_payload(db)


@router.get("/users")
def list_users(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    users = db.query(User).order_by(User.id.asc()).all()
    return [user_to_dict(u) for u in users]


@router.get("/status")
def admin_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Helps confirm Admin is reading the expected database."""
    from urllib.parse import urlparse

    from .db import TeamTask, UserState, engine

    parsed = urlparse(config.DATABASE_URL)
    host = parsed.hostname or ""
    return {
        "dialect": engine.dialect.name,
        "db_host": host,
        "db_name": (parsed.path or "").lstrip("/") or None,
        "user_count": db.query(User).count(),
        "user_state_count": db.query(UserState).count(),
        "ticket_count": db.query(TeamTask).count(),
        "roles": {
            role: db.query(User).filter(User.role == role).count()
            for role in ("super_admin", "admin", "manager", "member")
        },
    }


@router.post("/users")
def create_user(
    body: CreateUserBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    email = body.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email required")

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already exists")

    auth_type = (body.auth_type or "oauth").strip().lower()
    if auth_type not in ("oauth", "password", "github", "google"):
        raise HTTPException(status_code=400, detail="Invalid auth_type")

    role = normalize_role(body.role)
    if role == "super_admin" and not is_super_admin(admin):
        raise HTTPException(status_code=403, detail="Only Super Admin can create Super Admin users")

    username = None
    password_hash = None
    if auth_type == "password":
        if not body.username or not body.password:
            raise HTTPException(status_code=400, detail="Username and password required")
        if db.query(User).filter(User.username == body.username.strip()).first():
            raise HTTPException(status_code=400, detail="Username already exists")
        username = body.username.strip()
        password_hash = hash_password(body.password)

    user = User(
        email=email,
        name=(body.name or email.split("@")[0]).strip(),
        auth_type=auth_type,
        username=username,
        password_hash=password_hash,
        role=role,
    )
    db.add(user)
    db.flush()

    payload = empty_state()
    if body.copy_from_admin:
        admin_state = db.get(UserState, admin.id)
        if admin_state:
            try:
                payload = json.loads(admin_state.payload)
            except json.JSONDecodeError:
                payload = empty_state()

    db.add(UserState(user_id=user.id, payload=json.dumps(payload)))
    ws = get_default_workspace(db)
    db.add(
        WorkspaceMember(
            workspace_id=ws.id,
            user_id=user.id,
            role=role,
            active=True,
        )
    )
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


@router.post("/users/{user_id}/role")
def set_user_role(
    user_id: int,
    body: SetRoleBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    role = normalize_role(body.role)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    current = normalize_role(user.role)
    if role == "super_admin" or current == "super_admin":
        if not is_super_admin(admin):
            raise HTTPException(
                status_code=403,
                detail="Only Super Admin can assign or change Super Admin roles",
            )

    if current == "super_admin" and role != "super_admin":
        if _super_admin_count(db) <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last Super Admin")
        if user_id == admin.id:
            raise HTTPException(status_code=400, detail="Cannot demote your own Super Admin role")

    if current in ("admin", "super_admin") and role not in ("admin", "super_admin"):
        if _admin_level_count(db) <= 1:
            raise HTTPException(status_code=400, detail="Cannot demote the last Admin")

    if user_id == admin.id and role not in ("admin", "super_admin") and is_admin_user(admin):
        raise HTTPException(status_code=400, detail="Cannot demote your own Admin role")

    user.role = role
    db.commit()
    db.refresh(user)
    return user_to_dict(user)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot remove the Admin account")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if is_admin_user(user):
        raise HTTPException(status_code=400, detail="Cannot remove an Admin account")

    state = db.get(UserState, user.id)
    if state:
        db.delete(state)
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/impersonate")
def impersonate_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if request.session.get("impersonator_id"):
        raise HTTPException(status_code=400, detail="Already impersonating — return to Admin first")
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot log in as yourself")

    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if is_super_admin(target):
        raise HTTPException(status_code=400, detail="Cannot log in as Super Admin")
    if is_admin_user(target) and not is_super_admin(admin):
        raise HTTPException(status_code=400, detail="Cannot log in as Admin")

    request.session["impersonator_id"] = admin.id
    request.session["user_id"] = target.id
    return {"ok": True, "user": user_to_dict(target, request)}


@router.post("/stop-impersonating")
def stop_impersonating(request: Request, db: Session = Depends(get_db)):
    impersonator_id = request.session.get("impersonator_id")
    if not impersonator_id:
        raise HTTPException(status_code=400, detail="Not impersonating")

    admin = db.get(User, impersonator_id)
    if not admin or not is_admin_user(admin):
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")

    request.session.pop("impersonator_id", None)
    request.session["user_id"] = admin.id
    return {"ok": True, "user": user_to_dict(admin, request)}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    body: ResetPasswordBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Use Change Admin password for your own account",
        )

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if is_admin_user(user):
        raise HTTPException(status_code=400, detail="Cannot reset Admin via this action")

    new_password = body.new_password.strip()
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    username = (body.username or user.username or "").strip()
    if not username:
        raise HTTPException(
            status_code=400,
            detail="Username required (this user has no login username yet)",
        )

    conflict = (
        db.query(User)
        .filter(User.username == username, User.id != user.id)
        .first()
    )
    if conflict:
        raise HTTPException(status_code=400, detail="Username already exists")

    user.username = username
    user.password_hash = hash_password(new_password)
    db.commit()
    return {
        "ok": True,
        "user": user_to_dict(user),
        "username": username,
    }


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.post("/change-password")
def change_password(
    body: ChangePasswordBody,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if not admin.password_hash or not verify_password(body.current_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new_password = body.new_password.strip()
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must be different")
    admin.password_hash = hash_password(new_password)
    db.commit()
    return {"ok": True}


@router.get("/backup")
def download_backup(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Full DB snapshot (admin only). Use before migrations / deploys."""
    from datetime import datetime, timezone

    from .db import AppSetting, Notification, TaskComment, TeamTask

    def rows(model):
        return [
            {c.name: getattr(obj, c.name) for c in model.__table__.columns}
            for obj in db.query(model).all()
        ]

    return {
        "format": "copado_support_backup_v1",
        "source": "api",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": {
            "users": rows(User),
            "user_state": rows(UserState),
            "app_settings": rows(AppSetting),
            "team_tasks": rows(TeamTask),
            "task_comments": rows(TaskComment),
            "notifications": rows(Notification),
        },
    }
