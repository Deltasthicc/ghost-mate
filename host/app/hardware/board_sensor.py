from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass(frozen=True)
class CellState:
    occupied: bool
    polarity: int = 0
    magnitude: int = 0

    @classmethod
    def from_protocol(cls, payload: dict[str, Any]) -> "CellState":
        return cls(
            occupied=bool(payload.get("o", payload.get("occ", 0))),
            polarity=int(payload.get("p", payload.get("sign", 0))),
            magnitude=int(payload.get("m", payload.get("mag", 0))),
        )

    def to_protocol(self) -> dict[str, int]:
        return {"o": int(self.occupied), "p": self.polarity, "m": self.magnitude}


@dataclass
class BoardSnapshot:
    cells: dict[str, CellState] = field(default_factory=dict)
    ts_ms: int = field(default_factory=lambda: int(time() * 1000))

    @classmethod
    def empty(cls) -> "BoardSnapshot":
        files = "abcdefgh"
        ranks = "12345678"
        return cls(cells={f"{f}{r}": CellState(False, 0, 0) for r in ranks for f in files})

    @classmethod
    def from_scan_event(cls, event: dict[str, Any], previous: "BoardSnapshot | None" = None) -> "BoardSnapshot":
        base = dict(previous.cells) if previous else cls.empty().cells
        raw_cells = event.get("cells") or event.get("squares") or {}
        for square, cell in raw_cells.items():
            base[square] = CellState.from_protocol(cell)
        return cls(cells=base, ts_ms=int(event.get("ts_ms", int(time() * 1000))))

    def occupied_squares(self) -> set[str]:
        return {square for square, cell in self.cells.items() if cell.occupied}

    def diff(self, other: "BoardSnapshot") -> dict[str, tuple[CellState | None, CellState | None]]:
        squares = set(self.cells) | set(other.cells)
        changes: dict[str, tuple[CellState | None, CellState | None]] = {}
        for square in squares:
            a = self.cells.get(square)
            b = other.cells.get(square)
            if a != b:
                changes[square] = (a, b)
        return changes

    def to_payload(self) -> dict[str, Any]:
        return {
            "ts_ms": self.ts_ms,
            "cells": {square: cell.to_protocol() for square, cell in self.cells.items()},
        }


class BoardSensorService:
    def __init__(self) -> None:
        self.latest = BoardSnapshot.empty()

    def update_from_event(self, event: dict[str, Any]) -> BoardSnapshot:
        self.latest = BoardSnapshot.from_scan_event(event, previous=self.latest)
        return self.latest
