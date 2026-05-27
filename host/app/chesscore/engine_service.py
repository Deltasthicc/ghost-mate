"""
Persistent, async Stockfish service.

This module is the single source of Stockfish access for the entire host.

Performance: the prior implementation spawned a fresh Stockfish process for
every call (best_move, analysis, snapshot evaluation). On a Raspberry Pi 4 that
is ~500 ms of pure overhead per move just for process startup and NNUE load.
This module keeps one engine alive, hot, and reused via an async lock, and
caches recent analysis by Zobrist key.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import chess
import chess.engine

logger = logging.getLogger(__name__)

_DEFAULT_ANALYSIS_TIME = 0.5
_DEFAULT_BEST_MOVE_TIME = 1.0
_DEFAULT_ANALYSIS_DEPTH: int | None = None  # rely on time by default

# How many recent positions to cache. ~5000 entries is well under 5 MB and
# saves Stockfish work on undo/redo, repeated probes, and UI re-renders.
_CACHE_LIMIT = 5000


@dataclass
class EngineMove:
    uci: str
    san: str
    score: str | None = None


def _score_cp_white(score: chess.engine.Score) -> int | None:
    if score.mate() is not None:
        return None
    return score.score()


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


def _mate_display(score: chess.engine.Score) -> str:
    mate = score.mate()
    if mate is None:
        return "—"
    if mate > 0:
        return f"White mates in {mate}"
    if mate < 0:
        return f"Black mates in {abs(mate)}"
    return "Mate now"


def _pv_to_san(board: chess.Board, pv: list[chess.Move], limit: int = 8) -> list[str]:
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


class _LRU(OrderedDict):
    """Tiny LRU cache. Not thread-safe; we only ever touch it from the event loop."""

    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit

    def get(self, key):  # type: ignore[override]
        if key in self:
            self.move_to_end(key)
            return self[key]
        return None

    def put(self, key, value) -> None:
        if key in self:
            self.move_to_end(key)
        self[key] = value
        if len(self) > self._limit:
            self.popitem(last=False)


class StockfishService:
    """
    Persistent Stockfish wrapper.

    Use as ``await service.start()`` once at app startup, then call
    :meth:`best_move`, :meth:`analysis`, or :meth:`evaluate` freely from any
    coroutine. All calls are serialized internally; the engine itself is
    never restarted for routine queries, so NNUE stays hot.
    """

    def __init__(
        self,
        stockfish_path: str = "stockfish",
        move_time_s: float = _DEFAULT_BEST_MOVE_TIME,
        threads: int | None = None,
        hash_mb: int | None = None,
        skill_level: int | None = None,
    ) -> None:
        self.stockfish_path = stockfish_path
        self.move_time_s = float(move_time_s)
        self.threads = threads or max(1, (os.cpu_count() or 2) - 1)
        self.hash_mb = hash_mb or int(os.getenv("STOCKFISH_HASH_MB", "128"))
        self.skill_level = skill_level
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._available: bool | None = None  # None = not yet probed
        self._analysis_cache: _LRU = _LRU(_CACHE_LIMIT)

    # ------------------------------------------------------------------ life

    async def start(self) -> None:
        """Lazily start the engine. Safe to call repeatedly."""
        async with self._start_lock:
            if self._engine is not None:
                return
            try:
                self._engine = await asyncio.to_thread(self._spawn)
                self._available = True
                logger.info("Stockfish ready at %s (threads=%d, hash=%dMB)",
                            self.stockfish_path, self.threads, self.hash_mb)
            except FileNotFoundError:
                self._available = False
                logger.warning("Stockfish binary not found at %r — engine features disabled.",
                               self.stockfish_path)
            except Exception as exc:
                self._available = False
                logger.warning("Stockfish failed to start: %s", exc)

    async def stop(self) -> None:
        async with self._start_lock:
            engine = self._engine
            self._engine = None
            if engine is not None:
                await asyncio.to_thread(engine.quit)

    async def configure_options(
        self,
        *,
        threads: int | None = None,
        hash_mb: int | None = None,
        skill_level: int | None = None,
    ) -> None:
        """Update runtime Stockfish options and apply them to a running engine.

        The values are clamped defensively because the dashboard exposes these
        controls directly. If Stockfish is not running yet, the new values are
        stored and used on the next lazy start.
        """
        if threads is not None:
            self.threads = max(1, min(64, int(threads)))
        if hash_mb is not None:
            self.hash_mb = max(16, min(4096, int(hash_mb)))
        if skill_level is not None:
            self.skill_level = max(0, min(20, int(skill_level)))

        engine = self._engine
        if engine is None:
            return

        options: dict[str, Any] = {
            "Threads": self.threads,
            "Hash": self.hash_mb,
        }
        if self.skill_level is not None:
            options["Skill Level"] = self.skill_level
        async with self._lock:
            try:
                await asyncio.to_thread(engine.configure, options)
            except chess.engine.EngineError as exc:
                logger.debug("Stockfish runtime configure partial: %s", exc)

    def _spawn(self) -> chess.engine.SimpleEngine:
        engine = chess.engine.SimpleEngine.popen_uci(self.stockfish_path)
        options: dict[str, Any] = {
            "Threads": self.threads,
            "Hash": self.hash_mb,
        }
        if self.skill_level is not None:
            options["Skill Level"] = max(0, min(20, int(self.skill_level)))
        try:
            engine.configure(options)
        except chess.engine.EngineError as exc:
            logger.debug("Stockfish option configure partial: %s", exc)
        return engine

    async def _ensure_engine(self) -> chess.engine.SimpleEngine | None:
        if self._engine is None and self._available is not False:
            await self.start()
        return self._engine

    async def _restart_after_error(self) -> None:
        async with self._start_lock:
            engine = self._engine
            self._engine = None
            if engine is not None:
                try:
                    await asyncio.to_thread(engine.quit)
                except Exception:
                    pass
        await self.start()

    @property
    def is_available(self) -> bool:
        return self._available is True

    # ------------------------------------------------------------------ ops

    async def best_move(self, board: chess.Board, *, time_s: float | None = None) -> EngineMove:
        engine = await self._ensure_engine()
        if engine is None:
            raise RuntimeError("Stockfish unavailable")
        limit = chess.engine.Limit(time=time_s if time_s is not None else self.move_time_s)
        board_copy = board.copy(stack=False)
        async with self._lock:
            try:
                result = await asyncio.to_thread(engine.play, board_copy, limit)
            except chess.engine.EngineError:
                await self._restart_after_error()
                engine2 = await self._ensure_engine()
                if engine2 is None:
                    raise
                result = await asyncio.to_thread(engine2.play, board_copy, limit)
        if result.move is None:
            raise RuntimeError("Stockfish did not return a move")
        san = board_copy.san(result.move)
        return EngineMove(uci=result.move.uci(), san=san)

    async def analysis(
        self,
        board: chess.Board,
        *,
        multipv: int = 5,
        time_s: float | None = None,
        depth: int | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        """Return White-POV analysis with up to ``multipv`` lines."""
        # Game-over short-circuit — never touches the engine.
        if board.is_game_over(claim_draw=True):
            result = board.result(claim_draw=True)
            return self._game_over_payload(board, result)

        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return self._game_over_payload(board, board.result(claim_draw=True))

        safe_multipv = max(1, min(int(multipv), 5, len(legal_moves)))
        cache_key = (board._transposition_key(), safe_multipv,
                     int((time_s or self.move_time_s) * 1000), depth)
        if use_cache:
            cached = self._analysis_cache.get(cache_key)
            if cached is not None:
                return {**cached, "cache_hit": True, "generated_at_ms": int(time.time() * 1000)}

        engine = await self._ensure_engine()
        if engine is None:
            return self._unavailable_payload(board)

        limit_kwargs: dict[str, Any] = {"depth": depth}
        if time_s is not None:
            limit_kwargs["time"] = max(0.01, float(time_s))
        elif depth is None:
            limit_kwargs["time"] = max(0.05, self.move_time_s)
        limit = chess.engine.Limit(**limit_kwargs)
        board_copy = board.copy(stack=False)

        started = time.perf_counter()
        async with self._lock:
            try:
                infos = await asyncio.to_thread(
                    engine.analyse, board_copy, limit, multipv=safe_multipv
                )
            except chess.engine.EngineError as exc:
                logger.warning("Stockfish analyse error, restarting: %s", exc)
                await self._restart_after_error()
                engine2 = await self._ensure_engine()
                if engine2 is None:
                    return self._unavailable_payload(board)
                infos = await asyncio.to_thread(
                    engine2.analyse, board_copy, limit, multipv=safe_multipv
                )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        payload = self._build_payload(board_copy, infos)
        payload["cache_hit"] = False
        payload["analysis_time_s"] = time_s if time_s is not None else None
        payload["depth_requested"] = depth
        payload["elapsed_ms"] = elapsed_ms
        payload["generated_at_ms"] = int(time.time() * 1000)
        if use_cache:
            self._analysis_cache.put(cache_key, payload)
        return payload

    async def evaluate(self, board: chess.Board, *, time_s: float = 0.12) -> dict[str, Any]:
        """Quick single-line evaluation. Cached aggressively for UI snapshots."""
        if board.is_checkmate():
            mate_sign = -1 if board.turn == chess.WHITE else 1
            return {
                "display": "#+0" if mate_sign > 0 else "#-0",
                "score_cp": None,
                "score_pawns": None,
                "mate_in": 0,
                "source": "checkmate",
                "note": "Game is already checkmate.",
            }
        try:
            payload = await self.analysis(board, multipv=1, time_s=time_s, use_cache=False)
        except Exception as exc:
            logger.debug("evaluate failed, falling back to material: %s", exc)
            return _material_only_evaluation(board)

        if not payload.get("best_moves"):
            return _material_only_evaluation(board)

        return {
            "display": payload.get("current_display", "--"),
            "score_cp": payload.get("current_score_cp"),
            "score_pawns": (None if payload.get("current_score_cp") is None
                            else round(payload["current_score_cp"] / 100, 2)),
            "mate_in": payload.get("mate_in"),
            "source": "stockfish",
            "note": "White POV: positive means White is better, negative means Black is better.",
        }

    # ------------------------------------------------------------------ helpers

    def _build_payload(
        self,
        board: chess.Board,
        infos: dict[str, Any] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        info_list = [infos] if isinstance(infos, dict) else list(infos)
        best_moves: list[dict[str, Any]] = []
        top_depth: int | None = None
        current_white_score: chess.engine.Score | None = None

        for rank, info in enumerate(info_list, start=1):
            score_obj = info.get("score")
            pv = info.get("pv") or []
            if not score_obj or not pv:
                continue

            move = pv[0]
            if move not in board.legal_moves:
                continue

            white_score = score_obj.pov(chess.WHITE)
            depth = info.get("depth")
            if isinstance(depth, int) and (top_depth is None or depth > top_depth):
                top_depth = depth
            if current_white_score is None:
                current_white_score = white_score

            display = _score_display(white_score)
            score_cp = _score_cp_white(white_score)
            best_moves.append({
                "rank": rank,
                "uci": move.uci(),
                "san": board.san(move),
                "score_cp": score_cp,
                "score_display": display,
                "score_cp_white": score_cp,
                "score_display_white": display,
                "score_cp_turn": score_cp,
                "score_display_turn": display,
                "mate_in": white_score.mate(),
                "mate_display": _mate_display(white_score),
                "pv": _pv_to_san(board, list(pv)),
            })

        if current_white_score is None:
            return self._unavailable_payload(board)

        display = _score_display(current_white_score)
        cp = _score_cp_white(current_white_score)
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "score_view": "white",
            "depth": top_depth,
            "current_display": display,
            "current_score_cp": cp,
            "current_display_white": display,
            "current_score_cp_white": cp,
            "current_display_turn": display,
            "current_score_cp_turn": cp,
            "mate_in": current_white_score.mate(),
            "mate_display": _mate_display(current_white_score),
            "best_moves": best_moves,
            "note": (
                "All scores are White-centric: positive means White is better, "
                "negative means Black is better."
            ),
        }

    @staticmethod
    def _game_over_payload(board: chess.Board, result: str) -> dict[str, Any]:
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "score_view": "white",
            "depth": None,
            "current_display": result,
            "current_display_white": result,
            "current_display_turn": result,
            "current_score_cp": None,
            "current_score_cp_white": None,
            "current_score_cp_turn": None,
            "mate_in": None,
            "mate_display": result,
            "best_moves": [],
            "note": f"Game is over: {result}",
        }

    @staticmethod
    def _unavailable_payload(board: chess.Board) -> dict[str, Any]:
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "score_view": "white",
            "depth": None,
            "current_display": "--",
            "current_display_white": "--",
            "current_display_turn": "--",
            "current_score_cp": None,
            "current_score_cp_white": None,
            "current_score_cp_turn": None,
            "mate_in": None,
            "mate_display": "—",
            "best_moves": [],
            "note": "Stockfish unavailable.",
        }


# ---------------------------------------------------------------------- fallback

_PIECE_VALUES_CP: dict[chess.PieceType, int] = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0,
}


def _material_only_evaluation(board: chess.Board) -> dict[str, Any]:
    score = 0
    for _, piece in board.piece_map().items():
        v = _PIECE_VALUES_CP[piece.piece_type]
        score += v if piece.color == chess.WHITE else -v
    pawns = score / 100
    display = "0.00" if abs(pawns) < 0.005 else f"{pawns:+.2f}"
    return {
        "display": display,
        "score_cp": score,
        "score_pawns": round(pawns, 2),
        "mate_in": None,
        "source": "material",
        "note": "Material-only fallback. Configure STOCKFISH_PATH for true evaluation.",
    }
