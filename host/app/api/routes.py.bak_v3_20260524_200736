from __future__ import annotations

import asyncio
from fastapi import APIRouter, HTTPException, Request
import chess
import chess.engine
from pydantic import BaseModel

from host.app.domain.events import Event, EventType

router = APIRouter()


def _score_display(score: chess.engine.Score) -> str:
    mate = score.mate()
    if mate is not None:
        if mate > 0:
            return f"M{mate}"
        if mate < 0:
            return f"-M{abs(mate)}"
        return "M0"

    cp = score.score()
    if cp is None:
        return "--"
    return f"{cp / 100:+.2f}"


def _score_cp(score: chess.engine.Score) -> int | None:
    if score.mate() is not None:
        return None
    return score.score()


def _pv_to_san(board: chess.Board, pv: list[chess.Move], limit: int = 6) -> list[str]:
    copy = board.copy(stack=False)
    readable: list[str] = []

    for move in pv[:limit]:
        try:
            if move in copy.legal_moves:
                readable.append(copy.san(move))
                copy.push(move)
            else:
                readable.append(move.uci())
        except Exception:
            readable.append(move.uci())
            break

    return readable


def _stockfish_analysis_sync(
    board: chess.Board,
    stockfish_path: str,
    move_time_s: float,
    multipv: int,
) -> dict:
    if board.is_game_over(claim_draw=True):
        result = board.result(claim_draw=True)
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "depth": None,
            "current_display_white": result,
            "current_display_turn": result,
            "current_score_cp_white": None,
            "current_score_cp_turn": None,
            "mate_in": None,
            "best_moves": [],
            "note": f"Game is over: {result}",
        }

    legal_moves = list(board.legal_moves)
    safe_multipv = max(1, min(int(multipv), 5, len(legal_moves)))
    limit = chess.engine.Limit(time=move_time_s)

    with chess.engine.SimpleEngine.popen_uci(stockfish_path) as engine:
        infos = engine.analyse(board, limit, multipv=safe_multipv)

    if isinstance(infos, dict):
        info_list = [infos]
    else:
        info_list = list(infos)

    best_moves = []
    top_depth = None
    current_white_score = None
    current_turn_score = None

    for index, info in enumerate(info_list, start=1):
        score_obj = info.get("score")
        pv = info.get("pv") or []

        if not score_obj or not pv:
            continue

        move = pv[0]

        if move not in board.legal_moves:
            continue

        white_score = score_obj.pov(chess.WHITE)
        turn_score = score_obj.pov(board.turn)

        depth = info.get("depth")
        if isinstance(depth, int) and (top_depth is None or depth > top_depth):
            top_depth = depth

        if current_white_score is None:
            current_white_score = white_score
            current_turn_score = turn_score

        best_moves.append(
            {
                "rank": index,
                "uci": move.uci(),
                "san": board.san(move),
                "score_cp_white": _score_cp(white_score),
                "score_cp_turn": _score_cp(turn_score),
                "score_display_white": _score_display(white_score),
                "score_display_turn": _score_display(turn_score),
                "mate_in": turn_score.mate(),
                "pv": _pv_to_san(board, list(pv)),
            }
        )

    if current_white_score is None or current_turn_score is None:
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "depth": top_depth,
            "current_display_white": "--",
            "current_display_turn": "--",
            "current_score_cp_white": None,
            "current_score_cp_turn": None,
            "mate_in": None,
            "best_moves": [],
            "note": "Stockfish returned no usable legal move.",
        }

    return {
        "fen": board.fen(),
        "turn": "white" if board.turn == chess.WHITE else "black",
        "depth": top_depth,
        "current_display_white": _score_display(current_white_score),
        "current_display_turn": _score_display(current_turn_score),
        "current_score_cp_white": _score_cp(current_white_score),
        "current_score_cp_turn": _score_cp(current_turn_score),
        "mate_in": current_turn_score.mate(),
        "best_moves": best_moves,
        "note": (
            "White score is from White's point of view. "
            "Turn score is from the player-to-move's point of view."
        ),
    }


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


@router.get("/engine/analysis")
async def engine_analysis(request: Request, multipv: int = 5) -> dict:
    settings = request.app.state.settings
    board = request.app.state.game.board.copy(stack=False)

    try:
        return await asyncio.to_thread(
            _stockfish_analysis_sync,
            board,
            settings.stockfish_path,
            settings.engine_move_time_s,
            multipv,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Stockfish executable not found at {settings.stockfish_path!r}. Set STOCKFISH_PATH in .env.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stockfish analysis failed: {exc}") from exc
