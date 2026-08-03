import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import config
from .db import User, get_db, get_setting
from .deps import user_to_dict
from .login_history import record_login
from .seed import verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()

if config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET:
    oauth.register(
        name="github",
        client_id=config.GITHUB_CLIENT_ID,
        client_secret=config.GITHUB_CLIENT_SECRET,
        access_token_url="https://github.com/login/oauth/access_token",
        authorize_url="https://github.com/login/oauth/authorize",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "read:user user:email"},
    )

if config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


class LoginBody(BaseModel):
    username: str
    password: str


def _provider_enabled(db: Session, provider: str) -> bool:
    key = f"{provider}_login_enabled"
    return get_setting(db, key, "true").lower() in ("1", "true", "yes", "on")


def _provider_configured(provider: str) -> bool:
    if provider == "github":
        return bool(config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET)
    if provider == "google":
        return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)
    return False


def _oauth_client_ready(provider: str) -> bool:
    return _provider_configured(provider) and getattr(oauth, provider, None) is not None


@router.post("/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    username = body.username.strip()
    user = db.query(User).filter(User.username == username).first()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        if user:
            record_login(
                db,
                request=request,
                method="password",
                user=user,
                success=False,
                detail="Invalid password",
            )
            db.commit()
        raise HTTPException(status_code=401, detail="Invalid username or password")

    request.session.clear()
    request.session["user_id"] = user.id
    record_login(db, request=request, method="password", user=user, success=True)
    db.commit()
    return {"ok": True, "user": user_to_dict(user, request)}


@router.get("/providers")
def providers(db: Session = Depends(get_db)):
    return {
        "github": {
            "configured": _provider_configured("github"),
            "enabled": _provider_enabled(db, "github"),
        },
        "google": {
            "configured": _provider_configured("google"),
            "enabled": _provider_enabled(db, "google"),
        },
    }


@router.get("/github")
async def github_login(request: Request, db: Session = Depends(get_db)):
    if not _provider_configured("github"):
        raise HTTPException(status_code=503, detail="GitHub login is not configured")
    if not _provider_enabled(db, "github"):
        raise HTTPException(status_code=403, detail="GitHub login is disabled by admin")
    redirect_uri = f"{config.BASE_URL}/auth/callback"
    return await oauth.github.authorize_redirect(request, redirect_uri)


@router.get("/google")
async def google_login(request: Request, db: Session = Depends(get_db)):
    if not _provider_configured("google"):
        raise HTTPException(status_code=503, detail="Google login is not configured")
    if not _provider_enabled(db, "google"):
        raise HTTPException(status_code=403, detail="Google login is disabled by admin")
    redirect_uri = f"{config.BASE_URL}/auth/callback/google"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def github_callback(request: Request, db: Session = Depends(get_db)):
    if not _oauth_client_ready("github"):
        raise HTTPException(status_code=503, detail="GitHub login is not configured")
    if not _provider_enabled(db, "github"):
        raise HTTPException(status_code=403, detail="GitHub login is disabled by admin")

    try:
        token = await oauth.github.authorize_access_token(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"GitHub auth failed: {exc}") from exc

    access_token = token.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="GitHub did not return an access token")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        profile_res = await client.get("https://api.github.com/user", headers=headers)
        if profile_res.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not load GitHub profile")
        profile = profile_res.json()
        emails_res = await client.get("https://api.github.com/user/emails", headers=headers)
        emails = emails_res.json() if emails_res.status_code == 200 else []

    github_id = str(profile.get("id") or "")
    github_login = (profile.get("login") or "").strip()
    name = profile.get("name") or github_login or "GitHub User"
    picture = profile.get("avatar_url")

    email = ""
    if isinstance(emails, list):
        primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
        verified = next((e for e in emails if e.get("verified")), None)
        chosen = primary or verified or (emails[0] if emails else None)
        if chosen:
            email = (chosen.get("email") or "").lower().strip()
    if not email:
        email = (profile.get("email") or "").lower().strip()
    if not email and github_login:
        email = f"{github_login.lower()}@users.noreply.github.com"
    if not github_id:
        raise HTTPException(status_code=400, detail="GitHub did not return a user id")

    user = db.query(User).filter(User.github_id == github_id).first()
    if not user:
        user = db.query(User).filter(User.google_sub == github_id).first()  # legacy
    if not user and email:
        user = db.query(User).filter(User.email == email).first()
    if (
        not user
        and config.USER1_GITHUB_LOGIN
        and github_login.lower() == config.USER1_GITHUB_LOGIN.lower()
    ):
        user = db.query(User).filter(User.email == config.USER1_EMAIL).first()

    if user:
        if user.auth_type == "password":
            raise HTTPException(status_code=403, detail="Use username/password for the Admin account")
        user.github_id = github_id
        user.name = name or user.name
        user.picture = picture
        user.auth_type = "oauth"
    else:
        raise HTTPException(
            status_code=403,
            detail="No account for this GitHub user. Ask an admin to add your email first.",
        )

    db.commit()
    db.refresh(user)
    request.session.clear()
    request.session["user_id"] = user.id
    record_login(db, request=request, method="github", user=user, success=True)
    db.commit()
    return RedirectResponse(url="/", status_code=302)


@router.get("/callback/google")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not _oauth_client_ready("google"):
        raise HTTPException(status_code=503, detail="Google login is not configured")
    if not _provider_enabled(db, "google"):
        raise HTTPException(status_code=403, detail="Google login is disabled by admin")

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Google auth failed: {exc}") from exc

    info = token.get("userinfo") or {}
    email = (info.get("email") or "").lower().strip()
    google_sub = info.get("sub")
    name = info.get("name") or (email.split("@")[0] if email else "Google User")
    picture = info.get("picture")

    if not email or not google_sub:
        raise HTTPException(status_code=400, detail="Google did not return email")

    user = db.query(User).filter(User.google_sub == google_sub).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()

    if user:
        if user.auth_type == "password":
            raise HTTPException(status_code=403, detail="Use username/password for the Admin account")
        user.google_sub = google_sub
        user.name = name or user.name
        user.picture = picture
        user.auth_type = "oauth"
    else:
        raise HTTPException(
            status_code=403,
            detail="No account for this Google user. Ask an admin to add your email first.",
        )

    db.commit()
    db.refresh(user)
    request.session.clear()
    request.session["user_id"] = user.id
    record_login(db, request=request, method="google", user=user, success=True)
    db.commit()
    return RedirectResponse(url="/", status_code=302)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
