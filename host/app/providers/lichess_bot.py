from __future__ import annotations

from typing import AsyncIterator

from host.app.providers.base import GameProvider, ProviderMove


class LichessBotProvider(GameProvider):
    name = "lichess_bot"

    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self._running = False

    async def start(self) -> None:
        if not self.token:
            raise RuntimeError("LICHESS_BOT_TOKEN is required for LichessBotProvider")
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def moves(self) -> AsyncIterator[ProviderMove]:
        # Implement with Lichess bot game stream when you create a bot account.
        while False:
            yield ProviderMove(uci="0000", source=self.name)
