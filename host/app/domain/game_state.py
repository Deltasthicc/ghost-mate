from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import chess


@dataclass
class GameState:
    """Authoritative in-memory game state backed by python-chess."""

    board: chess.Board = field(default_factory=chess.Board)
    game_id: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("game-%Y%m%d-%H%M%S"))
    robot_busy: bool = False
    last_error: str | None = None

    def new_game(self, fen: str | None = None) -> None:
        self.board = chess.Board(fen) if fen else chess.Board()
        self.robot_busy = False
        self.last_error = None

    def legal_uci_moves(self) -> list[str]:
        return [move.uci() for move in self.board.legal_moves]

    def push_uci(self, uci: str) -> chess.Move:
        move = chess.Move.from_uci(uci)
        if move not in self.board.legal_moves:
            raise ValueError(f"Illegal move for current position: {uci}")
        self.board.push(move)
        return move

    def push_san(self, san: str) -> chess.Move:
        move = self.board.parse_san(san)
        self.board.push(move)
        return move

    def result_if_game_over(self) -> str | None:
        if self.board.is_game_over(claim_draw=True):
            return self.board.result(claim_draw=True)
        return None

    def snapshot(self) -> dict[str, object]:
        return {
            "game_id": self.game_id,
            "fen": self.board.fen(),
            "turn": "white" if self.board.turn == chess.WHITE else "black",
            "legal_moves": self.legal_uci_moves(),
            "is_check": self.board.is_check(),
            "is_game_over": self.board.is_game_over(claim_draw=True),
            "result": self.result_if_game_over(),
            "robot_busy": self.robot_busy,
            "last_error": self.last_error,
        }
