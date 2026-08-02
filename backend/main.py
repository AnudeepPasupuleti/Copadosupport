import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from typing import Optional

from . import config
from .auth import router as auth_router
from .admin import router as admin_router
from .queue import router as queue_router
from .org import router as org_router
from .sse import router as sse_router
from .db import UserState, get_db, init_db, SessionLocal
from .deps import get_current_user, user_org_context, user_to_dict
from .seed import empty_state, seed_users

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Copado Support")
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    same_site="lax",
    https_only=config.HTTPS_ONLY,
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(queue_router)
app.include_router(org_router)
app.include_router(sse_router)


@app.on_event("startup")
def on_startup():
    config.validate_runtime_secrets()
    (ROOT / "data").mkdir(exist_ok=True)
    init_db()
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()
    # Ensure memberships for users seeded after tables existed
    from .db import _ensure_default_workspace

    _ensure_default_workspace()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/me")
def me(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    data = user_to_dict(user, request)
    data.update(user_org_context(db, user))
    return data


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    picture: Optional[str] = None


class PasswordUpdate(BaseModel):
    current_password: Optional[str] = None
    new_password: str = Field(min_length=8)
    username: Optional[str] = None


@app.put("/api/me/profile")
def update_profile(
    body: ProfileUpdate,
    request: Request,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from .db import User

    db_user = db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        if len(name) > 255:
            raise HTTPException(status_code=400, detail="Name is too long")
        db_user.name = name

    if body.picture is not None:
        picture = body.picture.strip()
        if picture and not (picture.startswith("http://") or picture.startswith("https://")):
            raise HTTPException(status_code=400, detail="Picture must be an http(s) URL")
        if len(picture) > 512:
            raise HTTPException(status_code=400, detail="Picture URL is too long")
        db_user.picture = picture or None

    db.commit()
    db.refresh(db_user)
    data = user_to_dict(db_user, request)
    data.update(user_org_context(db, db_user))
    return data


@app.post("/api/me/password")
def update_my_password(
    body: PasswordUpdate,
    request: Request,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from .db import User
    from .seed import hash_password, verify_password

    db_user = db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    new_password = body.new_password.strip()
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    if db_user.password_hash:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="Current password required")
        if not verify_password(body.current_password, db_user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if new_password == body.current_password:
            raise HTTPException(status_code=400, detail="New password must be different")
    else:
        username = (body.username or db_user.username or "").strip()
        if not username:
            raise HTTPException(status_code=400, detail="Username required to set a password")
        conflict = (
            db.query(User)
            .filter(User.username == username, User.id != db_user.id)
            .first()
        )
        if conflict:
            raise HTTPException(status_code=400, detail="Username already exists")
        db_user.username = username

    db_user.password_hash = hash_password(new_password)
    db.commit()
    db.refresh(db_user)
    return {"ok": True, "user": user_to_dict(db_user, request)}


@app.get("/api/state")
def get_state(user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.get(UserState, user.id)
    if not row:
        return empty_state()
    try:
        return json.loads(row.payload)
    except json.JSONDecodeError:
        return empty_state()


@app.put("/api/state")
async def put_state(request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="State must be an object")

    data["updatedAt"] = data.get("updatedAt") or int(datetime.now(timezone.utc).timestamp() * 1000)
    payload = json.dumps(data)

    row = db.get(UserState, user.id)
    if not row:
        row = UserState(user_id=user.id, payload=payload)
        db.add(row)
    else:
        row.payload = payload
        row.updated_at = datetime.now(timezone.utc)

    db.commit()
    return {"ok": True, "updatedAt": data["updatedAt"]}


@app.get("/login")
def login_page():
    return FileResponse(ROOT / "login.html")


@app.get("/")
def index(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse(ROOT / "index.html")


def _session_is_admin(request: Request, db: Session) -> bool:
    uid = request.session.get("user_id")
    if not uid:
        return False
    from .db import User

    user = db.get(User, uid)
    return bool(user and user_to_dict(user)["is_admin"])


@app.get("/admin")
def admin_page(request: Request, db: Session = Depends(get_db)):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login", status_code=302)
    if not _session_is_admin(request, db):
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(ROOT / "admin.html")


@app.get("/styles.css")
def styles_css():
    return FileResponse(ROOT / "styles.css", media_type="text/css")


@app.get("/app.js")
def app_js():
    return FileResponse(ROOT / "app.js", media_type="application/javascript")


@app.get("/team.js")
def team_js():
    return FileResponse(ROOT / "team.js", media_type="application/javascript")


@app.get("/org.js")
def org_js():
    return FileResponse(ROOT / "org.js", media_type="application/javascript")


@app.get("/realtime.js")
def realtime_js():
    return FileResponse(ROOT / "realtime.js", media_type="application/javascript")


@app.get("/admin.js")
def admin_js(request: Request, db: Session = Depends(get_db)):
    if not _session_is_admin(request, db):
        raise HTTPException(status_code=403, detail="Admin only")
    return FileResponse(ROOT / "admin.js", media_type="application/javascript")


@app.get("/admin.css")
def admin_css(request: Request, db: Session = Depends(get_db)):
    if not _session_is_admin(request, db):
        raise HTTPException(status_code=403, detail="Admin only")
    return FileResponse(ROOT / "admin.css", media_type="text/css")
