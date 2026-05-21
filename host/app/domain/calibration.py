from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

FILES = "abcdefgh"
RANKS = "12345678"
SQUARES = [f"{file}{rank}" for rank in RANKS for file in FILES]


@dataclass
class SquareCalibration:
    baseline: int = 2048
    occupancy_threshold: int = 120
    white_polarity_negative: bool = True

    def classify(self, raw_adc: int) -> dict[str, int]:
        delta = raw_adc - self.baseline
        mag = abs(delta)
        occupied = 1 if mag >= self.occupancy_threshold else 0
        if not occupied:
            polarity = 0
        else:
            polarity = -1 if delta < 0 else 1
        return {"o": occupied, "p": polarity, "m": mag}


@dataclass
class BoardCalibration:
    squares: dict[str, SquareCalibration] = field(
        default_factory=lambda: {sq: SquareCalibration() for sq in SQUARES}
    )

    def classify_scan(self, raw: dict[str, int]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for square, raw_adc in raw.items():
            cal = self.squares.get(square, SquareCalibration())
            out[square] = cal.classify(raw_adc)
        return out

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "BoardCalibration":
        board = cls()
        for square, values in payload.get("squares", {}).items():
            board.squares[square] = SquareCalibration(**values)
        return board

    def to_payload(self) -> dict[str, Any]:
        return {
            "squares": {
                square: {
                    "baseline": cal.baseline,
                    "occupancy_threshold": cal.occupancy_threshold,
                    "white_polarity_negative": cal.white_polarity_negative,
                }
                for square, cal in self.squares.items()
            }
        }
