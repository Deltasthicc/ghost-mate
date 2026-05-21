from __future__ import annotations

import asyncio
from dataclasses import dataclass

import chess
import chess.engine


@dataclass
class EngineMove:
    uci: str
    san: str
    score: str | None = None


class StockfishService:
    def __init__(self, stockfish_path: str = "stockfish", move_time_s: float = 1.0) -> None:
        self.stockfish_path = stockfish_path
        self.move_time_s = move_time_s

    async def best_move(self, board: chess.Board) -> EngineMove:
        # python-chess engine APIs are blocking, so run them in a thread.
        return await asyncio.to_thread(self._best_move_sync, board.copy())

    def _best_move_sync(self, board: chess.Board) -> EngineMove:
        with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
            result = engine.play(board, chess.engine.Limit(time=self.move_time_s))
            if result.move is None:
                raise RuntimeError("Stockfish did not return a move")
            san = board.san(result.move)
            return EngineMove(uci=result.move.uci(), san=san)
