from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def websocket_events(websocket: WebSocket) -> None:
    await websocket.accept()
    app = websocket.app
    queue = await app.state.events.subscribe()
    try:
        await websocket.send_json({"type": "HELLO", "state": app.state.game.snapshot()})
        while True:
            event = await queue.get()
            await websocket.send_json(
                {
                    "type": event.type.value,
                    "created_at": event.created_at.isoformat(),
                    "payload": event.payload,
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        await app.state.events.unsubscribe(queue)
