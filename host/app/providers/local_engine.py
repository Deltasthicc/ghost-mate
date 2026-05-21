from __future__ import annotations

import asyncio
from typing import AsyncIterator

import chess

from host.app.chesscore.engine_service import StockfishService
from host.app.providers.base import GameProvider, ProviderMove


class LocalEngineProvider(GameProvider):
    name = "local_engine"

    def __init__(self, engine: StockfishService, board: chess.Board) -> None:
        self.engine = engine
        self.board = board
        self._queue: asyncio.Queue[ProviderMove] = asyncio.Queue()
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def submit_local_move(self, uci: str) -> None:
        move = chess.Move.from_uci(uci)
        if move not in self.board.legal_moves:
            raise ValueError(f"Illegal local move: {uci}")
        self.board.push(move)
        if not self.board.is_game_over():
            engine_move = await self.engine.best_move(self.board)
            self.board.push(chess.Move.from_uci(engine_move.uci))
            await self._queue.put(ProviderMove(uci=engine_move.uci, source=self.name))

    async def moves(self) -> AsyncIterator[ProviderMove]:
        while self._running:
            yield await self._queue.get()
