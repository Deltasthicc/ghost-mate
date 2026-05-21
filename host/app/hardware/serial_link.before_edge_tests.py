from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

try:
    import serial_asyncio
except Exception:  # pragma: no cover - optional until real hardware mode is used
    serial_asyncio = None

JsonDict = dict[str, Any]
EventCallback = Callable[[JsonDict], Awaitable[None]]


@dataclass
class CommandReply:
    id: int
    ok: bool
    err: str | None = None
    raw: JsonDict | None = None


class BaseJsonLineClient:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send_command(self, cmd: str, **payload: Any) -> CommandReply: ...
    def set_event_callback(self, callback: EventCallback) -> None: ...


class MockJsonLineClient(BaseJsonLineClient):
    """Hardware-free mock. Good for UI/backend development before ESP32 is connected."""

    def __init__(self) -> None:
        self._next_id = 1
        self._callback: EventCallback | None = None
        self._started = False
        self._occupied = self._starting_position()

    def set_event_callback(self, callback: EventCallback) -> None:
        self._callback = callback

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send_command(self, cmd: str, **payload: Any) -> CommandReply:
        msg_id = self._next_id
        self._next_id += 1
        await asyncio.sleep(0.03)

        if cmd in {"move", "move_square_to_square"}:
            src, dst = payload.get("from"), payload.get("to")
            if src and dst:
                self._occupied.discard(src)
                self._occupied.add(dst)
            await self._emit({"type": "motion_done", "id": msg_id})
        elif cmd == "capture_move":
            victim, src, dst = payload.get("victim"), payload.get("from"), payload.get("to")
            if victim:
                self._occupied.discard(victim)
            if src and dst:
                self._occupied.discard(src)
                self._occupied.add(dst)
            await self._emit({"type": "motion_done", "id": msg_id})
        elif cmd == "scan":
            await self._emit_scan(full=bool(payload.get("full", True)))

        return CommandReply(id=msg_id, ok=True, raw={"id": msg_id, "ok": True})

    async def _emit(self, event: JsonDict) -> None:
        if self._callback:
            await self._callback(event)

    async def _emit_scan(self, full: bool = True) -> None:
        cells: dict[str, JsonDict] = {}
        for square in [f"{f}{r}" for r in "12345678" for f in "abcdefgh"]:
            occ = 1 if square in self._occupied else 0
            cells[square] = {"o": occ, "p": 1 if occ else 0, "m": 800 if occ else 0}
        await self._emit({"type": "scan", "ts_ms": int(asyncio.get_event_loop().time() * 1000), "cells": cells})

    @staticmethod
    def _starting_position() -> set[str]:
        return {f"{f}2" for f in "abcdefgh"} | {f"{f}7" for f in "abcdefgh"} | set(
            ["a1", "b1", "c1", "d1", "e1", "f1", "g1", "h1", "a8", "b8", "c8", "d8", "e8", "f8", "g8", "h8"]
        )


class JsonLineSerialClient(BaseJsonLineClient):
    def __init__(self, port: str, baud: int, timeout_s: float = 5.0) -> None:
        self.port = port
        self.baud = baud
        self.timeout_s = timeout_s
        self._next_id = 1
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[CommandReply]] = {}
        self._callback: EventCallback | None = None

    def set_event_callback(self, callback: EventCallback) -> None:
        self._callback = callback

    async def start(self) -> None:
        if serial_asyncio is None:
            raise RuntimeError("pyserial-asyncio is not installed. Install project dependencies first.")
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self.port, baudrate=self.baud
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()

    async def send_command(self, cmd: str, **payload: Any) -> CommandReply:
        if self._writer is None:
            raise RuntimeError("Serial link has not been started")
        msg_id = self._next_id
        self._next_id += 1
        message = {"id": msg_id, "cmd": cmd, **payload}
        future: asyncio.Future[CommandReply] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future
        self._writer.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
        await self._writer.drain()
        try:
            return await asyncio.wait_for(future, timeout=self.timeout_s)
        finally:
            self._pending.pop(msg_id, None)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while True:
            raw = await self._reader.readline()
            if not raw:
                await asyncio.sleep(0.01)
                continue
            try:
                payload = json.loads(raw.decode(errors="replace").strip())
            except json.JSONDecodeError:
                continue

            if "id" in payload and "ok" in payload:
                msg_id = int(payload["id"])
                fut = self._pending.get(msg_id)
                if fut and not fut.done():
                    fut.set_result(CommandReply(id=msg_id, ok=bool(payload["ok"]), err=payload.get("err"), raw=payload))
            elif self._callback:
                await self._callback(payload)
