from __future__ import annotations

from typing import AsyncIterator

from host.app.providers.base import GameProvider, ProviderMove


class LichessBoardProvider(GameProvider):
    """
    Skeleton for Lichess Board API.

    Note: normal Lichess Board API is for human play. Engine-assisted play belongs in bot mode.
    Wire this after creating a token and choosing whether the account is human-board or bot.
    """

    name = "lichess_board"

    def __init__(self, token: str | None = None) -> None:
        self.token = token
        self._running = False

    async def start(self) -> None:
        if not self.token:
            raise RuntimeError("LICHESS_TOKEN is required for LichessBoardProvider")
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def moves(self) -> AsyncIterator[ProviderMove]:
        # Implement using berserk.TokenSession + board stream endpoints.
        while False:
            yield ProviderMove(uci="0000", source=self.name)
