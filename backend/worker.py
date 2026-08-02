"""Outbox publisher worker (also usable as in-process drain)."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

from .db import OutboxEvent, SessionLocal
from .realtime import hub

MAX_ATTEMPTS = 8


def _now():
    return datetime.now(timezone.utc)


def claim_and_publish_once(loop: asyncio.AbstractEventLoop | None = None) -> int:
    db = SessionLocal()
    published = 0
    try:
        rows = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.published_at.is_(None), OutboxEvent.attempts < MAX_ATTEMPTS)
            .order_by(OutboxEvent.id.asc())
            .limit(50)
            .all()
        )
        for row in rows:
            row.attempts = (row.attempts or 0) + 1
            try:
                envelope = json.loads(row.payload_json)
                if loop and loop.is_running():
                    fut = asyncio.run_coroutine_threadsafe(
                        hub.publish(row.workspace_id, envelope), loop
                    )
                    fut.result(timeout=5)
                row.published_at = _now()
                row.last_error = None
                published += 1
            except Exception as exc:  # noqa: BLE001
                row.last_error = str(exc)[:500]
            db.commit()
    finally:
        db.close()
    return published


def run_forever(interval: float = 1.0) -> None:
    print("outbox worker started", flush=True)
    while True:
        try:
            claim_and_publish_once()
        except Exception as exc:  # noqa: BLE001
            print(f"worker error: {exc}", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
