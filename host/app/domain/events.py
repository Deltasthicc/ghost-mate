"""Async pub/sub event bus.

Publish is now lock-free and lazily garbage-collects full queues, so a slow
subscriber can't stall the entire app. Subscribe/unsubscribe is the only path
that touches the lock.
"""
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
    ENGINE_UPDATE = "ENGINE_UPDATE"


@dataclass(frozen=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EventBus:
    """Tiny async pub/sub.

    Publish path takes no lock: iterates a snapshot of the subscriber set and
    fans out non-blocking puts. Slow subscribers get dropped from a queue rather
    than blocking everyone else.
    """

    __slots__ = ("_subscribers", "_lock", "_default_max")

    def __init__(self, default_max: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._lock = asyncio.Lock()
        self._default_max = default_max

    async def publish(self, event: Event) -> None:
        # Snapshot to a tuple so iteration is safe without holding the lock.
        dead: list[asyncio.Queue[Event]] | None = None
        for q in tuple(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Queue is wedged — drop the oldest event to make room and try
                # again. If that still fails, mark for removal.
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    if dead is None:
                        dead = []
                    dead.append(q)
        if dead:
            async with self._lock:
                for q in dead:
                    self._subscribers.discard(q)

    def publish_nowait(self, event: Event) -> None:
        """Synchronous publish for use from sync callbacks. Best-effort."""
        for q in tuple(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass

    async def subscribe(self, maxsize: int | None = None) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize or self._default_max)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
