from __future__ import annotations

from dataclasses import dataclass

FILES = "abcdefgh"
RANKS = "12345678"


@dataclass(frozen=True)
class XY:
    x_mm: float
    y_mm: float


@dataclass(frozen=True)
class SquareMapper:
    square_size_mm: float = 50.0
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0
    capture_left_x_mm: float = -60.0
    capture_right_x_mm: float = 460.0

    def square_to_xy(self, square: str) -> XY:
        if len(square) != 2 or square[0] not in FILES or square[1] not in RANKS:
            raise ValueError(f"Invalid algebraic square: {square}")
        file_index = FILES.index(square[0])
        rank_index = RANKS.index(square[1])
        return XY(
            x_mm=self.origin_x_mm + (file_index + 0.5) * self.square_size_mm,
            y_mm=self.origin_y_mm + (rank_index + 0.5) * self.square_size_mm,
        )

    def capture_slot_xy(self, color: str, slot: int) -> XY:
        if slot < 0:
            raise ValueError("slot must be >= 0")
        x = self.capture_left_x_mm if color.lower() == "white" else self.capture_right_x_mm
        y = self.origin_y_mm + ((slot % 8) + 0.5) * self.square_size_mm
        return XY(x_mm=x, y_mm=y)

    def all_square_centers(self) -> dict[str, XY]:
        return {f"{f}{r}": self.square_to_xy(f"{f}{r}") for r in RANKS for f in FILES}
