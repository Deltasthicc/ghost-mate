from __future__ import annotations

from dataclasses import dataclass

import chess

from host.app.hardware.board_sensor import BoardSnapshot


@dataclass(frozen=True)
class ReconcileResult:
    move: chess.Move | None
    confidence: float
    reason: str
    candidates: list[str]


class MoveReconciler:
    """
    Converts a before/after Hall-sensor occupancy change into one legal chess move.

    This intentionally uses python-chess as the authority. The Hall board reports square occupancy;
    the reconciler checks which legal move would transform the old occupancy into the new occupancy.
    """

    def reconcile(
        self,
        board: chess.Board,
        before: BoardSnapshot,
        after: BoardSnapshot,
    ) -> ReconcileResult:
        before_occ = before.occupied_squares()
        after_occ = after.occupied_squares()
        matched: list[chess.Move] = []

        for move in board.legal_moves:
            expected = self._apply_occupancy_only(board, before_occ, move)
            if expected == after_occ:
                matched.append(move)

        if len(matched) == 1:
            return ReconcileResult(matched[0], 1.0, "single legal occupancy match", [matched[0].uci()])
        if not matched:
            return ReconcileResult(None, 0.0, "no legal move matches sensor delta", [])
        return ReconcileResult(None, 0.4, "multiple legal moves match occupancy", [m.uci() for m in matched])

    def _apply_occupancy_only(
        self, board: chess.Board, occupied: set[str], move: chess.Move
    ) -> set[str]:
        next_occ = set(occupied)
        from_sq = chess.square_name(move.from_square)
        to_sq = chess.square_name(move.to_square)

        # Move the piece itself.
        next_occ.discard(from_sq)
        next_occ.discard(to_sq)
        next_occ.add(to_sq)

        # En passant removes a pawn from a square different from the destination.
        if board.is_en_passant(move):
            captured_rank_offset = -8 if board.turn == chess.WHITE else 8
            captured_square = chess.square_name(move.to_square + captured_rank_offset)
            next_occ.discard(captured_square)

        # Castling moves the rook too.
        if board.is_castling(move):
            if chess.square_file(move.to_square) > chess.square_file(move.from_square):
                rook_from = chess.H1 if board.turn == chess.WHITE else chess.H8
                rook_to = chess.F1 if board.turn == chess.WHITE else chess.F8
            else:
                rook_from = chess.A1 if board.turn == chess.WHITE else chess.A8
                rook_to = chess.D1 if board.turn == chess.WHITE else chess.D8
            next_occ.discard(chess.square_name(rook_from))
            next_occ.add(chess.square_name(rook_to))

        return next_occ
