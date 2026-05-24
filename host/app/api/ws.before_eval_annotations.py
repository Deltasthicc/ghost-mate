from __future__ import annotations

import asyncio
import inspect
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


async def maybe_await(value):
    """Support both sync and async event-bus methods safely."""
    if inspect.isawaitable(value):
        return await value
    return value


@router.websocket("/ws")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()

    event_bus = websocket.app.state.events
    game = websocket.app.state.game
    queue = None

    try:
        queue = await maybe_await(event_bus.subscribe())

        await websocket.send_json(
            {
                "type": "HELLO",
                "state": game.snapshot(),
            }
        )

        while True:
            event = await queue.get()
            await websocket.send_json(event)

    except WebSocketDisconnect:
        # Normal browser disconnect.
        pass

    except asyncio.CancelledError:
        # Normal server shutdown/reload path.
        pass

    finally:
        if queue is not None:
            with suppress(Exception):
                await maybe_await(event_bus.unsubscribe(queue))

        with suppress(Exception):
            await websocket.close(code=1000)
