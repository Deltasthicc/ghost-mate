"""
Comprehensive tests for host.app.domain.move_reconciler.MoveReconciler

Covers every possible sensor-delta scenario the reconciler must handle:
- Simple pawn moves (1-step and 2-step)
- All piece types moving
- Normal captures
- En passant (white and black)
- Kingside and queenside castling (both colors)
- All four promotion types (with and without capture)
- Ambiguous occupancy (promotion, symmetrical positions)
- No-match deltas (impossible physical states)
- Player picks up and replaces a piece (no change)
- Only one square changes (partial lift)
- Noise / extra squares change
- Confidence values
- ReconcileResult fields
"""
from __future__ import annotations

import chess
import pytest

from host.app.domain.move_reconciler import MoveReconciler
from host.app.hardware.board_sensor import BoardSnapshot, CellState
from host.tests.conftest import snapshot_from_board, reconcile_move


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def empty_snapshot() -> BoardSnapshot:
    return BoardSnapshot.empty()


def apply_delta(snap: BoardSnapshot, vacated: list[str], occupied: list[str],
                polarity: int = 1) -> BoardSnapshot:
    """Clone snap, mark squares vacated/occupied."""
    cells = dict(snap.cells)
    for sq in vacated:
        cells[sq] = CellState(False, 0, 0)
    for sq in occupied:
        cells[sq] = CellState(True, polarity, 800)
    return BoardSnapshot(cells=cells, ts_ms=snap.ts_ms + 50)


# ──────────────────────────────────────────────────────────────────────────────
# ReconcileResult structure
# ──────────────────────────────────────────────────────────────────────────────

class TestReconcileResultStructure:
    def test_result_has_move_attribute(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert hasattr(r, "move")

    def test_result_has_confidence_attribute(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert hasattr(r, "confidence")

    def test_result_has_reason_attribute(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert hasattr(r, "reason")

    def test_result_has_candidates_attribute(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert hasattr(r, "candidates")

    def test_successful_match_confidence_is_1(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert r.confidence == 1.0

    def test_no_match_confidence_is_0(self):
        board = chess.Board()
        before = snapshot_from_board(board)
        after = apply_delta(before, ["a1"], [], polarity=-1)  # Rook vanishes illegally
        r = MoveReconciler().reconcile(board, before, after)
        assert r.confidence == 0.0

    def test_successful_match_has_move(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert r.move is not None

    def test_no_match_move_is_none(self):
        board = chess.Board()
        before = snapshot_from_board(board)
        after = apply_delta(before, ["a1"], [], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None

    def test_candidates_list_for_unambiguous_move(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert r.candidates == ["e2e4"]

    def test_reason_string_for_success(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert "single" in r.reason.lower() or "match" in r.reason.lower()

    def test_reason_string_for_failure(self):
        board = chess.Board()
        before = snapshot_from_board(board)
        after = apply_delta(before, ["a1"], [], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert "no legal" in r.reason.lower() or "no match" in r.reason.lower()


# ──────────────────────────────────────────────────────────────────────────────
# Pawn moves
# ──────────────────────────────────────────────────────────────────────────────

class TestPawnMoves:
    def test_e2e4_white(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e4")
        assert r.move.uci() == "e2e4"

    def test_e2e3_white_single_step(self):
        r = reconcile_move(chess.STARTING_FEN, "e2e3")
        assert r.move.uci() == "e2e3"

    def test_d2d4_white(self):
        r = reconcile_move(chess.STARTING_FEN, "d2d4")
        assert r.move.uci() == "d2d4"

    def test_a2a4_white(self):
        r = reconcile_move(chess.STARTING_FEN, "a2a4")
        assert r.move.uci() == "a2a4"

    def test_h2h4_white(self):
        r = reconcile_move(chess.STARTING_FEN, "h2h4")
        assert r.move.uci() == "h2h4"

    def test_e7e5_black(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        r = reconcile_move(fen, "e7e5")
        assert r.move.uci() == "e7e5"

    def test_e7e6_black_single_step(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        r = reconcile_move(fen, "e7e6")
        assert r.move.uci() == "e7e6"

    def test_all_starting_white_pawn_double_moves(self):
        for file in "abcdefgh":
            r = reconcile_move(chess.STARTING_FEN, f"{file}2{file}4")
            assert r.move is not None
            assert r.move.uci() == f"{file}2{file}4"


# ──────────────────────────────────────────────────────────────────────────────
# Piece moves
# ──────────────────────────────────────────────────────────────────────────────

class TestPieceMoves:
    def test_knight_g1f3(self):
        r = reconcile_move(chess.STARTING_FEN, "g1f3")
        assert r.move.uci() == "g1f3"

    def test_knight_b1c3(self):
        r = reconcile_move(chess.STARTING_FEN, "b1c3")
        assert r.move.uci() == "b1c3"

    def test_bishop_move(self):
        fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
        r = reconcile_move(fen, "f1c4")
        assert r.move.uci() == "f1c4"

    def test_queen_move(self):
        fen = "rnbqkbnr/pppp1ppp/8/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 2 3"
        r = reconcile_move(fen, "d1e2")
        assert r.move.uci() == "d1e2"

    def test_rook_move_after_castling(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        r = reconcile_move(fen, "a1d1")
        assert r.move.uci() == "a1d1"

    def test_king_step(self):
        fen = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        r = reconcile_move(fen, "e1f1")
        assert r.move.uci() == "e1f1"

    def test_black_knight_b8c6(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        r = reconcile_move(fen, "b8c6")
        assert r.move.uci() == "b8c6"


# ──────────────────────────────────────────────────────────────────────────────
# Normal captures
# ──────────────────────────────────────────────────────────────────────────────

class TestNormalCaptures:
    def test_pawn_captures_pawn(self):
        fen = "4k3/8/8/8/3p4/4P3/8/4K3 w - - 0 1"
        r = reconcile_move(fen, "e3d4")
        assert r.move.uci() == "e3d4"
        assert r.confidence == 1.0

    def test_knight_captures_pawn(self):
        fen = "4k3/8/8/3p4/8/2N5/8/4K3 w - - 0 1"
        r = reconcile_move(fen, "c3d5")
        assert r.move.uci() == "c3d5"

    def test_bishop_captures_knight(self):
        fen = "4k3/8/8/3n4/8/1B6/8/4K3 w - - 0 1"
        r = reconcile_move(fen, "b3d5")
        assert r.move.uci() == "b3d5"

    def test_queen_captures_rook(self):
        fen = "4k3/8/8/3r4/8/3Q4/8/4K3 w - - 0 1"
        r = reconcile_move(fen, "d3d5")
        assert r.move.uci() == "d3d5"

    def test_rook_captures_rook(self):
        fen = "4k3/8/8/3r4/8/8/8/3RK3 w - - 0 1"
        r = reconcile_move(fen, "d1d5")
        assert r.move.uci() == "d1d5"

    def test_king_captures_pawn(self):
        fen = "4k3/8/8/8/8/4p3/8/4K3 w - - 0 1"
        r = reconcile_move(fen, "e1e2")
        # King can capture if not moving into check
        assert r.move is not None

    def test_black_pawn_captures_pawn(self):
        # Black pawn on e4, white pawn on d4 - black to move, black pawn on e4 captures d4
        # Actually need black pawn that can capture white: black pawn on e4, white pawn on d4
        # Simplest: black pawn e4 side-captures white pawn d4 ... but pawns capture diagonally forward
        # Black pawn on d4, white pawn on e4, black to move => d4xe3 if en passant
        # Direct capture: black pawn on e4 can capture white on d3... but black pawns move down
        # Black pawn goes from rank 7 toward rank 1, captures diagonally forward (down)
        # Black pawn on e5 captures white pawn on d4
        fen = "4k3/8/8/4p3/3P4/8/8/4K3 b - - 0 1"
        r = reconcile_move(fen, "e5d4")
        assert r.move.uci() == "e5d4"


# ──────────────────────────────────────────────────────────────────────────────
# En passant
# ──────────────────────────────────────────────────────────────────────────────

class TestEnPassant:
    def test_white_en_passant_east(self):
        fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
        r = reconcile_move(fen, "e5d6")
        assert r.move.uci() == "e5d6"
        assert r.confidence == 1.0

    def test_white_en_passant_west(self):
        fen = "8/8/8/2Pp4/8/8/8/4K2k w - d6 0 1"
        r = reconcile_move(fen, "c5d6")
        assert r.move.uci() == "c5d6"
        assert r.confidence == 1.0

    def test_black_en_passant_east(self):
        fen = "4K2k/8/8/8/3Pp3/8/8/8 b - d3 0 1"
        r = reconcile_move(fen, "e4d3")
        assert r.move.uci() == "e4d3"
        assert r.confidence == 1.0

    def test_black_en_passant_west(self):
        fen = "4K2k/8/8/8/2pP4/8/8/8 b - d3 0 1"
        r = reconcile_move(fen, "c4d3")
        assert r.move.uci() == "c4d3"
        assert r.confidence == 1.0

    def test_en_passant_captured_pawn_not_on_destination(self):
        """The key property of EP: the captured pawn is NOT on the destination square."""
        fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
        before_board = chess.Board(fen)
        after_board = chess.Board(fen)
        after_board.push(chess.Move.from_uci("e5d6"))

        before = snapshot_from_board(before_board)
        after = snapshot_from_board(after_board)

        # Verify the physical snapshot reflects EP: d5 is empty after the move
        assert not after.cells["d5"].occupied

        r = MoveReconciler().reconcile(before_board, before, after)
        assert r.move.uci() == "e5d6"

    def test_en_passant_not_available_without_ep_square(self):
        """Same position but no EP square — can't play EP."""
        fen = "8/8/8/3pP3/8/8/8/4K2k w - - 0 1"
        game_board = chess.Board(fen)
        # e5d6 should NOT be in legal moves
        assert chess.Move.from_uci("e5d6") not in game_board.legal_moves


# ──────────────────────────────────────────────────────────────────────────────
# Castling
# ──────────────────────────────────────────────────────────────────────────────

class TestCastling:
    def test_white_kingside_castling(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        r = reconcile_move(fen, "e1g1")
        assert r.move.uci() == "e1g1"
        assert r.confidence == 1.0

    def test_white_queenside_castling(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        r = reconcile_move(fen, "e1c1")
        assert r.move.uci() == "e1c1"
        assert r.confidence == 1.0

    def test_black_kingside_castling(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"
        r = reconcile_move(fen, "e8g8")
        assert r.move.uci() == "e8g8"
        assert r.confidence == 1.0

    def test_black_queenside_castling(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"
        r = reconcile_move(fen, "e8c8")
        assert r.move.uci() == "e8c8"
        assert r.confidence == 1.0

    def test_castling_occupancy_includes_rook(self):
        """After kingside castling, both g1 (king) and f1 (rook) must be occupied."""
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        after_board = chess.Board(fen)
        after_board.push(chess.Move.from_uci("e1g1"))
        after = snapshot_from_board(after_board)
        assert after.cells["g1"].occupied
        assert after.cells["f1"].occupied
        assert not after.cells["e1"].occupied
        assert not after.cells["h1"].occupied


# ──────────────────────────────────────────────────────────────────────────────
# Promotions
# ──────────────────────────────────────────────────────────────────────────────

class TestPromotions:
    """
    Promotion is the canonical ambiguous case: occupancy before/after is
    identical for all four promotion targets. The reconciler should return
    None move, confidence < 1, and all four candidates.
    """

    PROMO_FEN = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
    ALL_PROMOS = {"a7a8q", "a7a8r", "a7a8b", "a7a8n"}

    def test_promotion_to_queen_ambiguous(self):
        r = reconcile_move(self.PROMO_FEN, "a7a8q")
        assert r.move is None
        assert set(r.candidates) == self.ALL_PROMOS

    def test_promotion_to_rook_ambiguous(self):
        r = reconcile_move(self.PROMO_FEN, "a7a8r")
        assert r.move is None
        assert set(r.candidates) == self.ALL_PROMOS

    def test_promotion_to_bishop_ambiguous(self):
        r = reconcile_move(self.PROMO_FEN, "a7a8b")
        assert r.move is None
        assert set(r.candidates) == self.ALL_PROMOS

    def test_promotion_to_knight_ambiguous(self):
        r = reconcile_move(self.PROMO_FEN, "a7a8n")
        assert r.move is None
        assert set(r.candidates) == self.ALL_PROMOS

    def test_promotion_confidence_is_partial(self):
        r = reconcile_move(self.PROMO_FEN, "a7a8q")
        assert 0.0 < r.confidence < 1.0

    def test_promotion_reason_mentions_ambiguous(self):
        r = reconcile_move(self.PROMO_FEN, "a7a8q")
        assert "multiple" in r.reason.lower() or "ambiguous" in r.reason.lower()

    def test_promotion_with_capture_is_ambiguous(self):
        # White b-pawn captures black rook on a8
        fen = "r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1"
        before_board = chess.Board(fen)
        after_board = chess.Board(fen)
        after_board.push(chess.Move.from_uci("b7a8q"))
        before = snapshot_from_board(before_board)
        after = snapshot_from_board(after_board)
        r = MoveReconciler().reconcile(before_board, before, after)
        # All four promotion-captures should be candidates
        assert r.move is None
        assert len(r.candidates) == 4

    def test_black_promotion_ambiguous(self):
        fen = "4k3/8/8/8/8/8/7p/4K3 b - - 0 1"
        r = reconcile_move(fen, "h2h1q")
        assert r.move is None
        assert len(r.candidates) == 4


# ──────────────────────────────────────────────────────────────────────────────
# Impossible / no-match deltas
# ──────────────────────────────────────────────────────────────────────────────

class TestImpossibleDeltas:
    def test_rook_disappears_illegally(self):
        board = chess.Board()
        before = snapshot_from_board(board)
        after = apply_delta(before, ["a1"], [], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None
        assert r.confidence == 0.0

    def test_pawn_teleports_illegally(self):
        board = chess.Board()
        before = snapshot_from_board(board)
        # e2 pawn jumps to e5 (not a legal pawn move)
        after = apply_delta(before, ["e2"], ["e5"], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None
        assert r.confidence == 0.0

    def test_extra_piece_appears_from_nothing(self):
        board = chess.Board()
        before = snapshot_from_board(board)
        # e4 spontaneously becomes occupied
        after = apply_delta(before, [], ["e4"], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None
        assert r.confidence == 0.0

    def test_no_change_at_all(self):
        """Player lifts and replaces a piece — no net change in occupancy."""
        board = chess.Board()
        before = snapshot_from_board(board)
        after = snapshot_from_board(board)  # identical
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None
        assert r.confidence == 0.0

    def test_three_squares_changed(self):
        """Three squares change simultaneously — not a legal chess move."""
        board = chess.Board()
        before = snapshot_from_board(board)
        after = apply_delta(before, ["e2", "d2"], ["e4", "d4"], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        # Two white pawns can't both double-jump in a single move
        assert r.move is None

    def test_wrong_color_moved(self):
        """White's turn but a black square changes."""
        board = chess.Board()  # white to move
        before = snapshot_from_board(board)
        after = apply_delta(before, ["e7"], ["e5"], polarity=1)  # black pawn
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None
        assert r.confidence == 0.0

    def test_king_moves_into_check(self):
        """King stepping into check is not a legal move."""
        fen = "4k3/8/8/8/8/8/3r4/4K3 w - - 0 1"
        # d1 is attacked by black rook on d2; king can't go there
        board = chess.Board(fen)
        before = snapshot_from_board(board)
        after = apply_delta(before, ["e1"], ["d1"], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None

    def test_pinned_piece_moves_off_pin_line(self):
        """A pinned piece can't move off the pin line."""
        # White rook on d4 pinned by black rook on d8 (king on d1)
        # Moving e4 takes the rook off the d-file (pin line) -> illegal
        fen = "3rk3/8/8/8/3R4/8/8/3K4 w - - 0 1"
        board = chess.Board(fen)
        # Rook d4->e4 goes off the pin line, illegal
        before = snapshot_from_board(board)
        after = apply_delta(before, ["d4"], ["e4"], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None


# ──────────────────────────────────────────────────────────────────────────────
# Partial / noisy sensor data
# ──────────────────────────────────────────────────────────────────────────────

class TestNoisySensorData:
    def test_only_source_square_changes_no_destination(self):
        """Piece lifted but not placed yet — only one delta."""
        board = chess.Board()
        before = snapshot_from_board(board)
        after = apply_delta(before, ["e2"], [], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None
        assert r.confidence == 0.0

    def test_only_destination_appears_no_source(self):
        """Destination occupied but source still appears occupied (sensor lag)."""
        board = chess.Board()
        before = snapshot_from_board(board)
        after = apply_delta(before, [], ["e4"], polarity=-1)  # source e2 still there
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None

    def test_empty_board_any_delta_is_impossible(self):
        board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        before = snapshot_from_board(board)
        after = apply_delta(before, [], ["d4"], polarity=-1)
        r = MoveReconciler().reconcile(board, before, after)
        assert r.move is None
        assert r.confidence == 0.0
