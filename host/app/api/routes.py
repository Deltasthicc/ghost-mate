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
        turn_score = score_obj.pov(chess.WHITE)

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
            "All scores are White-centric: positive means White is better, negative means Black is better."
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


# === GM_DYNAMIC_STOCKFISH_V3_BACKEND START ===
# Extra analysis/position endpoints. These are intentionally additive so existing
# routes/tests remain intact.

import asyncio as _gm_asyncio
from io import StringIO as _gm_StringIO

import chess as _gm_chess
import chess.engine as _gm_chess_engine
import chess.pgn as _gm_chess_pgn
import time as _gm_time
import threading as _gm_threading
from pydantic import BaseModel as _GMBaseModel


class _GMFenRequest(_GMBaseModel):
    fen: str


class _GMPgnRequest(_GMBaseModel):
    pgn: str


# === GM_FAST_STOCKFISH_OPTIMIZATION START ===
_GM_ENGINE_LOCK = _gm_threading.Lock()
_GM_ENGINE = None
_GM_ENGINE_PATH = None
_GM_ANALYSIS_CACHE = {}
_GM_CACHE_TTL_S = 0.9

def _gm_analyse_with_persistent_engine(board, stockfish_path, limit, safe_multipv):
    global _GM_ENGINE, _GM_ENGINE_PATH

    with _GM_ENGINE_LOCK:
        if _GM_ENGINE is None or _GM_ENGINE_PATH != stockfish_path:
            if _GM_ENGINE is not None:
                try:
                    _GM_ENGINE.quit()
                except Exception:
                    pass

            _GM_ENGINE = _gm_chess_engine.SimpleEngine.popen_uci(stockfish_path)
            _GM_ENGINE_PATH = stockfish_path

            try:
                _GM_ENGINE.configure({"Threads": 2, "Hash": 64})
            except Exception:
                pass

        return _GM_ENGINE.analyse(board, limit, multipv=safe_multipv)
# === GM_FAST_STOCKFISH_OPTIMIZATION END ===


def _gm_score_cp_white(score: _gm_chess_engine.Score) -> int | None:
    if score.mate() is not None:
        return None
    return score.score()


def _gm_score_display_white(score: _gm_chess_engine.Score) -> str:
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


def _gm_mate_display_white(score: _gm_chess_engine.Score) -> str:
    mate = score.mate()
    if mate is None:
        return "—"
    if mate > 0:
        return f"White mates in {mate}"
    if mate < 0:
        return f"Black mates in {abs(mate)}"
    return "Mate now"


def _gm_pv_to_san(board: _gm_chess.Board, pv: list[_gm_chess.Move], limit: int = 8) -> list[str]:
    copy = board.copy(stack=False)
    readable: list[str] = []

    for move in pv[:limit]:
        try:
            if move in copy.legal_moves:
                readable.append(copy.san(move))
                copy.push(move)
            else:
                readable.append(move.uci())
                break
        except Exception:
            readable.append(move.uci())
            break

    return readable


def _gm_stockfish_live_sync(
    board: _gm_chess.Board,
    stockfish_path: str,
    move_time_s: float,
    multipv: int,
) -> dict:
    if board.is_game_over(claim_draw=True):
        result = board.result(claim_draw=True)
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == _gm_chess.WHITE else "black",
            "score_view": "white",
            "depth": None,
            "current_display": result,
            "current_display_white": result,
            "current_score_cp": None,
            "current_score_cp_white": None,
            "mate_in": None,
            "mate_display": result,
            "best_moves": [],
            "note": "Game is over.",
        }

    legal_moves = list(board.legal_moves)
    safe_multipv = max(1, min(int(multipv), 5, len(legal_moves)))
    limit = _gm_chess_engine.Limit(time=max(0.05, float(move_time_s)))

    infos = _gm_analyse_with_persistent_engine(board, stockfish_path, limit, safe_multipv)

    info_list = [infos] if isinstance(infos, dict) else list(infos)

    best_moves = []
    top_depth = None
    current_white_score = None

    for rank, info in enumerate(info_list, start=1):
        score_obj = info.get("score")
        pv = info.get("pv") or []
        if not score_obj or not pv:
            continue

        move = pv[0]
        if move not in board.legal_moves:
            continue

        white_score = score_obj.pov(_gm_chess.WHITE)

        depth = info.get("depth")
        if isinstance(depth, int) and (top_depth is None or depth > top_depth):
            top_depth = depth

        if current_white_score is None:
            current_white_score = white_score

        display = _gm_score_display_white(white_score)

        best_moves.append(
            {
                "rank": rank,
                "uci": move.uci(),
                "san": board.san(move),

                # Canonical White-POV fields.
                "score_cp": _gm_score_cp_white(white_score),
                "score_display": display,

                # Explicit White-POV fields.
                "score_cp_white": _gm_score_cp_white(white_score),
                "score_display_white": display,

                # Legacy aliases kept White-POV to avoid side-to-move sign confusion.
                "score_cp_turn": _gm_score_cp_white(white_score),
                "score_display_turn": display,

                "mate_in": white_score.mate(),
                "mate_display": _gm_mate_display_white(white_score),
                "pv": _gm_pv_to_san(board, list(pv)),
            }
        )

    if current_white_score is None:
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == _gm_chess.WHITE else "black",
            "score_view": "white",
            "depth": top_depth,
            "current_display": "--",
            "current_display_white": "--",
            "current_score_cp": None,
            "current_score_cp_white": None,
            "mate_in": None,
            "mate_display": "—",
            "best_moves": [],
            "note": "Stockfish returned no usable legal move.",
        }

    display = _gm_score_display_white(current_white_score)

    return {
        "fen": board.fen(),
        "turn": "white" if board.turn == _gm_chess.WHITE else "black",
        "score_view": "white",
        "depth": top_depth,

        # Canonical fields.
        "current_display": display,
        "current_score_cp": _gm_score_cp_white(current_white_score),

        # Explicit White-POV fields.
        "current_display_white": display,
        "current_score_cp_white": _gm_score_cp_white(current_white_score),

        # Legacy aliases kept White-POV.
        "current_display_turn": display,
        "current_score_cp_turn": _gm_score_cp_white(current_white_score),

        "mate_in": current_white_score.mate(),
        "mate_display": _gm_mate_display_white(current_white_score),
        "best_moves": best_moves,
        "note": (
            "All scores are White-centric: positive means White is better, "
            "negative means Black is better. Move ranking is Stockfish MultiPV "
            "for the side to move."
        ),
    }


async def _gm_set_game_board_from_fen(request: Request, fen: str) -> dict:
    board = _gm_chess.Board(fen)

    game = request.app.state.game

    try:
        game.new_game(board.fen())
    except TypeError:
        # Fallback for older GameState implementations.
        game.new_game()
        game.board = board

    snapshot = game.snapshot()

    try:
        await request.app.state.events.publish(Event(EventType.STATE_CHANGED, snapshot))
    except Exception:
        pass

    return snapshot


def _gm_final_board_from_pgn(pgn_text: str) -> _gm_chess.Board:
    game = _gm_chess_pgn.read_game(_gm_StringIO(pgn_text.strip()))
    if game is None:
        raise ValueError("Could not parse PGN. Paste a valid PGN game.")

    board = game.board()
    for move in game.mainline_moves():
        board.push(move)

    return board


@router.get("/engine/live")
async def gm_engine_live(request: Request, multipv: int = 5) -> dict:
    settings = request.app.state.settings
    board = request.app.state.game.board.copy(stack=False)

    cache_key = (
        board.fen(),
        settings.stockfish_path,
        int(max(1, min(int(multipv), 5))),
        round(float(settings.engine_move_time_s), 3),
    )

    now = _gm_time.monotonic()
    cached = _GM_ANALYSIS_CACHE.get(cache_key)
    if cached and now - cached[0] < _GM_CACHE_TTL_S:
        return cached[1]

    try:
        result = await _gm_asyncio.to_thread(
            _gm_stockfish_live_sync,
            board,
            settings.stockfish_path,
            settings.engine_move_time_s,
            multipv,
        )
        _GM_ANALYSIS_CACHE.clear()
        _GM_ANALYSIS_CACHE[cache_key] = (_gm_time.monotonic(), result)
        return result
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Stockfish executable not found at {settings.stockfish_path!r}. Set STOCKFISH_PATH in .env.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stockfish live analysis failed: {exc}") from exc


@router.post("/position/fen")
async def gm_load_fen(request: Request, body: _GMFenRequest) -> dict:
    try:
        return await _gm_set_game_board_from_fen(request, body.fen.strip())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid FEN: {exc}") from exc


@router.post("/position/pgn")
async def gm_load_pgn(request: Request, body: _GMPgnRequest) -> dict:
    try:
        board = _gm_final_board_from_pgn(body.pgn)
        return await _gm_set_game_board_from_fen(request, board.fen())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid PGN: {exc}") from exc

# === GM_DYNAMIC_STOCKFISH_V3_BACKEND END ===
