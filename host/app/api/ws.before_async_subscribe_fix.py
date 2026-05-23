from __future__ import annotations

import asyncio
from contextlib import suppress

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()

    event_bus = websocket.app.state.events
    game = websocket.app.state.game
    queue = event_bus.subscribe()

    try:
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
        # Normal client disconnect
        pass

    except asyncio.CancelledError:
        # Normal shutdown path during server stop / reload
        pass

    finally:
        with suppress(Exception):
            event_bus.unsubscribe(queue)

        with suppress(Exception):
            await websocket.close(code=1000)
