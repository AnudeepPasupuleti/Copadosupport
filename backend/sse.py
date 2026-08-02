"""Authenticated SSE event stream."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from . import config
from .db import OutboxEvent, User, Workspace, get_db
from .deps import get_current_user
from .realtime import hub
from .workspaces import get_current_workspace

router = APIRouter(prefix="/api/events", tags=["events"])


def _sse_format(event_id: str, data: dict) -> str:
    return f"id: {event_id}\nevent: message\ndata: {json.dumps(data)}\n\n"


@router.get("/stream")
async def event_stream(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    workspace: Workspace = Depends(get_current_workspace),
    last_event_id: Optional[str] = None,
):
    if not config.FEATURE_REALTIME_SSE:
        raise HTTPException(status_code=404, detail="Realtime SSE disabled")

    # Header takes precedence over query
    header_id = request.headers.get("last-event-id") or last_event_id

    async def gen():
        # Replay unpublished / recent published after cursor
        if header_id:
            last = (
                db.query(OutboxEvent)
                .filter(OutboxEvent.event_id == header_id)
                .first()
            )
            q = db.query(OutboxEvent).filter(OutboxEvent.workspace_id == workspace.id)
            if last:
                q = q.filter(OutboxEvent.id > last.id)
            else:
                # Unknown cursor — send refetch hint
                yield _sse_format(
                    "refetch",
                    {
                        "event_id": "refetch",
                        "schema_version": 1,
                        "event_type": "client.refetch",
                        "workspace_id": workspace.id,
                        "data": {"reason": "cursor_expired"},
                    },
                )
                q = q.filter(OutboxEvent.id > 0).order_by(OutboxEvent.id.desc()).limit(0)
            for row in q.order_by(OutboxEvent.id.asc()).limit(200).all():
                try:
                    envelope = json.loads(row.payload_json)
                except json.JSONDecodeError:
                    continue
                yield _sse_format(row.event_id, envelope)

        queue = await hub.subscribe(workspace.id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    envelope = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield _sse_format(envelope.get("event_id", ""), envelope)
                except asyncio.TimeoutError:
                    yield f": heartbeat {datetime.now(timezone.utc).isoformat()}\n\n"
        finally:
            await hub.unsubscribe(workspace.id, queue)

    return StreamingResponse(gen(), media_type="text/event-stream")
