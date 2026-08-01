"""Shared Team Queue API — cases, comments, dashboard, notifications."""

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .db import Notification, TaskComment, TeamTask, User, get_db, get_setting, set_setting
from .deps import get_current_user, user_to_dict

router = APIRouter(prefix="/api/queue", tags=["queue"])

STATUSES = (
    "new",
    "investigating",
    "waiting_customer",
    "waiting_engineering",
    "resolved",
    "closed",
)
PRIORITIES = ("low", "medium", "high")
OPEN_STATUSES = ("new", "investigating", "waiting_customer", "waiting_engineering")


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    status: str = "new"
    priority: str = "medium"
    due_date: Optional[str] = None
    tags: str = ""
    assignee_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    tags: Optional[str] = None
    assignee_id: Optional[int] = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class MarkReadBody(BaseModel):
    ids: Optional[list[int]] = None


def _next_case_number(db: Session) -> str:
    raw = get_setting(db, "team_case_counter", "1000")
    try:
        n = int(raw) + 1
    except ValueError:
        n = 1001
    set_setting(db, "team_case_counter", str(n))
    return f"CS-{n}"


def _user_brief(user: Optional[User]) -> Optional[dict]:
    if not user:
        return None
    return {
        "id": user.id,
        "name": user.name or user.email,
        "email": user.email,
        "picture": user.picture,
    }


def _task_dict(db: Session, task: TeamTask, include_comments: bool = False) -> dict:
    reporter = db.get(User, task.reporter_id)
    assignee = db.get(User, task.assignee_id) if task.assignee_id else None
    data = {
        "id": task.id,
        "case_number": task.case_number,
        "title": task.title,
        "description": task.description or "",
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date,
        "tags": task.tags or "",
        "reporter": _user_brief(reporter),
        "assignee": _user_brief(assignee),
        "assignee_id": task.assignee_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "comment_count": len(task.comments) if task.comments is not None else 0,
    }
    if include_comments:
        comments = []
        for c in task.comments or []:
            author = db.get(User, c.author_id)
            comments.append(
                {
                    "id": c.id,
                    "body": c.body,
                    "author": _user_brief(author),
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
            )
        data["comments"] = comments
    return data


def _notify(
    db: Session,
    *,
    user_id: int,
    kind: str,
    title: str,
    body: str,
    task_id: Optional[int],
    actor_id: int,
) -> None:
    if user_id == actor_id:
        return
    db.add(
        Notification(
            user_id=user_id,
            kind=kind,
            title=title,
            body=body,
            task_id=task_id,
            read=0,
        )
    )


def _validate_status(status: str) -> str:
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    return status


def _validate_priority(priority: str) -> str:
    if priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")
    return priority


@router.get("/users")
def list_teammates(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    users = db.query(User).order_by(User.name.asc(), User.email.asc()).all()
    return [_user_brief(u) for u in users]


@router.get("/meta")
def queue_meta(_user: User = Depends(get_current_user)):
    return {
        "statuses": list(STATUSES),
        "priorities": list(PRIORITIES),
        "status_labels": {
            "new": "New",
            "investigating": "Investigating",
            "waiting_customer": "Waiting on Customer",
            "waiting_engineering": "Waiting on Engineering",
            "resolved": "Resolved",
            "closed": "Closed",
        },
    }


@router.get("/tasks")
def list_tasks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[int] = None,
    mine: bool = False,
):
    query = db.query(TeamTask)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                TeamTask.title.ilike(like),
                TeamTask.case_number.ilike(like),
                TeamTask.description.ilike(like),
                TeamTask.tags.ilike(like),
            )
        )
    if status:
        _validate_status(status)
        query = query.filter(TeamTask.status == status)
    if priority:
        _validate_priority(priority)
        query = query.filter(TeamTask.priority == priority)
    if mine:
        query = query.filter(TeamTask.assignee_id == user.id)
    elif assignee_id is not None:
        query = query.filter(TeamTask.assignee_id == assignee_id)

    tasks = query.order_by(TeamTask.updated_at.desc()).limit(200).all()
    return [_task_dict(db, t) for t in tasks]


@router.post("/tasks")
def create_task(
    body: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title required")
    status = _validate_status(body.status)
    priority = _validate_priority(body.priority)
    if body.assignee_id is not None and not db.get(User, body.assignee_id):
        raise HTTPException(status_code=400, detail="Assignee not found")

    task = TeamTask(
        case_number=_next_case_number(db),
        title=title,
        description=(body.description or "").strip(),
        status=status,
        priority=priority,
        due_date=body.due_date or None,
        tags=(body.tags or "").strip(),
        reporter_id=user.id,
        assignee_id=body.assignee_id,
    )
    db.add(task)
    db.flush()

    if body.assignee_id:
        _notify(
            db,
            user_id=body.assignee_id,
            kind="assigned",
            title=f"Assigned {task.case_number}",
            body=task.title,
            task_id=task.id,
            actor_id=user.id,
        )

    db.commit()
    db.refresh(task)
    return _task_dict(db, task, include_comments=True)


@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    task = db.get(TeamTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_dict(db, task, include_comments=True)


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    body: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(TeamTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    prev_assignee = task.assignee_id

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title required")
        task.title = title
    if body.description is not None:
        task.description = body.description.strip()
    if body.status is not None:
        task.status = _validate_status(body.status)
    if body.priority is not None:
        task.priority = _validate_priority(body.priority)
    if body.due_date is not None:
        task.due_date = body.due_date or None
    if body.tags is not None:
        task.tags = body.tags.strip()
    if "assignee_id" in body.model_fields_set:
        if body.assignee_id is not None and not db.get(User, body.assignee_id):
            raise HTTPException(status_code=400, detail="Assignee not found")
        task.assignee_id = body.assignee_id

    task.updated_at = datetime.now(timezone.utc)

    if task.assignee_id and task.assignee_id != prev_assignee:
        _notify(
            db,
            user_id=task.assignee_id,
            kind="assigned",
            title=f"Assigned {task.case_number}",
            body=task.title,
            task_id=task.id,
            actor_id=user.id,
        )

    db.commit()
    db.refresh(task)
    return _task_dict(db, task, include_comments=True)


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(TeamTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    is_admin = user_to_dict(user)["is_admin"]
    if not is_admin and task.reporter_id != user.id:
        raise HTTPException(status_code=403, detail="Only reporter or admin can delete")
    db.query(Notification).filter(Notification.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    return {"ok": True}


@router.post("/tasks/{task_id}/comments")
def add_comment(
    task_id: int,
    body: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task = db.get(TeamTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Comment required")

    comment = TaskComment(task_id=task.id, author_id=user.id, body=text)
    db.add(comment)
    task.updated_at = datetime.now(timezone.utc)

    notify_ids = set()
    if task.assignee_id:
        notify_ids.add(task.assignee_id)
    if task.reporter_id:
        notify_ids.add(task.reporter_id)
    for uid in notify_ids:
        _notify(
            db,
            user_id=uid,
            kind="comment",
            title=f"Comment on {task.case_number}",
            body=text[:180],
            task_id=task.id,
            actor_id=user.id,
        )

    db.commit()
    db.refresh(task)
    return _task_dict(db, task, include_comments=True)


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    today = date.today().isoformat()
    total = db.query(func.count(TeamTask.id)).scalar() or 0
    mine = (
        db.query(func.count(TeamTask.id))
        .filter(TeamTask.assignee_id == user.id, TeamTask.status.in_(OPEN_STATUSES))
        .scalar()
        or 0
    )
    overdue = (
        db.query(func.count(TeamTask.id))
        .filter(
            TeamTask.due_date.isnot(None),
            TeamTask.due_date < today,
            TeamTask.status.in_(OPEN_STATUSES),
        )
        .scalar()
        or 0
    )
    due_today = (
        db.query(func.count(TeamTask.id))
        .filter(TeamTask.due_date == today, TeamTask.status.in_(OPEN_STATUSES))
        .scalar()
        or 0
    )

    by_status = {s: 0 for s in STATUSES}
    for status, count in (
        db.query(TeamTask.status, func.count(TeamTask.id)).group_by(TeamTask.status).all()
    ):
        by_status[status] = count

    upcoming = (
        db.query(TeamTask)
        .filter(TeamTask.due_date.isnot(None), TeamTask.status.in_(OPEN_STATUSES))
        .order_by(TeamTask.due_date.asc())
        .limit(8)
        .all()
    )

    return {
        "total": total,
        "mine": mine,
        "overdue": overdue,
        "due_today": due_today,
        "by_status": by_status,
        "upcoming": [_task_dict(db, t) for t in upcoming],
    }


@router.get("/notifications")
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    unread_only: bool = False,
):
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.read == 0)
    rows = query.order_by(Notification.created_at.desc()).limit(40).all()
    unread = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user.id, Notification.read == 0)
        .scalar()
        or 0
    )
    return {
        "unread": unread,
        "items": [
            {
                "id": n.id,
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "task_id": n.task_id,
                "read": bool(n.read),
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in rows
        ],
    }


@router.post("/notifications/read")
def mark_notifications_read(
    body: MarkReadBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Notification).filter(Notification.user_id == user.id, Notification.read == 0)
    if body.ids:
        query = query.filter(Notification.id.in_(body.ids))
    for n in query.all():
        n.read = 1
    db.commit()
    return {"ok": True}
