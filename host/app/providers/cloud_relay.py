from __future__ import annotations

import asyncio
from typing import AsyncIterator

from host.app.providers.base import GameProvider, ProviderMove


class CloudRelayProvider(GameProvider):
    name = "cloud_relay"

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ProviderMove] = asyncio.Queue()
        self._running = False

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def push_remote_move(self, uci: str, raw: dict | None = None) -> None:
        await self._queue.put(ProviderMove(uci=uci, source=self.name, raw=raw))

    async def moves(self) -> AsyncIterator[ProviderMove]:
        while self._running:
            yield await self._queue.get()
