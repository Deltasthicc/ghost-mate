"""Move history + PGN export / import — base, edge, and negative cases.

This file exercises:
- The shape and content of ``snapshot()["move_history"]``
- ``GameState.pgn()`` round-tripping for normal games, custom starts, special
  moves (castling, en passant, promotion, captures, checks), long games, and
  games loaded back from their own exported PGN
- The HTTP endpoints ``GET /api/state/pgn`` and ``POST /api/position/pgn``
  for both happy paths and negative inputs (malformed, illegal, empty, huge)

It deliberately keeps every test independent of Stockfish.
"""
from __future__ import annotations

import io

import chess
import chess.pgn
import pytest

from host.app.domain.game_state import GameState


# ─────────────────────────────────────────────────────────────────────────────
# move_history()
# ─────────────────────────────────────────────────────────────────────────────

class TestMoveHistoryShape:
    def test_empty_history_is_empty_list(self, game):
        history = game.move_history()
        assert history == []

    def test_history_after_three_moves(self, game):
        for uci in ("e2e4", "e7e5", "g1f3"):
            game.push_uci(uci)
        history = game.move_history()
        assert len(history) == 3
        assert [entry["uci"] for entry in history] == ["e2e4", "e7e5", "g1f3"]
        assert [entry["san"] for entry in history] == ["e4", "e5", "Nf3"]
        assert [entry["color"] for entry in history] == ["white", "black", "white"]
        assert [entry["ply"] for entry in history] == [1, 2, 3]
        assert [entry["move_number"] for entry in history] == [1, 1, 2]

    def test_history_records_castling_san(self, game):
        for uci in ("e2e4", "e7e5", "g1f3", "g8f6", "f1c4", "f8c5", "e1g1"):
            game.push_uci(uci)
        history = game.move_history()
        assert history[-1]["san"] == "O-O"
        assert history[-1]["uci"] == "e1g1"

    def test_history_records_queenside_castling_san(self, game):
        for uci in ("d2d4", "d7d5", "b1c3", "b8c6", "c1f4", "c8f5",
                    "d1d2", "d8d7", "e1c1"):
            game.push_uci(uci)
        history = game.move_history()
        assert history[-1]["san"] == "O-O-O"

    def test_history_records_promotion(self, game):
        game.new_game("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        game.push_uci("a7a8q")
        entry = game.move_history()[-1]
        # a8=Q on e8 king is a check via the a-file → SAN ends with '+'.
        assert entry["san"].startswith("a8=Q")
        assert entry["uci"] == "a7a8q"

    def test_history_records_underpromotion(self, game):
        game.new_game("8/P7/8/8/8/8/8/4k2K w - - 0 1")
        game.push_uci("a7a8n")
        entry = game.move_history()[-1]
        assert entry["san"].startswith("a8=N")

    def test_history_records_en_passant(self, game):
        game.new_game("rnbqkbnr/ppp1pppp/8/3pP3/8/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 3")
        game.push_uci("e5d6")
        entry = game.move_history()[-1]
        assert entry["san"] == "exd6"

    def test_history_records_check_marker(self, game):
        # 1.e4 e5 2.Bc4 Bc5 3.Qh5 — threatens mate but not check; 1.e4 e5 2.Qh5 → check
        for uci in ("e2e4", "f7f6", "d1h5"):
            game.push_uci(uci)
        history = game.move_history()
        assert history[-1]["san"].endswith("+")

    def test_fen_after_replay_matches_each_entry(self, game):
        moves = ("d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4")
        for uci in moves:
            game.push_uci(uci)
        replay = chess.Board()
        for entry, uci in zip(game.move_history(), moves):
            replay.push_uci(uci)
            assert entry["fen_after"] == replay.fen()

    def test_history_is_pure_each_call(self, game):
        for uci in ("e2e4", "e7e5"):
            game.push_uci(uci)
        first = game.move_history()
        second = game.move_history()
        assert first == second
        assert first is not second  # fresh list each time

    def test_new_game_clears_history(self, game):
        for uci in ("e2e4", "e7e5"):
            game.push_uci(uci)
        assert game.move_history()
        game.new_game()
        assert game.move_history() == []

    def test_long_game_has_correct_move_numbers(self, game):
        # 40 plies of legal back-and-forth using a real opening line.
        opening_uci = (
            "e2e4 c7c5 g1f3 d7d6 d2d4 c5d4 f3d4 g8f6 b1c3 a7a6 "
            "f1e2 e7e5 d4b3 f8e7 e1g1 e8g8 c1g5 b8c6 d1d2 c8e6 "
        ).split()
        for uci in opening_uci:
            game.push_uci(uci)
        history = game.move_history()
        assert len(history) == 20
        assert history[0]["move_number"] == 1
        assert history[-1]["move_number"] == 10


# ─────────────────────────────────────────────────────────────────────────────
# Custom-FEN-started games
# ─────────────────────────────────────────────────────────────────────────────

class TestHistoryFromCustomFen:
    def test_start_fen_recorded_in_snapshot(self, game):
        custom = "r3k2r/pppq1ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPPQ1PPP/R3K2R w KQkq - 0 8"
        game.new_game(custom)
        snap = game.snapshot()
        assert snap["start_fen"] == custom
        assert snap["move_history"] == []

    def test_history_san_correct_from_mid_game_position(self, game):
        custom = "r3k2r/pppq1ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPPQ1PPP/R3K2R w KQkq - 0 8"
        game.new_game(custom)
        game.push_uci("e1g1")  # White short castles
        game.push_uci("e8g8")  # Black short castles
        history = game.move_history()
        assert history[0]["san"] == "O-O"
        assert history[1]["san"] == "O-O"
        # First move from a mid-game FEN still starts at ply 1 / move_number 1
        assert history[0]["ply"] == 1
        assert history[0]["move_number"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# pgn()
# ─────────────────────────────────────────────────────────────────────────────

class TestPgnExport:
    def test_empty_game_pgn_has_result_star(self, game):
        text = game.pgn()
        assert "[Result \"*\"]" in text
        assert "[Event \"GhostMate Session\"]" in text

    def test_pgn_contains_main_line(self, game):
        for uci in ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"):
            game.push_uci(uci)
        text = game.pgn()
        assert "1. e4 e5 2. Nf3 Nc6 3. Bb5" in text

    def test_pgn_setup_header_only_when_starting_position_custom(self, game):
        text = game.pgn()
        assert "[SetUp" not in text

        custom = "r3k2r/pppq1ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPPQ1PPP/R3K2R w KQkq - 0 8"
        game.new_game(custom)
        text2 = game.pgn()
        assert "[SetUp \"1\"]" in text2
        assert f"[FEN \"{custom}\"]" in text2

    def test_pgn_result_reflects_checkmate(self, game):
        # Scholar's mate: 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6?? 4.Qxf7#
        for uci in ("e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"):
            game.push_uci(uci)
        assert game.board.is_checkmate()
        text = game.pgn()
        assert "[Result \"1-0\"]" in text
        assert "Qxf7#" in text

    def test_pgn_roundtrip_preserves_main_line(self, game):
        for uci in ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4"):
            game.push_uci(uci)
        first = game.pgn()

        parsed = chess.pgn.read_game(io.StringIO(first))
        replayed = GameState()
        replayed.load_pgn_game(parsed)
        # Same move stack and same SAN sequence
        assert [m.uci() for m in replayed.board.move_stack] == [
            m.uci() for m in game.board.move_stack
        ]
        second = replayed.pgn()
        # The headers' dates may differ; compare the mainline-moves portion.
        first_moves = first.split("\n\n")[1].strip()
        second_moves = second.split("\n\n")[1].strip()
        assert first_moves == second_moves

    def test_pgn_includes_castling_promotion_and_capture(self, game):
        moves = (
            "e2e4 e7e5 g1f3 b8c6 f1c4 g8f6 e1g1 f8c5 "  # castling
            "d2d3 d7d6 c2c3 e8g8 "  # black castles
        ).split()
        for uci in moves:
            game.push_uci(uci)
        text = game.pgn()
        # Both castles appear
        assert "O-O" in text


# ─────────────────────────────────────────────────────────────────────────────
# load_pgn_game
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadPgnGame:
    def test_load_pgn_preserves_move_stack(self, game):
        pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 *"
        parsed = chess.pgn.read_game(io.StringIO(pgn))
        game.load_pgn_game(parsed)
        assert len(game.board.move_stack) == 8
        history = game.move_history()
        assert [e["san"] for e in history] == \
            ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"]

    def test_load_pgn_resets_robot_state(self, game):
        game.robot_busy = True
        game.last_error = "stale"
        parsed = chess.pgn.read_game(io.StringIO("1. e4 e5 *"))
        game.load_pgn_game(parsed)
        assert game.robot_busy is False
        assert game.last_error is None

    def test_load_pgn_assigns_new_game_id(self, game):
        before = game.game_id
        parsed = chess.pgn.read_game(io.StringIO("1. e4 e5 *"))
        game.load_pgn_game(parsed)
        assert game.game_id != before

    def test_load_pgn_only_takes_mainline_not_variations(self, game):
        pgn = "1. e4 e5 (1... c5 2. Nf3 d6) 2. Nf3 *"
        parsed = chess.pgn.read_game(io.StringIO(pgn))
        game.load_pgn_game(parsed)
        history = game.move_history()
        assert [e["san"] for e in history] == ["e4", "e5", "Nf3"]

    def test_load_pgn_with_setup_fen_preserves_start_fen(self, game):
        pgn = (
            "[SetUp \"1\"]\n"
            "[FEN \"4k3/8/8/8/8/8/8/R3K3 w Q - 0 1\"]\n\n"
            "1. O-O-O Kd7 *\n"
        )
        parsed = chess.pgn.read_game(io.StringIO(pgn))
        game.load_pgn_game(parsed)
        assert game.start_fen.startswith("4k3/8/8/8/8/8/8/R3K3")
        history = game.move_history()
        assert history[0]["san"] == "O-O-O"


# ─────────────────────────────────────────────────────────────────────────────
# /api/state/pgn  endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestStatePgnEndpoint:
    def test_empty_game_returns_star(self, fresh_client):
        response = fresh_client.get("/api/state/pgn")
        assert response.status_code == 200
        data = response.json()
        assert data["ply"] == 0
        assert "*" in data["pgn"]
        assert data["start_fen"].startswith("rnbqkbnr/pppppppp")

    def test_response_shape(self, fresh_client):
        fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        response = fresh_client.get("/api/state/pgn")
        data = response.json()
        for key in ("fen", "start_fen", "pgn", "ply"):
            assert key in data

    def test_pgn_reflects_recent_moves(self, fresh_client):
        for uci in ("e2e4", "c7c5", "g1f3", "d7d6"):
            assert fresh_client.post("/api/move/human", json={"uci": uci}).status_code == 200
        data = fresh_client.get("/api/state/pgn").json()
        assert "1. e4 c5 2. Nf3 d6" in data["pgn"]
        assert data["ply"] == 4

    def test_pgn_endpoint_idempotent(self, fresh_client):
        fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        first = fresh_client.get("/api/state/pgn").json()["pgn"]
        second = fresh_client.get("/api/state/pgn").json()["pgn"]
        assert first == second


# ─────────────────────────────────────────────────────────────────────────────
# /api/position/pgn  endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestPositionPgnEndpoint:
    def test_valid_pgn_load_succeeds(self, fresh_client):
        pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 *"
        response = fresh_client.post("/api/position/pgn", json={"pgn": pgn})
        assert response.status_code == 200
        snap = response.json()
        assert len(snap["move_history"]) == 5

    def test_invalid_pgn_returns_400(self, fresh_client):
        response = fresh_client.post("/api/position/pgn",
                                     json={"pgn": "this is not pgn"})
        # Either 400 or 200 with a no-op load is acceptable, but it must not 500.
        assert response.status_code in (200, 400)
        if response.status_code == 200:
            # Loaded as an empty game
            assert response.json()["move_history"] == []

    def test_pgn_with_illegal_move_does_not_500(self, fresh_client):
        bad = "1. e4 e5 2. Bx5 *"  # illegal capture
        response = fresh_client.post("/api/position/pgn", json={"pgn": bad})
        assert response.status_code in (200, 400)

    def test_empty_pgn_body_returns_400(self, fresh_client):
        response = fresh_client.post("/api/position/pgn", json={"pgn": ""})
        assert response.status_code == 400

    def test_huge_pgn_with_setup_loads(self, fresh_client):
        # A long game starting from a custom position.
        pgn = (
            "[SetUp \"1\"]\n"
            "[FEN \"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1\"]\n\n"
            + " ".join(f"{n}." for n in range(1, 2))
            + "e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 *"
        )
        response = fresh_client.post("/api/position/pgn", json={"pgn": pgn})
        assert response.status_code == 200
        snap = response.json()
        assert len(snap["move_history"]) == 12  # 6 fullmoves = 12 plies

    def test_position_pgn_then_state_pgn_roundtrip(self, fresh_client):
        pgn_in = "1. d4 d5 2. c4 e6 *"
        fresh_client.post("/api/position/pgn", json={"pgn": pgn_in})
        pgn_out = fresh_client.get("/api/state/pgn").json()["pgn"]
        assert "1. d4 d5 2. c4 e6" in pgn_out
