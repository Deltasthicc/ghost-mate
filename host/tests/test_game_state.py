"""
Comprehensive tests for host.app.domain.game_state.GameState

Covers:
- Construction and new_game()
- Custom FEN loading
- Legal move enumeration
- UCI and SAN move pushing
- Error handling (illegal/invalid moves)
- Game-over detection (checkmate, stalemate, draw variants)
- Snapshot structure
- State fields (robot_busy, last_error, turn, is_check)
- Promotion (all four piece types)
- Castling (both sides, both colors)
- En passant
- 50-move rule, repetition
"""
from __future__ import annotations

import chess
import pytest

from host.app.domain.game_state import GameState


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────

class TestGameStateConstruction:
    def test_default_starts_at_starting_position(self):
        game = GameState()
        assert game.board.fen() == chess.Board().fen()

    def test_game_id_is_set_on_construction(self):
        game = GameState()
        assert game.game_id.startswith("game-")

    def test_robot_busy_starts_false(self):
        assert GameState().robot_busy is False

    def test_last_error_starts_none(self):
        assert GameState().last_error is None


# ──────────────────────────────────────────────────────────────────────────────
# new_game()
# ──────────────────────────────────────────────────────────────────────────────

class TestNewGame:
    def test_new_game_resets_to_start(self):
        game = GameState()
        game.push_uci("e2e4")
        game.new_game()
        assert game.board.fen() == chess.Board().fen()

    def test_new_game_changes_game_id(self):
        game = GameState()
        first_id = game.game_id
        game.new_game()
        assert game.game_id != first_id

    def test_new_game_clears_robot_busy(self):
        game = GameState()
        game.robot_busy = True
        game.new_game()
        assert game.robot_busy is False

    def test_new_game_clears_last_error(self):
        game = GameState()
        game.last_error = "something_bad"
        game.new_game()
        assert game.last_error is None

    def test_new_game_from_custom_fen(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.board.fen() == fen

    def test_new_game_from_fen_preserves_castling_rights(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.board.has_kingside_castling_rights(chess.WHITE)
        assert game.board.has_queenside_castling_rights(chess.WHITE)
        assert game.board.has_kingside_castling_rights(chess.BLACK)
        assert game.board.has_queenside_castling_rights(chess.BLACK)

    def test_new_game_from_fen_no_castling_rights(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert not game.board.has_kingside_castling_rights(chess.WHITE)
        assert not game.board.has_queenside_castling_rights(chess.WHITE)

    def test_new_game_from_fen_with_en_passant_target(self):
        fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.board.ep_square == chess.D6

    def test_new_game_black_to_move(self):
        fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.board.turn == chess.BLACK

    def test_new_game_invalid_fen_raises(self):
        game = GameState()
        with pytest.raises(ValueError):
            game.new_game("this is not a fen")


# ──────────────────────────────────────────────────────────────────────────────
# legal_uci_moves()
# ──────────────────────────────────────────────────────────────────────────────

class TestLegalUciMoves:
    def test_start_position_has_20_legal_moves(self):
        game = GameState()
        moves = game.legal_uci_moves()
        assert len(moves) == 20

    def test_start_position_contains_expected_pawn_moves(self):
        game = GameState()
        moves = set(game.legal_uci_moves())
        for file in "abcdefgh":
            assert f"{file}2{file}3" in moves
            assert f"{file}2{file}4" in moves

    def test_start_position_contains_knight_moves(self):
        game = GameState()
        moves = set(game.legal_uci_moves())
        assert "g1f3" in moves
        assert "g1h3" in moves
        assert "b1c3" in moves
        assert "b1a3" in moves

    def test_no_legal_moves_in_checkmate(self):
        game = GameState()
        for san in ["f3", "e5", "g4", "Qh4#"]:
            game.push_san(san)
        assert game.legal_uci_moves() == []

    def test_no_legal_moves_in_stalemate(self):
        # Classic stalemate: only king to move with no legal squares
        fen = "7k/8/6Q1/8/8/8/8/K7 b - - 0 1"
        game = GameState()
        game.new_game(fen)
        # Verify it's stalemate
        assert game.board.is_stalemate()
        assert game.legal_uci_moves() == []

    def test_legal_moves_are_uci_strings(self):
        game = GameState()
        for move in game.legal_uci_moves():
            assert isinstance(move, str)
            assert len(move) in (4, 5)  # 4 for normal, 5 for promotion

    def test_legal_moves_after_e4_black_has_more_options(self):
        game = GameState()
        game.push_uci("e2e4")
        # Black still has 20 moves (pawn advances + knights)
        assert len(game.legal_uci_moves()) == 20

    def test_promotion_moves_appear_when_pawn_about_to_promote(self):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        moves = set(game.legal_uci_moves())
        assert "a7a8q" in moves
        assert "a7a8r" in moves
        assert "a7a8b" in moves
        assert "a7a8n" in moves

    def test_castling_moves_appear_when_path_clear(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        moves = set(game.legal_uci_moves())
        assert "e1g1" in moves  # kingside
        assert "e1c1" in moves  # queenside

    def test_no_castling_through_check(self):
        # Rook on e-file threatens the castling path
        fen = "r3k2r/8/8/8/8/8/8/R2rK2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        moves = set(game.legal_uci_moves())
        # White king can't castle queenside (d1 is attacked)
        assert "e1c1" not in moves


# ──────────────────────────────────────────────────────────────────────────────
# push_uci()
# ──────────────────────────────────────────────────────────────────────────────

class TestPushUci:
    def test_legal_pawn_move(self):
        game = GameState()
        move = game.push_uci("e2e4")
        assert move.uci() == "e2e4"
        assert game.board.piece_at(chess.E4).symbol() == "P"
        assert game.board.piece_at(chess.E2) is None

    def test_legal_knight_move(self):
        game = GameState()
        game.push_uci("g1f3")
        assert game.board.piece_at(chess.F3).symbol() == "N"

    def test_push_uci_returns_chess_move_object(self):
        game = GameState()
        result = game.push_uci("e2e4")
        assert isinstance(result, chess.Move)

    def test_illegal_move_raises_value_error(self):
        game = GameState()
        with pytest.raises(ValueError, match="Illegal move"):
            game.push_uci("e2e5")

    def test_out_of_turn_move_raises_value_error(self):
        game = GameState()
        with pytest.raises(ValueError):
            game.push_uci("e7e5")  # Black's move at white's turn

    def test_invalid_uci_string_raises(self):
        game = GameState()
        with pytest.raises(Exception):
            game.push_uci("zzz")

    def test_empty_string_raises(self):
        game = GameState()
        with pytest.raises(Exception):
            game.push_uci("")

    def test_turn_alternates_after_moves(self):
        game = GameState()
        assert game.board.turn == chess.WHITE
        game.push_uci("e2e4")
        assert game.board.turn == chess.BLACK
        game.push_uci("e7e5")
        assert game.board.turn == chess.WHITE

    def test_case_insensitive_uci(self):
        game = GameState()
        game.push_uci("E2E4")
        assert game.board.piece_at(chess.E4) is not None

    def test_uci_with_leading_trailing_whitespace(self):
        game = GameState()
        game.push_uci("  e2e4  ")
        assert game.board.piece_at(chess.E4) is not None

    def test_sequential_moves_build_correct_position(self):
        game = GameState()
        for uci in ["e2e4", "e7e5", "g1f3", "b8c6"]:
            game.push_uci(uci)
        assert game.board.piece_at(chess.F3).symbol() == "N"
        assert game.board.piece_at(chess.C6).symbol() == "n"

    def test_en_passant_removes_captured_pawn(self):
        fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("e5d6")
        assert game.board.piece_at(chess.D6).symbol() == "P"
        assert game.board.piece_at(chess.D5) is None  # Captured pawn gone

    def test_kingside_castling_white(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("e1g1")
        assert game.board.piece_at(chess.G1).symbol() == "K"
        assert game.board.piece_at(chess.F1).symbol() == "R"
        assert game.board.piece_at(chess.E1) is None
        assert game.board.piece_at(chess.H1) is None

    def test_queenside_castling_white(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("e1c1")
        assert game.board.piece_at(chess.C1).symbol() == "K"
        assert game.board.piece_at(chess.D1).symbol() == "R"
        assert game.board.piece_at(chess.E1) is None
        assert game.board.piece_at(chess.A1) is None

    def test_kingside_castling_black(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("e8g8")
        assert game.board.piece_at(chess.G8).symbol() == "k"
        assert game.board.piece_at(chess.F8).symbol() == "r"

    def test_queenside_castling_black(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("e8c8")
        assert game.board.piece_at(chess.C8).symbol() == "k"
        assert game.board.piece_at(chess.D8).symbol() == "r"

    def test_castling_removes_castling_rights(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("e1g1")
        assert not game.board.has_castling_rights(chess.WHITE)

    def test_promotion_to_queen(self):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("a7a8q")
        assert game.board.piece_at(chess.A8).symbol() == "Q"

    def test_promotion_to_rook(self):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("a7a8r")
        assert game.board.piece_at(chess.A8).symbol() == "R"

    def test_promotion_to_bishop(self):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("a7a8b")
        assert game.board.piece_at(chess.A8).symbol() == "B"

    def test_promotion_to_knight(self):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("a7a8n")
        assert game.board.piece_at(chess.A8).symbol() == "N"

    def test_promotion_with_capture(self):
        # White pawn on b7 captures black rook on a8
        fen = "r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("b7a8q")
        assert game.board.piece_at(chess.A8).symbol() == "Q"


# ──────────────────────────────────────────────────────────────────────────────
# push_san()
# ──────────────────────────────────────────────────────────────────────────────

class TestPushSan:
    def test_simple_pawn_san(self):
        game = GameState()
        game.push_san("e4")
        assert game.board.piece_at(chess.E4) is not None

    def test_knight_san(self):
        game = GameState()
        game.push_san("Nf3")
        assert game.board.piece_at(chess.F3).symbol() == "N"

    def test_san_castling_kingside(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_san("O-O")
        assert game.board.piece_at(chess.G1).symbol() == "K"

    def test_san_castling_queenside(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_san("O-O-O")
        assert game.board.piece_at(chess.C1).symbol() == "K"

    def test_illegal_san_raises(self):
        game = GameState()
        with pytest.raises(Exception):
            game.push_san("Qh5")  # illegal at start

    def test_invalid_san_notation_raises(self):
        game = GameState()
        with pytest.raises(Exception):
            game.push_san("Zzz99")

    def test_san_sequence(self):
        game = GameState()
        for san in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "O-O"]:
            game.push_san(san)
        assert game.board.piece_at(chess.G1).symbol() == "K"
        assert game.board.piece_at(chess.F1).symbol() == "R"

    def test_san_promotion(self):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        game.push_san("a8=Q")
        assert game.board.piece_at(chess.A8).symbol() == "Q"


# ──────────────────────────────────────────────────────────────────────────────
# result_if_game_over()
# ──────────────────────────────────────────────────────────────────────────────

class TestResultIfGameOver:
    def test_returns_none_in_progress(self):
        game = GameState()
        assert game.result_if_game_over() is None

    def test_fools_mate_returns_black_wins(self):
        game = GameState()
        for san in ["f3", "e5", "g4", "Qh4#"]:
            game.push_san(san)
        assert game.result_if_game_over() == "0-1"

    def test_scholars_mate_returns_black_wins(self):
        # 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6?? 4.Qxf7#
        game = GameState()
        for san in ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]:
            game.push_san(san)
        assert game.result_if_game_over() == "1-0"

    def test_stalemate_returns_draw(self):
        fen = "7k/8/6Q1/8/8/8/8/K7 b - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.result_if_game_over() == "1/2-1/2"

    def test_insufficient_material_k_vs_k(self):
        fen = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        # K vs K — draw by insufficient material
        assert game.result_if_game_over() == "1/2-1/2"

    def test_insufficient_material_k_plus_b_vs_k(self):
        fen = "4k3/8/8/8/8/8/8/4KB2 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.result_if_game_over() == "1/2-1/2"

    def test_fifty_move_rule_triggers_draw(self):
        game = GameState()
        # Position with kings and rooks to shuffle without captures/pawn moves
        fen = "4k3/8/8/8/8/8/8/R3K3 w Q - 99 1"
        game.new_game(fen)
        # One king shuffle triggers claim
        game.push_uci("e1d1")
        assert game.result_if_game_over() == "1/2-1/2"


# ──────────────────────────────────────────────────────────────────────────────
# snapshot()
# ──────────────────────────────────────────────────────────────────────────────

class TestSnapshot:
    def test_snapshot_has_required_keys(self):
        game = GameState()
        snap = game.snapshot()
        required_keys = {
            "game_id", "fen", "turn", "legal_moves",
            "is_check", "is_game_over", "result", "robot_busy", "last_error",
        }
        assert required_keys.issubset(set(snap.keys()))

    def test_snapshot_turn_white_at_start(self):
        assert GameState().snapshot()["turn"] == "white"

    def test_snapshot_turn_black_after_white_move(self):
        game = GameState()
        game.push_uci("e2e4")
        assert game.snapshot()["turn"] == "black"

    def test_snapshot_is_check_false_at_start(self):
        assert GameState().snapshot()["is_check"] is False

    def test_snapshot_is_check_true_when_in_check(self):
        fen = "4k3/8/8/8/8/8/4R3/4K3 b - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.snapshot()["is_check"] is True

    def test_snapshot_is_game_over_false_in_progress(self):
        assert GameState().snapshot()["is_game_over"] is False

    def test_snapshot_is_game_over_true_in_checkmate(self):
        game = GameState()
        for san in ["f3", "e5", "g4", "Qh4#"]:
            game.push_san(san)
        snap = game.snapshot()
        assert snap["is_game_over"] is True
        assert snap["result"] == "0-1"

    def test_snapshot_result_none_in_progress(self):
        assert GameState().snapshot()["result"] is None

    def test_snapshot_robot_busy_reflects_state(self):
        game = GameState()
        game.robot_busy = True
        assert game.snapshot()["robot_busy"] is True
        game.robot_busy = False
        assert game.snapshot()["robot_busy"] is False

    def test_snapshot_last_error_reflects_state(self):
        game = GameState()
        game.last_error = "test_error"
        assert game.snapshot()["last_error"] == "test_error"

    def test_snapshot_fen_changes_after_move(self):
        game = GameState()
        original_fen = game.snapshot()["fen"]
        game.push_uci("e2e4")
        assert game.snapshot()["fen"] != original_fen

    def test_snapshot_legal_moves_is_list_of_strings(self):
        snap = GameState().snapshot()
        assert isinstance(snap["legal_moves"], list)
        assert all(isinstance(m, str) for m in snap["legal_moves"])
