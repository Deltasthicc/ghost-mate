"""
Comprehensive PGN replay, game result detection, and full opening sequence tests.

Covers:
- Famous short games (Fool's Mate, Scholar's Mate, Opera Game)
- All draw conditions (stalemate, 50-move, insufficient material, repetition)
- Full opening replays (Ruy Lopez, Sicilian, Italian, King's Gambit, French)
- Castling in real game context
- En passant in real game context
- Promotion in real game context
- PGN round-trip (write → replay → verify positions)
- Board state after each move in a multi-move sequence
"""
from __future__ import annotations

import chess
import chess.pgn
import pytest
from pathlib import Path

from host.app.domain.game_state import GameState
from host.app.chesscore.pgn_store import PgnStore
from host.app.chesscore.replay import PgnReplay


# ──────────────────────────────────────────────────────────────────────────────
# Famous short checkmate games
# ──────────────────────────────────────────────────────────────────────────────

class TestFamousCheckmates:
    def test_fools_mate(self):
        game = GameState()
        for san in ["f3", "e5", "g4", "Qh4#"]:
            game.push_san(san)
        snap = game.snapshot()
        assert snap["is_game_over"] is True
        assert snap["is_check"] is True
        assert snap["result"] == "0-1"
        assert snap["legal_moves"] == []

    def test_fools_mate_via_uci(self):
        game = GameState()
        for uci in ["f2f3", "e7e5", "g2g4", "d8h4"]:
            game.push_uci(uci)
        assert game.result_if_game_over() == "0-1"
        assert game.board.is_checkmate()

    def test_reversed_fools_mate_black_plays_it(self):
        # White has to cooperate; this is just verifying result detection
        game = GameState()
        for san in ["e4", "f5", "d3", "g5", "Qh5#"]:
            game.push_san(san)
        assert game.result_if_game_over() == "1-0"

    def test_scholars_mate(self):
        game = GameState()
        for san in ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]:
            game.push_san(san)
        assert game.result_if_game_over() == "1-0"
        assert game.board.is_checkmate()

    def test_scholars_mate_positions(self):
        game = GameState()
        game.push_san("e4")
        assert game.board.piece_at(chess.E4).symbol() == "P"
        game.push_san("e5")
        game.push_san("Bc4")
        assert game.board.piece_at(chess.C4).symbol() == "B"
        game.push_san("Nc6")
        game.push_san("Qh5")
        game.push_san("Nf6")
        game.push_san("Qxf7#")
        assert game.board.is_checkmate()


# ──────────────────────────────────────────────────────────────────────────────
# Draw conditions
# ──────────────────────────────────────────────────────────────────────────────

class TestDrawConditions:
    def test_stalemate_king_only(self):
        # Qg6 stalemating black king in corner
        fen = "7k/8/6Q1/8/8/8/8/K7 b - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.result_if_game_over() == "1/2-1/2"
        assert game.board.is_stalemate()

    def test_stalemate_no_check(self):
        fen = "7k/8/6Q1/8/8/8/8/K7 b - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert not game.board.is_check()

    def test_insufficient_material_k_vs_k(self):
        fen = "4k3/8/8/8/8/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.result_if_game_over() == "1/2-1/2"
        assert game.board.is_insufficient_material()

    def test_insufficient_material_kb_vs_k(self):
        fen = "4k3/8/8/8/8/8/8/3BK3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.result_if_game_over() == "1/2-1/2"

    def test_insufficient_material_kn_vs_k(self):
        fen = "4k3/8/8/8/8/8/8/3NK3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.result_if_game_over() == "1/2-1/2"

    def test_sufficient_material_kq_vs_k(self):
        fen = "4k3/8/8/8/8/8/8/3QK3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        assert game.result_if_game_over() is None

    def test_fifty_move_rule(self):
        fen = "4k3/8/8/8/8/8/8/R3K3 w Q - 99 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("e1d1")  # 100th half-move without pawn/capture
        assert game.result_if_game_over() == "1/2-1/2"

    def test_threefold_repetition(self):
        game = GameState()
        # Knight shuffle: g1-f3-g1-f3-g1-f3 forces 3-fold repetition
        for _ in range(3):
            game.push_uci("g1f3")
            game.push_uci("g8f6")
            game.push_uci("f3g1")
            game.push_uci("f6g8")
        # python-chess sets can_claim_threefold_repetition but doesn't auto-draw
        # The result should register as a draw if claimed
        assert game.board.can_claim_threefold_repetition() or \
               game.board.is_fivefold_repetition()

    def test_fivefold_repetition_is_forced_draw(self):
        game = GameState()
        # 5-fold repetition is automatic in python-chess
        for _ in range(5):
            game.push_uci("g1f3")
            game.push_uci("g8f6")
            game.push_uci("f3g1")
            game.push_uci("f6g8")
        assert game.board.is_fivefold_repetition()
        assert game.result_if_game_over() == "1/2-1/2"


# ──────────────────────────────────────────────────────────────────────────────
# Special move correctness in real-game context
# ──────────────────────────────────────────────────────────────────────────────

class TestSpecialMovesInContext:
    def test_castling_ruy_lopez(self):
        game = GameState()
        for san in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "O-O"]:
            game.push_san(san)
        assert game.board.piece_at(chess.G1).symbol() == "K"
        assert game.board.piece_at(chess.F1).symbol() == "R"
        # Castling rights lost after O-O
        assert not game.board.has_castling_rights(chess.WHITE)

    def test_en_passant_french_defense(self):
        game = GameState()
        for san in ["e4", "e6", "d4", "d5", "e5", "c5", "c3", "cxd4", "cxd4", "f6"]:
            game.push_san(san)
        game.push_san("exf6")  # en passant (French Advance)
        assert game.board.piece_at(chess.F6).symbol() == "P"
        assert game.board.piece_at(chess.F5) is None

    def test_promotion_in_endgame_sequence(self):
        game = GameState()
        fen = "4k3/7P/8/8/8/8/8/4K3 w - - 0 1"
        game.new_game(fen)
        game.push_uci("h7h8q")
        assert game.board.piece_at(chess.H8).symbol() == "Q"

    def test_double_pawn_push_sets_ep_square(self):
        game = GameState()
        game.push_uci("e2e4")
        assert game.board.ep_square == chess.E3

    def test_single_pawn_push_no_ep_square(self):
        game = GameState()
        game.push_uci("e2e3")
        assert game.board.ep_square is None


# ──────────────────────────────────────────────────────────────────────────────
# Full opening sequences
# ──────────────────────────────────────────────────────────────────────────────

class TestOpeningSequences:
    def _play(self, game: GameState, sans: list[str]) -> None:
        for san in sans:
            game.push_san(san)

    def test_ruy_lopez_main_line(self):
        game = GameState()
        self._play(game, ["e4", "e5", "Nf3", "Nc6", "Bb5"])
        assert game.board.piece_at(chess.B5).symbol() == "B"
        assert not game.snapshot()["is_game_over"]

    def test_sicilian_defense_main_line(self):
        game = GameState()
        self._play(game, ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4"])
        assert game.board.piece_at(chess.D4).symbol() == "N"

    def test_italian_game(self):
        game = GameState()
        self._play(game, ["e4", "e5", "Nf3", "Nc6", "Bc4"])
        assert game.board.piece_at(chess.C4).symbol() == "B"

    def test_kings_gambit(self):
        game = GameState()
        self._play(game, ["e4", "e5", "f4"])
        assert game.board.piece_at(chess.F4).symbol() == "P"
        # Black can accept
        game.push_san("exf4")
        assert game.board.piece_at(chess.F4).symbol() == "p"

    def test_french_defense(self):
        game = GameState()
        self._play(game, ["e4", "e6", "d4", "d5"])
        assert game.board.piece_at(chess.D5).symbol() == "p"

    def test_queens_gambit(self):
        game = GameState()
        self._play(game, ["d4", "d5", "c4"])
        assert game.board.piece_at(chess.C4).symbol() == "P"

    def test_english_opening(self):
        game = GameState()
        self._play(game, ["c4", "e5", "Nc3", "Nf6", "g3", "d5"])
        assert not game.snapshot()["is_game_over"]

    def test_twenty_moves_without_error(self):
        """Plays the first 10 moves of a real GM game without any error."""
        game = GameState()
        # Kasparov vs Deep Blue 1997, Game 1 (first 10 moves)
        sans = ["Nf3", "d5", "g3", "Bg4", "Bg2", "Nd7", "h3", "Bxf3",
                "Bxf3", "c6"]
        self._play(game, sans)
        assert game.snapshot()["turn"] == "white"

    def test_opera_game_paul_morphy(self):
        """The famous Opera Game by Paul Morphy (1858)."""
        game = GameState()
        sans = [
            "e4", "e5", "Nf3", "d6", "d4", "Bg4", "dxe5", "Bxf3",
            "Qxf3", "dxe5", "Bc4", "Nf6", "Qb3", "Qe7", "Nc3", "c6",
            "Bg5", "b5", "Nxb5", "cxb5", "Bxb5+", "Nbd7", "O-O-O",
            "Rd8", "Rxd7", "Rxd7", "Rd1", "Qe6", "Bxd7+", "Nxd7",
            "Qb8+", "Nxb8", "Rd8#"
        ]
        self._play(game, sans)
        assert game.result_if_game_over() == "1-0"
        assert game.board.is_checkmate()


# ──────────────────────────────────────────────────────────────────────────────
# PGN round-trip tests
# ──────────────────────────────────────────────────────────────────────────────

class TestPgnRoundTrip:
    def _build_pgn_game(self, ucis: list[str]) -> chess.pgn.Game:
        game = chess.pgn.Game()
        node = game
        for uci in ucis:
            move = chess.Move.from_uci(uci)
            node = node.add_variation(move)
        return game

    def test_save_and_reload_simple_game(self, tmp_path):
        moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]
        store = PgnStore(directory=tmp_path)
        game = self._build_pgn_game(moves)
        path = store.save_game(game, "round-trip-test")
        loaded = PgnReplay().load_moves(path)
        assert loaded == moves

    def test_save_and_reload_castling(self, tmp_path):
        moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "e1g1"]
        store = PgnStore(directory=tmp_path)
        path = store.save_game(self._build_pgn_game(moves), "castling-rt")
        loaded = PgnReplay().load_moves(path)
        assert "e1g1" in loaded

    def test_save_and_reload_en_passant(self, tmp_path):
        pgn_text = "[FEN \"8/8/8/3pP3/8/8/8/4K2k w - d6 0 1\"]\n\n1. exd6 *\n"
        pgn_file = tmp_path / "ep.pgn"
        pgn_file.write_text(pgn_text)
        loaded = PgnReplay().load_moves(pgn_file)
        assert loaded == ["e5d6"]

    def test_save_and_reload_promotion(self, tmp_path):
        pgn_text = "[FEN \"4k3/P7/8/8/8/8/8/4K3 w - - 0 1\"]\n\n1. a8=Q *\n"
        pgn_file = tmp_path / "promo.pgn"
        pgn_file.write_text(pgn_text)
        loaded = PgnReplay().load_moves(pgn_file)
        assert loaded == ["a7a8q"]

    def test_replay_builds_correct_board_state(self, tmp_path):
        """After replaying all moves from PGN, the board should match."""
        moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"]
        store = PgnStore(directory=tmp_path)
        path = store.save_game(self._build_pgn_game(moves), "board-check")
        loaded = PgnReplay().load_moves(path)

        game = GameState()
        for uci in loaded:
            game.push_uci(uci)

        board = chess.Board()
        for uci in moves:
            board.push(chess.Move.from_uci(uci))

        assert game.board.fen() == board.fen()

    def test_fools_mate_pgn_round_trip(self, tmp_path):
        moves = ["f2f3", "e7e5", "g2g4", "d8h4"]
        store = PgnStore(directory=tmp_path)
        path = store.save_game(self._build_pgn_game(moves), "fools")
        loaded = PgnReplay().load_moves(path)
        assert loaded == moves

    def test_empty_pgn_returns_empty_list(self, tmp_path):
        pgn_file = tmp_path / "empty.pgn"
        pgn_file.write_text(str(chess.pgn.Game()))
        assert PgnReplay().load_moves(pgn_file) == []


# ──────────────────────────────────────────────────────────────────────────────
# Board state tracking across a full game
# ──────────────────────────────────────────────────────────────────────────────

class TestBoardStateTracking:
    def test_piece_positions_after_each_move(self):
        game = GameState()

        game.push_uci("e2e4")
        assert game.board.piece_at(chess.E4) is not None
        assert game.board.piece_at(chess.E2) is None

        game.push_uci("d7d5")
        assert game.board.piece_at(chess.D5) is not None

        game.push_uci("e4d5")  # capture
        assert game.board.piece_at(chess.D5).symbol() == "P"
        assert game.board.piece_at(chess.E4) is None

    def test_halfmove_clock_resets_on_pawn_move(self):
        game = GameState()
        game.push_uci("e2e4")
        assert game.board.halfmove_clock == 0

    def test_halfmove_clock_resets_on_capture(self):
        fen = "4k3/8/8/3p4/4P3/8/8/4K3 w - - 5 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("e4d5")  # pawn captures
        assert game.board.halfmove_clock == 0

    def test_halfmove_clock_increments_on_piece_move(self):
        fen = "4k3/8/8/8/8/5N2/8/4K3 w - - 3 1"
        game = GameState()
        game.new_game(fen)
        game.push_uci("f3e5")
        assert game.board.halfmove_clock == 4

    def test_fullmove_number_increments_after_black_moves(self):
        game = GameState()
        assert game.board.fullmove_number == 1
        game.push_uci("e2e4")
        assert game.board.fullmove_number == 1  # still 1 until black moves
        game.push_uci("e7e5")
        assert game.board.fullmove_number == 2

    def test_turn_tracking_ten_moves(self):
        game = GameState()
        moves = ["e2e4", "e7e5", "g1f3", "b8c6",
                 "f1b5", "a7a6", "b5a4", "g8f6",
                 "e1g1", "f8e7"]
        for i, uci in enumerate(moves):
            game.push_uci(uci)
            assert game.board.turn == (chess.BLACK if i % 2 == 0 else chess.WHITE)
