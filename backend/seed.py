import copy
import json
from pathlib import Path

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import config
from .db import AppSetting, User, UserState, set_setting

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def empty_state() -> dict:
    return {
        "activeDate": None,
        "items": [],
        "history": [],
        "diary": [],
        "updatedAt": 0,
    }


def load_seed_payload() -> dict:
    path = Path(config.CHECKLIST_SEED_PATH)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "diary" not in data:
            data["diary"] = []
        if "history" not in data:
            data["history"] = []
        if "items" not in data:
            data["items"] = []
        return data
    return empty_state()


def seed_settings(db: Session) -> None:
    if db.get(AppSetting, "google_login_enabled") is None:
        set_setting(db, "google_login_enabled", "false")
    if db.get(AppSetting, "github_login_enabled") is None:
        set_setting(db, "github_login_enabled", "true")
    db.commit()


def seed_users(db: Session) -> None:
    seed_settings(db)

    if db.query(User).count() > 0:
        return

    payload = load_seed_payload()

    admin = User(
        username=config.ADMIN_USERNAME,
        password_hash=hash_password(config.ADMIN_PASSWORD),
        email="admin@local",
        name="Admin",
        auth_type="password",
        role="super_admin",
    )
    db.add(admin)
    db.flush()
    db.add(UserState(user_id=admin.id, payload=json.dumps(copy.deepcopy(payload))))

    user1 = User(
        email=config.USER1_EMAIL,
        name="apasupuleti",
        auth_type="oauth",
        role="member",
    )
    db.add(user1)
    db.flush()
    db.add(UserState(user_id=user1.id, payload=json.dumps(copy.deepcopy(payload))))

    db.commit()
