"""
Authoritative in-memory game state, backed by python-chess.

Snapshot is now cheap: no Stockfish spawn, no synchronous engine probes.
Use the StockfishService directly for evaluation when needed (see
api/routes.py:/engine/live). This keeps WebSocket broadcasts and state polls
fast even on a Raspberry Pi 4.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import chess


PIECE_VALUES_CP: dict[chess.PieceType, int] = {
    chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
    chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0,
}


def make_game_id() -> str:
    """Unique, human-readable game id with collision-resistant UUID suffix."""
    timestamp = datetime.now(timezone.utc).strftime("game-%Y%m%d-%H%M%S-%f")
    return f"{timestamp}-{uuid4().hex[:8]}"


def _material_cp(board: chess.Board) -> int:
    score = 0
    for _, piece in board.piece_map().items():
        v = PIECE_VALUES_CP[piece.piece_type]
        score += v if piece.color == chess.WHITE else -v
    return score


def _format_cp(cp: int) -> str:
    pawns = cp / 100
    return "0.00" if abs(pawns) < 0.005 else f"{pawns:+.2f}"


def evaluate_position(board: chess.Board) -> dict[str, Any]:
    """Cheap material-only evaluation. Stockfish evaluation lives in StockfishService."""
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
    cp = _material_cp(board)
    return {
        "display": _format_cp(cp),
        "score_cp": cp,
        "score_pawns": round(cp / 100, 2),
        "mate_in": None,
        "source": "material",
        "note": "Material-only fallback. Live Stockfish eval is at /api/engine/live.",
    }


@dataclass
class GameState:
    """In-memory game state. Snapshot is allocation-light and engine-free."""

    board: chess.Board = field(default_factory=chess.Board)
    game_id: str = field(default_factory=make_game_id)
    robot_busy: bool = False
    last_error: str | None = None

    # Cached snapshot — invalidated whenever the position changes.
    _snapshot_cache: dict[str, Any] | None = field(default=None, repr=False)
    _snapshot_key: tuple | None = field(default=None, repr=False)

    def _invalidate(self) -> None:
        self._snapshot_cache = None
        self._snapshot_key = None

    def new_game(self, fen: str | None = None) -> None:
        self.board = chess.Board(fen) if fen else chess.Board()
        self.game_id = make_game_id()
        self.robot_busy = False
        self.last_error = None
        self._invalidate()

    def legal_uci_moves(self) -> list[str]:
        return [move.uci() for move in self.board.legal_moves]

    def push_uci(self, uci: str) -> chess.Move:
        clean_uci = uci.strip().lower()
        move = chess.Move.from_uci(clean_uci)
        if move not in self.board.legal_moves:
            raise ValueError(f"Illegal move for current position: {clean_uci}")
        self.board.push(move)
        self._invalidate()
        return move

    def push_san(self, san: str) -> chess.Move:
        move = self.board.parse_san(san.strip())
        self.board.push(move)
        self._invalidate()
        return move

    def result_if_game_over(self) -> str | None:
        if self.board.is_game_over(claim_draw=True):
            return self.board.result(claim_draw=True)
        return None

    def snapshot(self) -> dict[str, Any]:
        """Cheap, cached snapshot. No subprocess spawning."""
        # Cache key combines transient flags and the position itself.
        try:
            position_key = self.board._transposition_key()
        except Exception:
            position_key = self.board.fen()

        key = (position_key, self.robot_busy, self.last_error, self.game_id)
        if self._snapshot_key == key and self._snapshot_cache is not None:
            return self._snapshot_cache

        board = self.board
        is_over = board.is_game_over(claim_draw=True)
        snapshot = {
            "game_id": self.game_id,
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "legal_moves": [m.uci() for m in board.legal_moves],
            "is_check": board.is_check(),
            "is_game_over": is_over,
            "result": board.result(claim_draw=True) if is_over else None,
            "robot_busy": self.robot_busy,
            "last_error": self.last_error,
            "evaluation": evaluate_position(board),
            "ply": board.ply(),
            "halfmove_clock": board.halfmove_clock,
            "fullmove_number": board.fullmove_number,
        }
        self._snapshot_cache = snapshot
        self._snapshot_key = key
        return snapshot
