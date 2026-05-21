from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from host.app.domain.events import Event, EventType

router = APIRouter()


class MoveRequest(BaseModel):
    uci: str


class RobotMoveRequest(BaseModel):
    source: str
    target: str
    capture: bool = False
    victim: str | None = None


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/state")
async def state(request: Request) -> dict:
    return request.app.state.game.snapshot()


@router.post("/game/new")
async def new_game(request: Request, fen: str | None = None) -> dict:
    request.app.state.game.new_game(fen)
    await request.app.state.events.publish(Event(EventType.STATE_CHANGED, request.app.state.game.snapshot()))
    return request.app.state.game.snapshot()


@router.post("/move/human")
async def human_move(request: Request, body: MoveRequest) -> dict:
    try:
        move = request.app.state.game.push_uci(body.uci)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await request.app.state.events.publish(
        Event(EventType.LOCAL_MOVE_CANDIDATE, {"uci": move.uci(), "fen": request.app.state.game.board.fen()})
    )
    return request.app.state.game.snapshot()


@router.post("/move/robot")
async def robot_move(request: Request, body: RobotMoveRequest) -> dict:
    motion = request.app.state.motion
    if body.capture and body.victim:
        reply = await motion.capture_move(body.victim, body.source, body.target)
    else:
        reply = await motion.move_square_to_square(body.source, body.target, body.capture)
    if not reply.ok:
        raise HTTPException(status_code=500, detail=reply.err or "motion failed")
    return {"ok": True, "reply": reply.raw}


@router.post("/hardware/home")
async def hardware_home(request: Request) -> dict:
    reply = await request.app.state.motion.home()
    request.app.state.safety.homed = reply.ok
    return {"ok": reply.ok, "err": reply.err}


@router.post("/hardware/park")
async def hardware_park(request: Request) -> dict:
    reply = await request.app.state.motion.park()
    return {"ok": reply.ok, "err": reply.err}


@router.post("/hardware/scan")
async def hardware_scan(request: Request, full: bool = True) -> dict:
    reply = await request.app.state.motion.scan(full=full)
    return {"ok": reply.ok, "err": reply.err}


@router.get("/board/snapshot")
async def board_snapshot(request: Request) -> dict:
    return request.app.state.board_sensor.latest.to_payload()
