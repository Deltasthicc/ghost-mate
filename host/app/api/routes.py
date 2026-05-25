"""HTTP API.

Designed to be cheap: the heavy lift (Stockfish) lives in StockfishService and
is reused across requests. The /api/engine/analysis and /api/engine/live
endpoints are kept as aliases so older clients keep working.
"""
from __future__ import annotations

import logging
from io import StringIO

import chess
import chess.pgn
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from host.app.domain.events import Event, EventType

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------- request bodies

class MoveRequest(BaseModel):
    uci: str


class RobotMoveRequest(BaseModel):
    source: str
    target: str
    capture: bool = False
    victim: str | None = None


class FenRequest(BaseModel):
    fen: str


class PgnRequest(BaseModel):
    pgn: str


# ---------------------------------------------------------------- helpers

def _final_board_from_pgn(pgn_text: str) -> chess.Board:
    game = chess.pgn.read_game(StringIO(pgn_text.strip()))
    if game is None:
        raise ValueError("Could not parse PGN.")
    board = game.board()
    for move in game.mainline_moves():
        board.push(move)
    return board


async def _set_game_from_fen(request: Request, fen: str) -> dict:
    board = chess.Board(fen)
    game = request.app.state.game
    game.new_game(board.fen())
    snapshot = game.snapshot()
    await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    return snapshot


# ---------------------------------------------------------------- endpoints

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/state")
async def state(request: Request) -> dict:
    return request.app.state.game.snapshot()


@router.post("/game/new")
async def new_game(request: Request, fen: str | None = None) -> dict:
    request.app.state.game.new_game(fen)
    snapshot = request.app.state.game.snapshot()
    await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    return snapshot


@router.post("/move/human")
async def human_move(request: Request, body: MoveRequest) -> dict:
    game = request.app.state.game
    try:
        move = game.push_uci(body.uci)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    snapshot = game.snapshot()
    # Push the new authoritative state alongside the candidate event so the WS
    # client doesn't have to round-trip a GET /api/state afterwards.
    await request.app.state.events.publish(Event(
        EventType.LOCAL_MOVE_CANDIDATE,
        {"uci": move.uci(), "fen": game.board.fen(), "state": snapshot},
    ))
    return snapshot


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


# ---------------------------------------------------------------- engine

async def _do_analysis(request: Request, multipv: int) -> dict:
    settings = request.app.state.settings
    engine = request.app.state.stockfish
    board = request.app.state.game.board.copy(stack=False)

    # Correct lazy-start behavior:
    # app startup stays fast and tests don't spawn Stockfish repeatedly,
    # but the first real engine request starts the persistent Stockfish process.
    if not engine.is_available:
        await engine.start()

    if not engine.is_available:
        raise HTTPException(
            status_code=503,
            detail=f"Stockfish not available at {settings.stockfish_path!r}. "
                   "Set STOCKFISH_PATH and ensure the binary is installed.",
        )

    try:
        return await engine.analysis(board, multipv=multipv)
    except Exception as exc:
        logger.exception("Stockfish analysis failed")
        raise HTTPException(status_code=500, detail=f"Stockfish analysis failed: {exc}") from exc


@router.get("/engine/analysis")
async def engine_analysis(request: Request, multipv: int = 5) -> dict:
    return await _do_analysis(request, multipv)


@router.get("/engine/live")
async def engine_live(request: Request, multipv: int = 5) -> dict:
    return await _do_analysis(request, multipv)


@router.post("/engine/bestmove")
async def engine_bestmove(request: Request, time_s: float | None = None) -> dict:
    engine = request.app.state.stockfish

    if not engine.is_available:
        await engine.start()

    if not engine.is_available:
        raise HTTPException(status_code=503, detail="Stockfish unavailable")

    board = request.app.state.game.board.copy(stack=False)
    try:
        move = await engine.best_move(board, time_s=time_s)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"uci": move.uci, "san": move.san}


# ---------------------------------------------------------------- position load

@router.post("/position/fen")
async def load_fen(request: Request, body: FenRequest) -> dict:
    try:
        return await _set_game_from_fen(request, body.fen.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc


@router.post("/position/pgn")
async def load_pgn(request: Request, body: PgnRequest) -> dict:
    try:
        board = _final_board_from_pgn(body.pgn)
        return await _set_game_from_fen(request, board.fen())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid PGN: {exc}") from exc
