from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class EventType(StrEnum):
    LOCAL_MOVE_CANDIDATE = "LOCAL_MOVE_CANDIDATE"
    REMOTE_MOVE_RECEIVED = "REMOTE_MOVE_RECEIVED"
    ROBOT_MOVE_COMPLETE = "ROBOT_MOVE_COMPLETE"
    SCAN_RECEIVED = "SCAN_RECEIVED"
    SCAN_MISMATCH = "SCAN_MISMATCH"
    GAME_END = "GAME_END"
    FAULT = "FAULT"
    STATE_CHANGED = "STATE_CHANGED"


@dataclass(frozen=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Small async pub/sub bus used by API, WebSocket, and game services."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event: Event) -> None:
        async with self._lock:
            dead: list[asyncio.Queue[Event]] = []
            for queue in self._subscribers:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(queue)
            for queue in dead:
                self._subscribers.discard(queue)

    async def subscribe(self, maxsize: int = 100) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)
