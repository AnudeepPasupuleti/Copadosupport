"""In-process SSE fan-out hub (single web instance)."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any, Optional


class EventHub:
    def __init__(self) -> None:
        self._subs: dict[int, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, workspace_id: int) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._subs[workspace_id].add(q)
        return q

    async def unsubscribe(self, workspace_id: int, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subs[workspace_id].discard(q)
            if not self._subs[workspace_id]:
                self._subs.pop(workspace_id, None)

    async def publish(self, workspace_id: int, envelope: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._subs.get(workspace_id, ()))
        for q in targets:
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(envelope)
                except asyncio.QueueFull:
                    pass

    def publish_threadsafe(self, loop: Optional[asyncio.AbstractEventLoop], workspace_id: int, envelope: dict) -> None:
        if loop is None or loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self.publish(workspace_id, envelope), loop)


hub = EventHub()


def envelope_from_outbox_payload(payload_json: str) -> dict:
    return json.loads(payload_json or "{}")
