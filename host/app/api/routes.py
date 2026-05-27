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

from host.app.ai.coach import LlmCoach, build_coach_context
from host.app.domain.events import Event, EventType

logger = logging.getLogger(__name__)
router = APIRouter()
_MAX_ENGINE_DEPTH = 30
_MAX_ENGINE_MULTIPV = 5


def _cap_engine_depth(value: int | None, fallback: int = 15) -> int:
    try:
        depth = int(value if value is not None else fallback)
    except (TypeError, ValueError):
        depth = fallback
    return max(1, min(_MAX_ENGINE_DEPTH, depth))


def _cap_engine_multipv(value: int | None, fallback: int = 5) -> int:
    try:
        multipv = int(value if value is not None else fallback)
    except (TypeError, ValueError):
        multipv = fallback
    return max(1, min(_MAX_ENGINE_MULTIPV, multipv))


def _cap_engine_search_time(value: float | None, fallback: float = 2.0) -> float:
    try:
        time_s = float(value if value is not None else fallback)
    except (TypeError, ValueError):
        time_s = fallback
    return max(0.1, min(30.0, time_s))


def _cap_engine_threads(value: int | None, fallback: int) -> int:
    try:
        threads = int(value if value is not None else fallback)
    except (TypeError, ValueError):
        threads = fallback
    return max(1, min(64, threads))


def _cap_engine_hash_mb(value: int | None, fallback: int) -> int:
    try:
        hash_mb = int(value if value is not None else fallback)
    except (TypeError, ValueError):
        hash_mb = fallback
    return max(16, min(4096, hash_mb))


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


class CoachRequest(BaseModel):
    question: str | None = None
    style: str = "student"


class EngineSettingsRequest(BaseModel):
    max_depth: int | None = None
    search_time_s: float | None = None
    multipv: int | None = None
    threads: int | None = None
    hash_mb: int | None = None


# ---------------------------------------------------------------- helpers

def _parse_pgn(pgn_text: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(StringIO(pgn_text.strip()))
    if game is None:
        raise ValueError("Could not parse PGN.")
    return game


async def _set_game_from_fen(request: Request, fen: str) -> dict:
    board = chess.Board(fen)
    game = request.app.state.game
    game.new_game(board.fen())
    snapshot = game.snapshot()
    await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    return snapshot


async def _set_game_from_pgn(request: Request, pgn_text: str) -> dict:
    parsed = _parse_pgn(pgn_text)
    game = request.app.state.game
    game.load_pgn_game(parsed)
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

async def _do_analysis(
    request: Request,
    multipv: int,
    *,
    time_s: float | None = None,
    depth: int | None = None,
    use_cache: bool = True,
) -> dict:
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
        return await engine.analysis(
            board,
            multipv=multipv,
            time_s=time_s,
            depth=depth,
            use_cache=use_cache,
        )
    except Exception as exc:
        logger.exception("Stockfish analysis failed")
        raise HTTPException(status_code=500, detail=f"Stockfish analysis failed: {exc}") from exc


@router.get("/engine/analysis")
async def engine_analysis(request: Request, multipv: int = 5) -> dict:
    return await _do_analysis(request, _cap_engine_multipv(multipv))


@router.get("/engine/live")
async def engine_live(
    request: Request,
    multipv: int = 5,
    max_depth: int | None = None,
    time_s: float | None = None,
) -> dict:
    settings = request.app.state.settings
    depth = _cap_engine_depth(max_depth, request.app.state.settings.capped_engine_live_max_depth)
    capped_multipv = _cap_engine_multipv(multipv, settings.engine_live_multipv)
    capped_time = _cap_engine_search_time(time_s, settings.engine_live_search_time_s)
    analysis = await _do_analysis(
        request,
        capped_multipv,
        time_s=capped_time,
        depth=depth,
        use_cache=False,
    )
    analysis.update({
        "max_depth": depth,
        "search_time_s": capped_time,
        "multipv_requested": capped_multipv,
        "threads": request.app.state.stockfish.threads,
        "hash_mb": request.app.state.stockfish.hash_mb,
    })
    return analysis


@router.get("/engine/settings")
async def engine_settings(request: Request) -> dict:
    settings = request.app.state.settings
    engine = request.app.state.stockfish
    return {
        "max_depth": settings.capped_engine_live_max_depth,
        "max_depth_cap": _MAX_ENGINE_DEPTH,
        "search_time_s": _cap_engine_search_time(
            settings.engine_live_search_time_s,
            settings.engine_live_search_time_s,
        ),
        "multipv": _cap_engine_multipv(settings.engine_live_multipv),
        "multipv_cap": _MAX_ENGINE_MULTIPV,
        "threads": engine.threads,
        "hash_mb": engine.hash_mb,
    }


@router.post("/engine/settings")
async def update_engine_settings(request: Request, body: EngineSettingsRequest) -> dict:
    settings = request.app.state.settings
    engine = request.app.state.stockfish

    settings.engine_live_max_depth = _cap_engine_depth(
        body.max_depth,
        settings.capped_engine_live_max_depth,
    )
    settings.engine_live_search_time_s = _cap_engine_search_time(
        body.search_time_s,
        settings.engine_live_search_time_s,
    )
    settings.engine_live_multipv = _cap_engine_multipv(
        body.multipv,
        settings.engine_live_multipv,
    )
    next_threads = _cap_engine_threads(body.threads, engine.threads)
    next_hash_mb = _cap_engine_hash_mb(body.hash_mb, engine.hash_mb)
    await engine.configure_options(threads=next_threads, hash_mb=next_hash_mb)

    return await engine_settings(request)


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


@router.post("/ai/coach")
async def ai_coach(request: Request, body: CoachRequest) -> dict:
    settings = request.app.state.settings
    board = request.app.state.game.board.copy(stack=False)
    snapshot = request.app.state.game.snapshot()
    analysis = await request.app.state.stockfish.analysis(
        board,
        multipv=settings.engine_live_multipv,
        depth=min(settings.capped_engine_live_max_depth, 8),
        use_cache=True,
    )
    context = build_coach_context(snapshot, analysis)
    coach = LlmCoach(settings)
    return await coach.explain(
        context=context,
        question=body.question,
        style=body.style,
    )


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
        return await _set_game_from_pgn(request, body.pgn)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid PGN: {exc}") from exc


@router.get("/state/pgn")
async def state_pgn(request: Request) -> dict:
    game = request.app.state.game
    return {
        "fen": game.board.fen(),
        "start_fen": game.start_fen,
        "pgn": game.pgn(),
        "ply": game.board.ply(),
    }
