"""Workspace resolution helpers."""

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from . import config
from .db import User, Workspace, WorkspaceMember, get_db
from .deps import get_current_user


def get_default_workspace(db: Session) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.slug == config.DEFAULT_WORKSPACE_SLUG).first()
    if not ws:
        raise HTTPException(status_code=500, detail="Default workspace missing")
    return ws


def ensure_workspace_member(db: Session, workspace: Workspace, user: User) -> WorkspaceMember:
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.active.is_(True),
        )
        .first()
    )
    if member:
        return member
    # Auto-join default workspace for provisioned users
    if workspace.slug == config.DEFAULT_WORKSPACE_SLUG:
        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=getattr(user, "role", None) or "member",
            active=True,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member
    raise HTTPException(status_code=403, detail="Not a member of this workspace")


def get_current_workspace(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Workspace:
    ws = get_default_workspace(db)
    ensure_workspace_member(db, ws, user)
    return ws
