import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import config
from .db import User, UserState, get_db, get_setting, set_setting
from .deps import get_current_user, user_to_dict
from .seed import empty_state, hash_password, verify_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.auth_type != "password" or user.username != config.ADMIN_USERNAME:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


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
    if user.username == config.ADMIN_USERNAME and user.auth_type == "password":
        raise HTTPException(status_code=400, detail="Cannot remove the Admin account")

    state = db.get(UserState, user.id)
    if state:
        db.delete(state)
    db.delete(user)
    db.commit()
    return {"ok": True}


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
