"""Case activity + transactional outbox helpers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from .db import CaseActivity, OutboxEvent, TeamTask


def _now() -> datetime:
    return datetime.now(timezone.utc)


def record_activity(
    db: Session,
    *,
    workspace_id: int,
    case_id: int,
    actor_id: Optional[int],
    activity_type: str,
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    correlation_id: Optional[str] = None,
) -> CaseActivity:
    row = CaseActivity(
        workspace_id=workspace_id,
        case_id=case_id,
        actor_id=actor_id,
        activity_type=activity_type,
        before_json=json.dumps(before or {}),
        after_json=json.dumps(after or {}),
        correlation_id=correlation_id,
        occurred_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def enqueue_outbox(
    db: Session,
    *,
    workspace_id: int,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int,
    aggregate_version: int,
    actor_id: Optional[int],
    data: Optional[dict] = None,
    topic: Optional[str] = None,
) -> OutboxEvent:
    event_id = uuid.uuid4().hex
    topic_name = topic or event_type
    envelope = {
        "event_id": event_id,
        "schema_version": 1,
        "event_type": event_type,
        "workspace_id": workspace_id,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "aggregate_version": aggregate_version,
        "actor_id": actor_id,
        "occurred_at": _now().isoformat(),
        "data": data or {},
    }
    row = OutboxEvent(
        event_id=event_id,
        schema_version=1,
        event_type=event_type,
        topic=topic_name,
        workspace_id=workspace_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        actor_id=actor_id,
        payload_json=json.dumps(envelope),
        occurred_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def activity_dict(row: CaseActivity) -> dict[str, Any]:
    return {
        "id": row.id,
        "case_id": row.case_id,
        "actor_id": row.actor_id,
        "type": row.activity_type,
        "before": json.loads(row.before_json or "{}"),
        "after": json.loads(row.after_json or "{}"),
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        "correlation_id": row.correlation_id,
    }


def snapshot_task(task: TeamTask) -> dict:
    return {
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date,
        "assignee_id": task.assignee_id,
        "version": task.version,
    }
