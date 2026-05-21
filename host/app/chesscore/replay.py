from __future__ import annotations

from pathlib import Path

import chess.pgn


class PgnReplay:
    def load_moves(self, path: str | Path) -> list[str]:
        with Path(path).open("r", encoding="utf-8") as fh:
            game = chess.pgn.read_game(fh)
        if game is None:
            return []
        board = game.board()
        moves: list[str] = []
        for move in game.mainline_moves():
            moves.append(move.uci())
            board.push(move)
        return moves
