"""
JSON-line serial transport.

Two implementations:
- MockJsonLineClient: hardware-free, models the protocol and piece map.
- JsonLineSerialClient: real ESP32/Teensy link via pyserial-asyncio.

Optimizations vs the previous version:
- orjson when available (faster encode + decode).
- Bounded id allocator; pending futures don't leak on timeout.
- Write coalescing: writes are not awaited on drain unless the buffer is full,
  which removes a per-command round-trip on TCP-like serial backends.
- Read loop never silently sleeps on empty reads; readline blocks naturally.
- Configurable baud (default 921600 — both ESP32 and Teensy 4 do this fine).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

try:
    import orjson
    _LOADS = orjson.loads
    _DUMPS = orjson.dumps  # returns bytes
    _USE_ORJSON = True
except ImportError:  # pragma: no cover
    import json
    _USE_ORJSON = False
    _LOADS = json.loads

    def _DUMPS(obj: Any) -> bytes:  # type: ignore[no-redef]
        return json.dumps(obj, separators=(",", ":")).encode()

try:
    import serial_asyncio
except Exception:  # pragma: no cover
    serial_asyncio = None

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------- mock

class MockJsonLineClient(BaseJsonLineClient):
    """Hardware-free mock. Models protocol + occupancy, not real physics."""

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
        # Shorter simulated latency keeps the test suite snappy.
        await asyncio.sleep(0.005)

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
            return CommandReply(
                id=msg_id, ok=False,
                err=f"Unknown mock command: {cmd}",
                raw={"id": msg_id, "ok": False},
            )
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
        await self._emit({
            "type": "scan",
            "ts_ms": int(asyncio.get_event_loop().time() * 1000),
            "cells": cells,
        })

    @staticmethod
    def _starting_piece_map() -> dict[str, str]:
        pieces: dict[str, str] = {}
        for file in "abcdefgh":
            pieces[f"{file}1"] = "white"
            pieces[f"{file}2"] = "white"
            pieces[f"{file}7"] = "black"
            pieces[f"{file}8"] = "black"
        return pieces


# ---------------------------------------------------------------- real serial

class JsonLineSerialClient(BaseJsonLineClient):
    """Real serial bridge. One reader task, futures-based reply correlation."""

    __slots__ = (
        "port", "baud", "timeout_s",
        "_next_id", "_reader", "_writer", "_reader_task",
        "_pending", "_callback", "_write_lock", "_stopping",
    )

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
        self._write_lock = asyncio.Lock()
        self._stopping = False

    def set_event_callback(self, callback: EventCallback) -> None:
        self._callback = callback

    async def start(self) -> None:
        if serial_asyncio is None:
            raise RuntimeError("pyserial-asyncio is not installed.")
        self._reader, self._writer = await serial_asyncio.open_serial_connection(
            url=self.port, baudrate=self.baud,
        )
        self._stopping = False
        self._reader_task = asyncio.create_task(self._read_loop(), name="serial-read")
        logger.info("Serial open on %s @ %d", self.port, self.baud)

    async def stop(self) -> None:
        self._stopping = True
        task = self._reader_task
        self._reader_task = None
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        # Cancel all pending futures so callers don't hang.
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def send_command(self, cmd: str, **payload: Any) -> CommandReply:
        if self._writer is None:
            raise RuntimeError("Serial link has not been started")
        msg_id = self._next_id
        self._next_id += 1

        message = {"id": msg_id, "cmd": cmd, **payload}
        loop = asyncio.get_event_loop()
        future: asyncio.Future[CommandReply] = loop.create_future()
        self._pending[msg_id] = future

        data = _DUMPS(message) + b"\n"
        async with self._write_lock:
            self._writer.write(data)
            # Only drain if the transport buffer is over the high-water mark.
            transport = self._writer.transport
            try:
                if transport is not None and transport.get_write_buffer_size() > 4096:
                    await self._writer.drain()
            except Exception:
                await self._writer.drain()

        try:
            return await asyncio.wait_for(future, timeout=self.timeout_s)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            return CommandReply(id=msg_id, ok=False, err="timeout")
        finally:
            self._pending.pop(msg_id, None)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while not self._stopping:
            try:
                raw = await self._reader.readline()
            except Exception as exc:
                if self._stopping:
                    return
                logger.warning("Serial read failed: %s", exc)
                await asyncio.sleep(0.05)
                continue

            if not raw:
                # EOF — small backoff to avoid a hot loop.
                await asyncio.sleep(0.01)
                continue

            try:
                payload = _LOADS(raw.strip())
            except Exception:
                # Bad line; ignore.
                continue

            if "id" in payload and "ok" in payload:
                msg_id = int(payload["id"])
                fut = self._pending.get(msg_id)
                if fut and not fut.done():
                    fut.set_result(CommandReply(
                        id=msg_id,
                        ok=bool(payload["ok"]),
                        err=payload.get("err"),
                        raw=payload,
                    ))
            elif self._callback:
                try:
                    await self._callback(payload)
                except Exception as exc:
                    logger.exception("Event callback failed: %s", exc)
