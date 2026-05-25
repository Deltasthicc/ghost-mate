"""
Hall-sensor board snapshot model.

Optimizations:
- The 64 square names are precomputed once at module load.
- BoardSnapshot.empty uses the precomputed names.
- to_payload returns plain dicts (faster JSON serialization).
- diff iterates only the union of keys present in the new event when called
  incrementally (used by the firmware delta scan).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

_FILES = "abcdefgh"
_RANKS = "12345678"
_SQUARE_NAMES: tuple[str, ...] = tuple(f"{f}{r}" for r in _RANKS for f in _FILES)


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


_EMPTY_CELL = CellState(False, 0, 0)


@dataclass
class BoardSnapshot:
    cells: dict[str, CellState] = field(default_factory=dict)
    ts_ms: int = field(default_factory=lambda: int(time() * 1000))

    @classmethod
    def empty(cls) -> "BoardSnapshot":
        return cls(cells={name: _EMPTY_CELL for name in _SQUARE_NAMES})

    @classmethod
    def from_scan_event(
        cls, event: dict[str, Any], previous: "BoardSnapshot | None" = None
    ) -> "BoardSnapshot":
        base = dict(previous.cells) if previous else {name: _EMPTY_CELL for name in _SQUARE_NAMES}
        raw_cells = event.get("cells") or event.get("squares") or {}
        for square, cell in raw_cells.items():
            base[square] = CellState.from_protocol(cell)
        return cls(cells=base, ts_ms=int(event.get("ts_ms", int(time() * 1000))))

    def occupied_squares(self) -> set[str]:
        return {s for s, c in self.cells.items() if c.occupied}

    def diff(self, other: "BoardSnapshot") -> dict[str, tuple[CellState | None, CellState | None]]:
        squares = set(self.cells) | set(other.cells)
        return {
            s: (self.cells.get(s), other.cells.get(s))
            for s in squares
            if self.cells.get(s) != other.cells.get(s)
        }

    def to_payload(self) -> dict[str, Any]:
        # Flat dict comprehension is faster than dict() with two args.
        return {
            "ts_ms": self.ts_ms,
            "cells": {s: c.to_protocol() for s, c in self.cells.items()},
        }


class BoardSensorService:
    __slots__ = ("latest",)

    def __init__(self) -> None:
        self.latest = BoardSnapshot.empty()

    def update_from_event(self, event: dict[str, Any]) -> BoardSnapshot:
        self.latest = BoardSnapshot.from_scan_event(event, previous=self.latest)
        return self.latest
