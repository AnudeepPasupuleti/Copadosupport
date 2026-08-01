import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import config
from .auth import router as auth_router
from .admin import router as admin_router
from .queue import router as queue_router
from .db import UserState, get_db, init_db, SessionLocal
from .deps import get_current_user, user_to_dict
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


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(get_current_user)):
    return user_to_dict(user)


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
