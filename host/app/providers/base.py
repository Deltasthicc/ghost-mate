from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass(frozen=True)
class ProviderMove:
    uci: str
    source: str
    raw: dict | None = None


class GameProvider(ABC):
    name: str

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def moves(self) -> AsyncIterator[ProviderMove]: ...

    async def submit_local_move(self, uci: str) -> None:
        _ = uci
