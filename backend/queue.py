"""Shared Team Queue API — cases, comments, dashboard, notifications."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from . import config
from .db import (
    CaseActivity,
    CommentMention,
    IdempotencyKey,
    Notification,
    TaskComment,
    TeamTask,
    User,
    Workspace,
    WorkspaceCaseCounter,
    get_db,
)
from .deps import get_current_user, is_manager_or_admin, user_to_dict
from .events import (
    activity_dict,
    enqueue_outbox,
    record_activity,
    snapshot_task,
)
from .realtime import hub
from .workspaces import get_current_workspace

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
    team_id: Optional[int] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    tags: Optional[str] = None
    assignee_id: Optional[int] = None
    team_id: Optional[int] = None
    version: Optional[int] = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    mention_ids: list[int] = Field(default_factory=list)


class MarkReadBody(BaseModel):
    ids: Optional[list[int]] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_due(due_date: Optional[str]) -> tuple[Optional[str], Optional[datetime]]:
    if not due_date:
        return None, None
    value = due_date.strip()
    if not value:
        return None, None
    try:
        y, m, d = [int(x) for x in value.split("-")[:3]]
        due_at = datetime(y, m, d, 12, 0, tzinfo=timezone.utc)
        return f"{y:04d}-{m:02d}-{d:02d}", due_at
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="due_date must be YYYY-MM-DD") from exc


def _next_case_number(db: Session, workspace: Workspace) -> str:
    counter = db.get(WorkspaceCaseCounter, workspace.id)
    if not counter:
        counter = WorkspaceCaseCounter(workspace_id=workspace.id, next_number=1001)
        db.add(counter)
        db.flush()
    n = counter.next_number
    counter.next_number = n + 1
    db.flush()
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


def _task_in_workspace(task: Optional[TeamTask], workspace: Workspace) -> TeamTask:
    if not task or task.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _task_dict(db: Session, task: TeamTask, include_comments: bool = False) -> dict:
    reporter = db.get(User, task.reporter_id)
    assignee = db.get(User, task.assignee_id) if task.assignee_id else None
    due_date = task.due_date
    if not due_date and task.due_at:
        due_date = task.due_at.date().isoformat()
    data = {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "team_id": task.team_id,
        "case_number": task.case_number,
        "title": task.title,
        "description": task.description or "",
        "status": task.status,
        "priority": task.priority,
        "due_date": due_date,
        "due_at": task.due_at.isoformat() if task.due_at else None,
        "version": task.version or 1,
        "tags": task.tags or "",
        "reporter": _user_brief(reporter),
        "assignee": _user_brief(assignee),
        "assignee_id": task.assignee_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "resolved_at": task.resolved_at.isoformat() if task.resolved_at else None,
        "closed_at": task.closed_at.isoformat() if task.closed_at else None,
        "comment_count": len(task.comments) if task.comments is not None else 0,
    }
    if include_comments:
        comments = []
        for c in task.comments or []:
            author = db.get(User, c.author_id)
            mention_ids = [m.user_id for m in (c.mentions or [])]
            comments.append(
                {
                    "id": c.id,
                    "body": c.body,
                    "author": _user_brief(author),
                    "mention_ids": mention_ids,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
            )
        data["comments"] = comments
    return data


def _notify(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
    kind: str,
    title: str,
    body: str,
    task_id: Optional[int],
    actor_id: int,
    activity_id: Optional[int] = None,
) -> Optional[Notification]:
    if user_id == actor_id:
        return None
    row = Notification(
        workspace_id=workspace_id,
        user_id=user_id,
        kind=kind,
        title=title,
        body=body,
        task_id=task_id,
        activity_id=activity_id,
        read=0,
    )
    db.add(row)
    db.flush()
    return row


async def _publish_live(db: Session, outbox_id: int) -> None:
    from .db import OutboxEvent

    row = db.get(OutboxEvent, outbox_id)
    if not row or row.published_at:
        return
    try:
        envelope = json.loads(row.payload_json)
        await hub.publish(row.workspace_id, envelope)
        row.published_at = _now()
        row.attempts = (row.attempts or 0) + 1
        db.commit()
    except Exception as exc:  # noqa: BLE001
        row.attempts = (row.attempts or 0) + 1
        row.last_error = str(exc)[:500]
        db.commit()


def _validate_status(status: str) -> str:
    if status not in STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    return status


def _validate_priority(priority: str) -> str:
    if priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")
    return priority


def _idempotency_get(
    db: Session, workspace_id: int, user_id: int, key: Optional[str], method: str, path: str
) -> Optional[dict]:
    if not key:
        return None
    row = (
        db.query(IdempotencyKey)
        .filter(
            IdempotencyKey.workspace_id == workspace_id,
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == key.strip(),
        )
        .first()
    )
    if not row:
        return None
    if row.method != method or row.path != path:
        raise HTTPException(status_code=409, detail="Idempotency-Key reused for a different request")
    return json.loads(row.response_json)


def _idempotency_store(
    db: Session,
    workspace_id: int,
    user_id: int,
    key: Optional[str],
    method: str,
    path: str,
    payload: dict,
) -> None:
    if not key:
        return
    db.add(
        IdempotencyKey(
            workspace_id=workspace_id,
            user_id=user_id,
            key=key.strip(),
            method=method,
            path=path,
            response_json=json.dumps(payload),
        )
    )


@router.get("/users")
def list_teammates(
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    _user: User = Depends(get_current_user),
):
    from .db import WorkspaceMember

    member_ids = [
        m.user_id
        for m in db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.active.is_(True))
        .all()
    ]
    users = (
        db.query(User)
        .filter(User.id.in_(member_ids))
        .order_by(User.name.asc(), User.email.asc())
        .all()
        if member_ids
        else []
    )
    return [_user_brief(u) for u in users]


@router.get("/meta")
def queue_meta(
    _user: User = Depends(get_current_user),
    _workspace: Workspace = Depends(get_current_workspace),
):
    return {
        "statuses": list(STATUSES),
        "priorities": list(PRIORITIES),
        "features": {
            "realtime_sse": config.FEATURE_REALTIME_SSE,
            "mentions": config.FEATURE_MENTIONS,
        },
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
    workspace: Workspace = Depends(get_current_workspace),
    q: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_id: Optional[int] = None,
    mine: bool = False,
    scope: str = "all",
    cursor: Optional[int] = None,
    limit: int = 50,
):
    scope = (scope or "all").strip().lower()
    if scope not in ("all", "assigned", "created"):
        raise HTTPException(status_code=400, detail="scope must be all, assigned, or created")
    limit = max(1, min(limit, 100))

    query = db.query(TeamTask).filter(TeamTask.workspace_id == workspace.id)
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

    if scope == "assigned" or mine:
        query = query.filter(TeamTask.assignee_id == user.id)
    elif scope == "created":
        query = query.filter(TeamTask.reporter_id == user.id)
    elif assignee_id is not None:
        query = query.filter(TeamTask.assignee_id == assignee_id)

    if cursor is not None:
        query = query.filter(TeamTask.id < cursor)

    tasks = (
        query.options(joinedload(TeamTask.comments))
        .order_by(TeamTask.updated_at.desc(), TeamTask.id.desc())
        .limit(limit)
        .all()
    )
    items = [_task_dict(db, t) for t in tasks]
    next_cursor = tasks[-1].id if len(tasks) == limit else None
    return {"items": items, "next_cursor": next_cursor}


@router.post("/tasks")
async def create_task(
    body: TaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    path = "/api/queue/tasks"
    cached = _idempotency_get(db, workspace.id, user.id, idempotency_key, "POST", path)
    if cached is not None:
        return cached

    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title required")
    status = _validate_status(body.status)
    priority = _validate_priority(body.priority)
    if body.assignee_id is not None and not db.get(User, body.assignee_id):
        raise HTTPException(status_code=400, detail="Assignee not found")
    due_date, due_at = _parse_due(body.due_date)

    task = TeamTask(
        workspace_id=workspace.id,
        team_id=body.team_id,
        case_number=_next_case_number(db, workspace),
        title=title,
        description=(body.description or "").strip(),
        status=status,
        priority=priority,
        due_date=due_date,
        due_at=due_at,
        tags=(body.tags or "").strip(),
        reporter_id=user.id,
        assignee_id=body.assignee_id,
        version=1,
    )
    db.add(task)
    db.flush()

    activity = record_activity(
        db,
        workspace_id=workspace.id,
        case_id=task.id,
        actor_id=user.id,
        activity_type="case.created",
        after=snapshot_task(task),
    )
    outbox = enqueue_outbox(
        db,
        workspace_id=workspace.id,
        event_type="case.created",
        aggregate_type="case",
        aggregate_id=task.id,
        aggregate_version=task.version,
        actor_id=user.id,
        data={"case_number": task.case_number},
        topic="case.created",
    )

    if body.assignee_id:
        _notify(
            db,
            workspace_id=workspace.id,
            user_id=body.assignee_id,
            kind="assigned",
            title=f"Assigned {task.case_number}",
            body=task.title,
            task_id=task.id,
            actor_id=user.id,
            activity_id=activity.id,
        )
        enqueue_outbox(
            db,
            workspace_id=workspace.id,
            event_type="case.assigned",
            aggregate_type="case",
            aggregate_id=task.id,
            aggregate_version=task.version,
            actor_id=user.id,
            data={"assignee_id": body.assignee_id},
            topic="case.assigned",
        )

    payload = _task_dict(db, task, include_comments=True)
    _idempotency_store(db, workspace.id, user.id, idempotency_key, "POST", path, payload)
    db.commit()
    await _publish_live(db, outbox.id)
    db.refresh(task)
    return payload


@router.get("/tasks/{task_id}")
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    _user: User = Depends(get_current_user),
):
    task = (
        db.query(TeamTask)
        .options(joinedload(TeamTask.comments).joinedload(TaskComment.mentions))
        .filter(TeamTask.id == task_id)
        .first()
    )
    task = _task_in_workspace(task, workspace)
    return _task_dict(db, task, include_comments=True)


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    body: TaskUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    task = db.get(TeamTask, task_id)
    task = _task_in_workspace(task, workspace)

    if body.version is None:
        raise HTTPException(status_code=400, detail="version is required")
    if body.version != (task.version or 1):
        return JSONResponse(
            status_code=409,
            content={
                "code": "version_conflict",
                "message": "Case was updated by someone else",
                "task": _task_dict(db, task, include_comments=True),
            },
        )

    before = snapshot_task(task)
    prev_assignee = task.assignee_id
    prev_status = task.status
    prev_priority = task.priority
    prev_due = task.due_date

    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title required")
        task.title = title
    if body.description is not None:
        task.description = body.description.strip()
    if body.status is not None:
        task.status = _validate_status(body.status)
        if task.status == "resolved" and not task.resolved_at:
            task.resolved_at = _now()
        if task.status == "closed" and not task.closed_at:
            task.closed_at = _now()
    if body.priority is not None:
        task.priority = _validate_priority(body.priority)
    if body.due_date is not None:
        due_date, due_at = _parse_due(body.due_date)
        task.due_date = due_date
        task.due_at = due_at
    if body.tags is not None:
        task.tags = body.tags.strip()
    if body.team_id is not None:
        task.team_id = body.team_id
    if "assignee_id" in body.model_fields_set:
        if body.assignee_id is not None and not db.get(User, body.assignee_id):
            raise HTTPException(status_code=400, detail="Assignee not found")
        task.assignee_id = body.assignee_id

    task.version = (task.version or 1) + 1
    task.updated_at = _now()
    after = snapshot_task(task)

    activity = record_activity(
        db,
        workspace_id=workspace.id,
        case_id=task.id,
        actor_id=user.id,
        activity_type="case.updated",
        before=before,
        after=after,
    )
    outboxes = [
        enqueue_outbox(
            db,
            workspace_id=workspace.id,
            event_type="case.updated",
            aggregate_type="case",
            aggregate_id=task.id,
            aggregate_version=task.version,
            actor_id=user.id,
            data={"before": before, "after": after},
        )
    ]
    if task.status != prev_status:
        outboxes.append(
            enqueue_outbox(
                db,
                workspace_id=workspace.id,
                event_type="case.status_changed",
                aggregate_type="case",
                aggregate_id=task.id,
                aggregate_version=task.version,
                actor_id=user.id,
                data={"from": prev_status, "to": task.status},
            )
        )
    if task.priority != prev_priority:
        outboxes.append(
            enqueue_outbox(
                db,
                workspace_id=workspace.id,
                event_type="case.priority_changed",
                aggregate_type="case",
                aggregate_id=task.id,
                aggregate_version=task.version,
                actor_id=user.id,
                data={"from": prev_priority, "to": task.priority},
            )
        )
    if task.due_date != prev_due:
        outboxes.append(
            enqueue_outbox(
                db,
                workspace_id=workspace.id,
                event_type="case.due_changed",
                aggregate_type="case",
                aggregate_id=task.id,
                aggregate_version=task.version,
                actor_id=user.id,
                data={"from": prev_due, "to": task.due_date},
            )
        )

    if task.assignee_id and task.assignee_id != prev_assignee:
        _notify(
            db,
            workspace_id=workspace.id,
            user_id=task.assignee_id,
            kind="assigned",
            title=f"Assigned {task.case_number}",
            body=task.title,
            task_id=task.id,
            actor_id=user.id,
            activity_id=activity.id,
        )
        outboxes.append(
            enqueue_outbox(
                db,
                workspace_id=workspace.id,
                event_type="case.assigned",
                aggregate_type="case",
                aggregate_id=task.id,
                aggregate_version=task.version,
                actor_id=user.id,
                data={"assignee_id": task.assignee_id},
            )
        )

    db.commit()
    for ob in outboxes:
        await _publish_live(db, ob.id)
    db.refresh(task)
    return _task_dict(db, task, include_comments=True)


@router.delete("/tasks/{task_id}")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    task = db.get(TeamTask, task_id)
    task = _task_in_workspace(task, workspace)
    is_admin = is_manager_or_admin(user)
    if not is_admin and task.reporter_id != user.id:
        raise HTTPException(status_code=403, detail="Only reporter, manager, or admin can delete")
    db.query(Notification).filter(Notification.task_id == task_id).delete()
    db.query(CaseActivity).filter(CaseActivity.case_id == task_id).delete()
    db.delete(task)
    db.commit()
    return {"ok": True}


@router.post("/tasks/{task_id}/comments")
async def add_comment(
    task_id: int,
    body: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    path = f"/api/queue/tasks/{task_id}/comments"
    cached = _idempotency_get(db, workspace.id, user.id, idempotency_key, "POST", path)
    if cached is not None:
        return cached

    task = db.get(TeamTask, task_id)
    task = _task_in_workspace(task, workspace)
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Comment required")

    mention_ids = []
    if config.FEATURE_MENTIONS:
        mention_ids = sorted({int(x) for x in (body.mention_ids or []) if x and x != user.id})

    comment = TaskComment(task_id=task.id, author_id=user.id, body=text)
    db.add(comment)
    db.flush()
    for mid in mention_ids:
        if db.get(User, mid):
            db.add(CommentMention(comment_id=comment.id, user_id=mid))

    task.version = (task.version or 1) + 1
    task.updated_at = _now()

    activity = record_activity(
        db,
        workspace_id=workspace.id,
        case_id=task.id,
        actor_id=user.id,
        activity_type="comment.created",
        after={"comment_id": comment.id, "preview": text[:180]},
    )
    outbox = enqueue_outbox(
        db,
        workspace_id=workspace.id,
        event_type="comment.created",
        aggregate_type="case",
        aggregate_id=task.id,
        aggregate_version=task.version,
        actor_id=user.id,
        data={"comment_id": comment.id},
    )

    notify_ids = set()
    if task.assignee_id:
        notify_ids.add(task.assignee_id)
    if task.reporter_id:
        notify_ids.add(task.reporter_id)
    for uid in notify_ids:
        _notify(
            db,
            workspace_id=workspace.id,
            user_id=uid,
            kind="comment",
            title=f"Comment on {task.case_number}",
            body=text[:180],
            task_id=task.id,
            actor_id=user.id,
            activity_id=activity.id,
        )

    for mid in mention_ids:
        _notify(
            db,
            workspace_id=workspace.id,
            user_id=mid,
            kind="mention",
            title=f"Mentioned on {task.case_number}",
            body=text[:180],
            task_id=task.id,
            actor_id=user.id,
            activity_id=activity.id,
        )
        enqueue_outbox(
            db,
            workspace_id=workspace.id,
            event_type="mention.created",
            aggregate_type="case",
            aggregate_id=task.id,
            aggregate_version=task.version,
            actor_id=user.id,
            data={"user_id": mid, "comment_id": comment.id},
        )

    payload = _task_dict(db, task, include_comments=True)
    _idempotency_store(db, workspace.id, user.id, idempotency_key, "POST", path, payload)
    db.commit()
    await _publish_live(db, outbox.id)
    return payload


@router.get("/tasks/{task_id}/activities")
def list_activities(
    task_id: int,
    db: Session = Depends(get_db),
    workspace: Workspace = Depends(get_current_workspace),
    _user: User = Depends(get_current_user),
    after: Optional[int] = None,
    limit: int = 50,
):
    task = db.get(TeamTask, task_id)
    _task_in_workspace(task, workspace)
    limit = max(1, min(limit, 100))
    query = db.query(CaseActivity).filter(
        CaseActivity.workspace_id == workspace.id,
        CaseActivity.case_id == task_id,
    )
    if after is not None:
        query = query.filter(CaseActivity.id > after)
    rows = query.order_by(CaseActivity.id.asc()).limit(limit).all()
    return {"items": [activity_dict(r) for r in rows]}


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
):
    today = date.today().isoformat()
    base = db.query(TeamTask).filter(TeamTask.workspace_id == workspace.id)
    total = base.with_entities(func.count(TeamTask.id)).scalar() or 0
    mine = (
        db.query(func.count(TeamTask.id))
        .filter(
            TeamTask.workspace_id == workspace.id,
            TeamTask.assignee_id == user.id,
            TeamTask.status.in_(OPEN_STATUSES),
        )
        .scalar()
        or 0
    )
    overdue = (
        db.query(func.count(TeamTask.id))
        .filter(
            TeamTask.workspace_id == workspace.id,
            TeamTask.due_date.isnot(None),
            TeamTask.due_date < today,
            TeamTask.status.in_(OPEN_STATUSES),
        )
        .scalar()
        or 0
    )
    due_today = (
        db.query(func.count(TeamTask.id))
        .filter(
            TeamTask.workspace_id == workspace.id,
            TeamTask.due_date == today,
            TeamTask.status.in_(OPEN_STATUSES),
        )
        .scalar()
        or 0
    )

    by_status = {s: 0 for s in STATUSES}
    for status, count in (
        db.query(TeamTask.status, func.count(TeamTask.id))
        .filter(TeamTask.workspace_id == workspace.id)
        .group_by(TeamTask.status)
        .all()
    ):
        by_status[status] = count

    upcoming = (
        db.query(TeamTask)
        .filter(
            TeamTask.workspace_id == workspace.id,
            TeamTask.due_date.isnot(None),
            TeamTask.status.in_(OPEN_STATUSES),
        )
        .order_by(TeamTask.due_date.asc())
        .limit(8)
        .all()
    )

    my_tickets = (
        db.query(TeamTask)
        .filter(
            TeamTask.workspace_id == workspace.id,
            TeamTask.assignee_id == user.id,
            TeamTask.status.in_(OPEN_STATUSES),
        )
        .order_by(TeamTask.updated_at.desc())
        .limit(10)
        .all()
    )

    return {
        "total": total,
        "mine": mine,
        "overdue": overdue,
        "due_today": due_today,
        "by_status": by_status,
        "upcoming": [_task_dict(db, t) for t in upcoming],
        "my_tickets": [_task_dict(db, t) for t in my_tickets],
    }


@router.get("/notifications")
def list_notifications(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    unread_only: bool = False,
):
    query = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.workspace_id == workspace.id,
    )
    if unread_only:
        query = query.filter(Notification.read == 0)
    rows = query.order_by(Notification.created_at.desc()).limit(40).all()
    unread = (
        db.query(func.count(Notification.id))
        .filter(
            Notification.user_id == user.id,
            Notification.workspace_id == workspace.id,
            Notification.read == 0,
        )
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
    workspace: Workspace = Depends(get_current_workspace),
):
    query = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.workspace_id == workspace.id,
        Notification.read == 0,
    )
    if body.ids:
        query = query.filter(Notification.id.in_(body.ids))
    for n in query.all():
        n.read = 1
    db.commit()
    return {"ok": True}
