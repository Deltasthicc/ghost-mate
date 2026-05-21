from __future__ import annotations

from pathlib import Path

import chess.pgn


class PgnStore:
    def __init__(self, directory: str | Path = "data/logs") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save_game(self, game: chess.pgn.Game, game_id: str) -> Path:
        path = self.directory / f"{game_id}.pgn"
        path.write_text(str(game), encoding="utf-8")
        return path
