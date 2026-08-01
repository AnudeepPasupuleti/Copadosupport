from typing import Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import User, get_db


def is_admin_user(user: User) -> bool:
    from . import config

    return user.auth_type == "password" and user.username == config.ADMIN_USERNAME


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
    data = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "auth_type": user.auth_type,
        "username": user.username,
        "is_admin": is_admin_user(user),
        "has_password": bool(user.password_hash),
        "impersonating": False,
    }
    if request is not None:
        impersonator_id = request.session.get("impersonator_id")
        data["impersonating"] = bool(impersonator_id)
    return data
