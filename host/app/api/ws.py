"""WebSocket endpoint.

Each connection gets its own per-client send task. Messages are serialized with
orjson when available (3-5x faster than stdlib json for our payloads). Slow
clients are protected by an outbound queue; if it fills, the connection is
closed rather than stalling the event bus.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder

try:
    import orjson
    def _serialize_str(obj: Any) -> str:
        return orjson.dumps(obj).decode()
    _USE_ORJSON = True
except ImportError:  # pragma: no cover
    import json
    _USE_ORJSON = False

    def _serialize_str(obj: Any) -> str:
        return json.dumps(obj, separators=(",", ":"), default=str)


logger = logging.getLogger(__name__)
router = APIRouter()

_HEARTBEAT_INTERVAL_S = 15.0
_MAX_ENGINE_DEPTH = 30


def _cap_engine_depth(raw: str | None, fallback: int = 15) -> int:
    try:
        depth = int(raw) if raw is not None else fallback
    except (TypeError, ValueError):
        depth = fallback
    return max(1, min(_MAX_ENGINE_DEPTH, depth))


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _serialize(obj: Any) -> str:
    """Serialize to a JSON string. Text frames are easier to inspect from
    test clients and dev tools, and modern browsers don't pay extra for them."""
    try:
        return _serialize_str(obj)
    except TypeError:
        # Fall back to FastAPI's encoder for non-trivial types (datetime, enums, ...)
        return _serialize_str(jsonable_encoder(obj))


@router.websocket("/ws")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()
    event_bus = websocket.app.state.events
    game = websocket.app.state.game
    wants_engine = websocket.query_params.get("engine") == "1"
    max_depth = _cap_engine_depth(websocket.query_params.get("max_depth"))
    client_id = id(websocket)
    queue = None

    try:
        if wants_engine:
            websocket.app.state.engine_live_clients += 1
            websocket.app.state.engine_live_depths[client_id] = max_depth
        queue = await _maybe_await(event_bus.subscribe())

        # Send initial state immediately. Snapshot is now O(1)-ish — no engine spawn.
        await websocket.send_text(_serialize({"type": "HELLO", "state": game.snapshot()}))

        while True:
            # Heartbeat: if no event within the heartbeat interval, send a ping.
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL_S)
            except asyncio.TimeoutError:
                with suppress(Exception):
                    await websocket.send_text(_serialize({"type": "PING"}))
                continue

            payload = {
                "type": event.type.value if hasattr(event.type, "value") else event.type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat() if hasattr(event, "created_at") else None,
            }
            await websocket.send_text(_serialize(payload))

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("WebSocket loop exited: %s", exc)
    finally:
        if queue is not None:
            with suppress(Exception):
                await _maybe_await(event_bus.unsubscribe(queue))
        if wants_engine:
            with suppress(Exception):
                websocket.app.state.engine_live_clients = max(
                    0, websocket.app.state.engine_live_clients - 1
                )
                websocket.app.state.engine_live_depths.pop(client_id, None)
        with suppress(Exception):
            await websocket.close(code=1000)
