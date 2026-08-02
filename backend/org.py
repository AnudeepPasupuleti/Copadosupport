"""Org chart: reporting tree + named teams."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import OrgTeam, OrgTeamMember, User, get_db
from .deps import get_current_user, is_manager_or_admin, user_to_dict
from .workspaces import get_default_workspace

router = APIRouter(prefix="/api/org", tags=["org"])


def require_org_viewer(user: User = Depends(get_current_user)) -> User:
    return user


def require_org_editor(user: User = Depends(get_current_user)) -> User:
    if not is_manager_or_admin(user):
        raise HTTPException(status_code=403, detail="Admin or Manager only")
    return user


class ManagerBody(BaseModel):
    manager_id: Optional[int] = None


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None


class MemberBody(BaseModel):
    user_id: int
    title: str = ""


def _user_brief(user: User) -> dict:
    data = user_to_dict(user)
    return {
        "id": data["id"],
        "name": data["name"],
        "email": data["email"],
        "picture": data["picture"],
        "role": data["role"],
        "role_label": data["role_label"],
        "reports_to_id": user.reports_to_id,
    }


def _would_create_cycle(db: Session, user_id: int, manager_id: int) -> bool:
    """True if setting user_id.reports_to = manager_id creates a cycle."""
    if user_id == manager_id:
        return True
    seen = {user_id}
    current = manager_id
    while current is not None:
        if current in seen:
            return True
        seen.add(current)
        boss = db.get(User, current)
        if not boss:
            break
        current = boss.reports_to_id
    return False


def _build_tree(users: list[User]) -> list[dict]:
    by_id = {u.id: u for u in users}
    children: dict[Optional[int], list[User]] = {}
    for u in users:
        parent = u.reports_to_id if u.reports_to_id in by_id else None
        children.setdefault(parent, []).append(u)

    def node(u: User) -> dict:
        kids = children.get(u.id, [])
        kids.sort(key=lambda x: (x.name or x.email or "").lower())
        return {**_user_brief(u), "reports": [node(c) for c in kids]}

    roots = children.get(None, [])
    roots.sort(key=lambda x: (x.name or x.email or "").lower())
    return [node(u) for u in roots]


def _team_dict(db: Session, team: OrgTeam) -> dict:
    members_out = []
    for m in sorted(team.members, key=lambda x: x.id):
        user = db.get(User, m.user_id)
        if not user:
            continue
        members_out.append({**_user_brief(user), "title": m.title or ""})
    return {
        "id": team.id,
        "name": team.name,
        "description": team.description or "",
        "members": members_out,
        "created_at": team.created_at.isoformat() if team.created_at else None,
    }


@router.get("/chart")
def get_chart(db: Session = Depends(get_db), user: User = Depends(require_org_viewer)):
    users = db.query(User).order_by(User.id.asc()).all()
    teams = db.query(OrgTeam).order_by(OrgTeam.name.asc()).all()
    return {
        "can_edit": is_manager_or_admin(user),
        "tree": _build_tree(users),
        "people": [_user_brief(u) for u in users],
        "teams": [_team_dict(db, t) for t in teams],
    }


@router.put("/users/{user_id}/manager")
def set_manager(
    user_id: int,
    body: ManagerBody,
    db: Session = Depends(get_db),
    _editor: User = Depends(require_org_editor),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    manager_id = body.manager_id
    if manager_id is not None:
        manager = db.get(User, manager_id)
        if not manager:
            raise HTTPException(status_code=400, detail="Manager not found")
        if _would_create_cycle(db, user_id, manager_id):
            raise HTTPException(status_code=400, detail="That manager assignment would create a cycle")

    target.reports_to_id = manager_id
    db.commit()
    db.refresh(target)
    return _user_brief(target)


@router.get("/teams")
def list_teams(db: Session = Depends(get_db), _user: User = Depends(require_org_viewer)):
    teams = db.query(OrgTeam).order_by(OrgTeam.name.asc()).all()
    return [_team_dict(db, t) for t in teams]


@router.post("/teams")
def create_team(
    body: TeamCreate,
    db: Session = Depends(get_db),
    _editor: User = Depends(require_org_editor),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    if db.query(OrgTeam).filter(OrgTeam.name == name).first():
        raise HTTPException(status_code=400, detail="Team name already exists")
    team = OrgTeam(
        workspace_id=get_default_workspace(db).id,
        name=name,
        description=(body.description or "").strip(),
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    return _team_dict(db, team)


@router.patch("/teams/{team_id}")
def update_team(
    team_id: int,
    body: TeamUpdate,
    db: Session = Depends(get_db),
    _editor: User = Depends(require_org_editor),
):
    team = db.get(OrgTeam, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name required")
        conflict = db.query(OrgTeam).filter(OrgTeam.name == name, OrgTeam.id != team_id).first()
        if conflict:
            raise HTTPException(status_code=400, detail="Team name already exists")
        team.name = name
    if body.description is not None:
        team.description = body.description.strip()
    db.commit()
    db.refresh(team)
    return _team_dict(db, team)


@router.delete("/teams/{team_id}")
def delete_team(
    team_id: int,
    db: Session = Depends(get_db),
    _editor: User = Depends(require_org_editor),
):
    team = db.get(OrgTeam, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    db.delete(team)
    db.commit()
    return {"ok": True}


@router.post("/teams/{team_id}/members")
def add_member(
    team_id: int,
    body: MemberBody,
    db: Session = Depends(get_db),
    _editor: User = Depends(require_org_editor),
):
    team = db.get(OrgTeam, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    user = db.get(User, body.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="User not found")
    existing = (
        db.query(OrgTeamMember)
        .filter(OrgTeamMember.team_id == team_id, OrgTeamMember.user_id == body.user_id)
        .first()
    )
    if existing:
        existing.title = (body.title or "").strip()
    else:
        db.add(
            OrgTeamMember(
                team_id=team_id,
                user_id=body.user_id,
                title=(body.title or "").strip(),
            )
        )
    db.commit()
    db.refresh(team)
    return _team_dict(db, team)


@router.delete("/teams/{team_id}/members/{user_id}")
def remove_member(
    team_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    _editor: User = Depends(require_org_editor),
):
    team = db.get(OrgTeam, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    row = (
        db.query(OrgTeamMember)
        .filter(OrgTeamMember.team_id == team_id, OrgTeamMember.user_id == user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Member not found")
    db.delete(row)
    db.commit()
    db.refresh(team)
    return _team_dict(db, team)
