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
    """
    Hardware-free mock.

    This deliberately models only the serial protocol and board occupancy, not real physics.
    White pieces use negative polarity. Black pieces use positive polarity.
    """

    def __init__(self) -> None:
        self._next_id = 1
        self._callback: EventCallback | None = None
        self._started = False
        self._pieces = self._starting_piece_map()

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
            src = payload.get("from")
            dst = payload.get("to")
            if src and dst:
                color = self._pieces.pop(src, None)
                self._pieces.pop(dst, None)
                if color:
                    self._pieces[dst] = color
            await self._emit({"type": "motion_done", "id": msg_id})

        elif cmd == "capture_move":
            victim = payload.get("victim")
            src = payload.get("from")
            dst = payload.get("to")
            if victim:
                self._pieces.pop(victim, None)
            if src and dst:
                color = self._pieces.pop(src, None)
                self._pieces.pop(dst, None)
                if color:
                    self._pieces[dst] = color
            await self._emit({"type": "motion_done", "id": msg_id})

        elif cmd == "scan":
            await self._emit_scan(full=bool(payload.get("full", True)))

        elif cmd in {"home", "park", "set_em"}:
            pass

        else:
            return CommandReply(id=msg_id, ok=False, err=f"Unknown mock command: {cmd}", raw={"id": msg_id, "ok": False})

        return CommandReply(id=msg_id, ok=True, raw={"id": msg_id, "ok": True})

    async def _emit(self, event: JsonDict) -> None:
        if self._callback:
            await self._callback(event)

    async def _emit_scan(self, full: bool = True) -> None:
        cells: dict[str, JsonDict] = {}

        for rank in "12345678":
            for file in "abcdefgh":
                square = f"{file}{rank}"
                color = self._pieces.get(square)
                occupied = color is not None
                polarity = -1 if color == "white" else 1 if color == "black" else 0
                magnitude = 800 if occupied else 0
                cells[square] = {"o": int(occupied), "p": polarity, "m": magnitude}

        await self._emit(
            {
                "type": "scan",
                "ts_ms": int(asyncio.get_event_loop().time() * 1000),
                "cells": cells,
            }
        )

    @staticmethod
    def _starting_piece_map() -> dict[str, str]:
        pieces: dict[str, str] = {}

        for file in "abcdefgh":
            pieces[f"{file}1"] = "white"
            pieces[f"{file}2"] = "white"
            pieces[f"{file}7"] = "black"
            pieces[f"{file}8"] = "black"

        return pieces


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
            url=self.port,
            baudrate=self.baud,
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
                future = self._pending.get(msg_id)

                if future and not future.done():
                    future.set_result(
                        CommandReply(
                            id=msg_id,
                            ok=bool(payload["ok"]),
                            err=payload.get("err"),
                            raw=payload,
                        )
                    )

            elif self._callback:
                await self._callback(payload)
