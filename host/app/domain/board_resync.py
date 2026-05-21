from __future__ import annotations

import chess

from host.app.hardware.board_sensor import BoardSnapshot


class BoardResync:
    """Helpers for checking whether the physical occupancy agrees with python-chess."""

    @staticmethod
    def expected_occupied_squares(board: chess.Board) -> set[str]:
        return {chess.square_name(square) for square in board.piece_map()}

    @staticmethod
    def physical_occupied_squares(snapshot: BoardSnapshot) -> set[str]:
        return {square for square, cell in snapshot.cells.items() if cell.occupied}

    def mismatch(self, board: chess.Board, snapshot: BoardSnapshot) -> dict[str, list[str]]:
        expected = self.expected_occupied_squares(board)
        physical = self.physical_occupied_squares(snapshot)
        return {
            "missing_on_board": sorted(expected - physical),
            "extra_on_board": sorted(physical - expected),
        }
