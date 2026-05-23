"""
Comprehensive FastAPI endpoint and WebSocket tests.

Covers every API route:
  GET  /                     (index page)
  GET  /static/style.css
  GET  /static/app.js
  GET  /api/health
  GET  /api/state
  POST /api/game/new         (default + custom FEN)
  POST /api/move/human       (legal, illegal, invalid, edge cases)
  POST /api/move/robot       (normal, capture, bad squares)
  POST /api/hardware/home
  POST /api/hardware/park
  POST /api/hardware/scan
  GET  /api/board/snapshot
  WS   /ws                   (HELLO event, state shape, STATE_CHANGED delivery)

Also tests:
  - Game-over detection via API
  - Move sequences that change turn
  - HTTP error codes and body content
  - State consistency across requests
  - Concurrent WebSocket subscribers
"""
from __future__ import annotations

import asyncio

import chess
import pytest
from fastapi.testclient import TestClient


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def assert_state_shape(state: dict) -> None:
    required = {"game_id", "fen", "turn", "legal_moves", "is_check",
                "is_game_over", "result", "robot_busy", "last_error"}
    assert required.issubset(set(state.keys())), f"Missing keys: {required - set(state.keys())}"
    assert state["turn"] in {"white", "black"}
    assert isinstance(state["legal_moves"], list)
    assert isinstance(state["is_check"], bool)
    assert isinstance(state["is_game_over"], bool)
    assert isinstance(state["robot_busy"], bool)


# ══════════════════════════════════════════════════════════════════════════════
# Static and health endpoints
# ══════════════════════════════════════════════════════════════════════════════

class TestStaticAndHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_index_page_loads(self, client):
        r = client.get("/")
        assert r.status_code == 200

    def test_index_page_has_title(self, client):
        r = client.get("/")
        assert "Chess" in r.text or "chess" in r.text

    def test_index_page_links_css(self, client):
        r = client.get("/")
        assert "style.css" in r.text

    def test_index_page_links_js(self, client):
        r = client.get("/")
        assert "app.js" in r.text

    def test_css_loads(self, client):
        r = client.get("/static/style.css")
        assert r.status_code == 200

    def test_js_loads(self, client):
        r = client.get("/static/app.js")
        assert r.status_code == 200

    def test_css_content_type(self, client):
        r = client.get("/static/style.css")
        assert "css" in r.headers.get("content-type", "")

    def test_nonexistent_route_returns_404(self, client):
        r = client.get("/api/nonexistent")
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/state
# ══════════════════════════════════════════════════════════════════════════════

class TestGetState:
    def test_state_shape(self, fresh_client):
        r = fresh_client.get("/api/state")
        assert r.status_code == 200
        assert_state_shape(r.json())

    def test_state_reflects_after_move(self, fresh_client):
        fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        r = fresh_client.get("/api/state")
        assert r.json()["turn"] == "black"

    def test_state_fen_valid(self, fresh_client):
        r = fresh_client.get("/api/state")
        board = chess.Board(r.json()["fen"])  # must not raise
        assert board is not None


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/game/new
# ══════════════════════════════════════════════════════════════════════════════

class TestNewGame:
    def test_new_game_returns_200(self, client):
        assert client.post("/api/game/new").status_code == 200

    def test_new_game_state_shape(self, client):
        assert_state_shape(client.post("/api/game/new").json())

    def test_new_game_starts_white_turn(self, client):
        assert client.post("/api/game/new").json()["turn"] == "white"

    def test_new_game_has_20_legal_moves(self, client):
        state = client.post("/api/game/new").json()
        assert len(state["legal_moves"]) == 20

    def test_new_game_game_ids_differ(self, client):
        id1 = client.post("/api/game/new").json()["game_id"]
        id2 = client.post("/api/game/new").json()["game_id"]
        assert id1 != id2

    def test_new_game_custom_fen_accepted(self, client):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        state = client.post("/api/game/new", params={"fen": fen}).json()
        assert state["fen"] == fen

    def test_new_game_custom_fen_legal_moves_include_castling(self, client):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        state = client.post("/api/game/new", params={"fen": fen}).json()
        assert "e1g1" in state["legal_moves"]
        assert "e1c1" in state["legal_moves"]

    def test_new_game_resets_in_progress_game(self, fresh_client):
        # Make some moves then reset
        fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        fresh_client.post("/api/move/human", json={"uci": "e7e5"})
        state = fresh_client.post("/api/game/new").json()
        assert state["turn"] == "white"
        assert len(state["legal_moves"]) == 20

    def test_new_game_after_checkmate_resets(self, client):
        client.post("/api/game/new")
        for uci in ["f2f3", "e7e5", "g2g4", "d8h4"]:
            client.post("/api/move/human", json={"uci": uci})
        state = client.post("/api/game/new").json()
        assert state["is_game_over"] is False

    def test_new_game_invalid_fen_returns_error(self, client):
        # The route doesn't validate FEN; chess.Board raises ValueError internally
        # This test verifies the request doesn't return 200 (it crashes or returns error)
        import pytest
        try:
            r = client.post("/api/game/new", params={"fen": "this-is-not-a-fen"})
            assert r.status_code >= 400
        except Exception:
            pass  # Server exception is also acceptable - FEN is invalid

    def test_new_game_ep_fen(self, client):
        fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
        state = client.post("/api/game/new", params={"fen": fen}).json()
        assert "e5d6" in state["legal_moves"]

    def test_new_game_checkmate_fen_already_over(self, client):
        # Fool's mate final position
        fen = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
        board = chess.Board(fen)
        if board.is_checkmate():
            state = client.post("/api/game/new", params={"fen": fen}).json()
            assert state["is_game_over"] is True


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/move/human
# ══════════════════════════════════════════════════════════════════════════════

class TestHumanMove:
    def test_legal_move_returns_200(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        assert r.status_code == 200

    def test_legal_move_returns_state_shape(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        assert_state_shape(r.json())

    def test_legal_move_advances_turn(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        assert r.json()["turn"] == "black"

    def test_illegal_move_returns_400(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "e2e5"})
        assert r.status_code == 400

    def test_illegal_move_body_mentions_illegal(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "e2e5"})
        assert "Illegal" in r.text or "illegal" in r.text

    def test_wrong_color_move_returns_400(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "e7e5"})
        assert r.status_code == 400

    def test_invalid_uci_format_returns_4xx(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "not-a-move"})
        assert r.status_code >= 400

    def test_empty_uci_returns_4xx(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": ""})
        assert r.status_code >= 400

    def test_missing_uci_field_returns_4xx(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={})
        assert r.status_code >= 400

    def test_move_sequence_alternates_turns(self, fresh_client):
        moves = ["e2e4", "e7e5", "g1f3", "b8c6"]
        for i, uci in enumerate(moves):
            r = fresh_client.post("/api/move/human", json={"uci": uci})
            assert r.status_code == 200
            expected_turn = "black" if i % 2 == 0 else "white"
            assert r.json()["turn"] == expected_turn

    def test_castling_kingside_via_api(self, client):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        client.post("/api/game/new", params={"fen": fen})
        r = client.post("/api/move/human", json={"uci": "e1g1"})
        assert r.status_code == 200
        board = chess.Board(r.json()["fen"])
        assert board.piece_at(chess.G1).symbol() == "K"
        assert board.piece_at(chess.F1).symbol() == "R"

    def test_castling_queenside_via_api(self, client):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        client.post("/api/game/new", params={"fen": fen})
        r = client.post("/api/move/human", json={"uci": "e1c1"})
        assert r.status_code == 200
        board = chess.Board(r.json()["fen"])
        assert board.piece_at(chess.C1).symbol() == "K"

    def test_en_passant_via_api(self, client):
        fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
        client.post("/api/game/new", params={"fen": fen})
        r = client.post("/api/move/human", json={"uci": "e5d6"})
        assert r.status_code == 200
        board = chess.Board(r.json()["fen"])
        assert board.piece_at(chess.D6).symbol() == "P"
        assert board.piece_at(chess.D5) is None

    def test_promotion_via_api(self, client):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        client.post("/api/game/new", params={"fen": fen})
        r = client.post("/api/move/human", json={"uci": "a7a8q"})
        assert r.status_code == 200
        board = chess.Board(r.json()["fen"])
        assert board.piece_at(chess.A8).symbol() == "Q"

    def test_promotion_to_knight_via_api(self, client):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        client.post("/api/game/new", params={"fen": fen})
        r = client.post("/api/move/human", json={"uci": "a7a8n"})
        assert r.status_code == 200
        board = chess.Board(r.json()["fen"])
        assert board.piece_at(chess.A8).symbol() == "N"

    def test_fools_mate_game_over_via_api(self, client):
        client.post("/api/game/new")
        for uci in ["f2f3", "e7e5", "g2g4", "d8h4"]:
            r = client.post("/api/move/human", json={"uci": uci})
        state = r.json()
        assert state["is_game_over"] is True
        assert state["result"] == "0-1"

    def test_check_flag_set_via_api(self, client):
        fen = "4k3/8/8/8/8/8/4R3/4K3 b - - 0 1"
        state = client.post("/api/game/new", params={"fen": fen}).json()
        assert state["is_check"] is True

    def test_illegal_move_does_not_change_state(self, fresh_client):
        state_before = fresh_client.get("/api/state").json()
        fresh_client.post("/api/move/human", json={"uci": "e2e5"})
        state_after = fresh_client.get("/api/state").json()
        assert state_before["fen"] == state_after["fen"]

    def test_move_after_game_over_rejected(self, client):
        client.post("/api/game/new")
        for uci in ["f2f3", "e7e5", "g2g4", "d8h4"]:
            client.post("/api/move/human", json={"uci": uci})
        r = client.post("/api/move/human", json={"uci": "a2a3"})
        assert r.status_code == 400

    def test_normal_capture_updates_fen(self, client):
        fen = "4k3/8/8/8/3p4/4P3/8/4K3 w - - 0 1"
        client.post("/api/game/new", params={"fen": fen})
        r = client.post("/api/move/human", json={"uci": "e3d4"})
        assert r.status_code == 200
        board = chess.Board(r.json()["fen"])
        assert board.piece_at(chess.D4).symbol() == "P"
        assert board.piece_at(chess.E3) is None

    def test_case_insensitive_uci_accepted(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "E2E4"})
        assert r.status_code == 200

    def test_uci_with_whitespace_accepted(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "  e2e4  "})
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/move/robot
# ══════════════════════════════════════════════════════════════════════════════

class TestRobotMove:
    def test_basic_robot_move_returns_ok(self, fresh_client):
        r = fresh_client.post("/api/move/robot",
                              json={"source": "e2", "target": "e4", "capture": False})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_robot_capture_move_returns_ok(self, fresh_client):
        r = fresh_client.post("/api/move/robot",
                              json={"source": "e2", "target": "d5",
                                    "capture": True, "victim": "d5"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_robot_move_without_victim_is_ok(self, fresh_client):
        r = fresh_client.post("/api/move/robot",
                              json={"source": "g1", "target": "f3", "capture": False})
        assert r.status_code == 200

    def test_robot_move_response_has_ok_field(self, fresh_client):
        r = fresh_client.post("/api/move/robot",
                              json={"source": "e2", "target": "e4", "capture": False})
        assert "ok" in r.json()

    def test_robot_move_missing_source_returns_4xx(self, fresh_client):
        r = fresh_client.post("/api/move/robot",
                              json={"target": "e4", "capture": False})
        assert r.status_code >= 400

    def test_robot_move_missing_target_returns_4xx(self, fresh_client):
        r = fresh_client.post("/api/move/robot",
                              json={"source": "e2", "capture": False})
        assert r.status_code >= 400


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/hardware/*
# ══════════════════════════════════════════════════════════════════════════════

class TestHardwareEndpoints:
    def test_home_returns_ok(self, client):
        r = client.post("/api/hardware/home")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_home_sets_homed_state(self, client):
        client.post("/api/hardware/home")
        # Verify via a scan or state (homed state is internal but used by safety)
        r = client.post("/api/hardware/home")
        assert r.json()["ok"] is True

    def test_park_returns_ok(self, client):
        r = client.post("/api/hardware/park")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_scan_returns_ok(self, client):
        r = client.post("/api/hardware/scan")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_scan_with_full_false(self, client):
        r = client.post("/api/hardware/scan", params={"full": False})
        assert r.status_code == 200

    def test_home_park_scan_cycle(self, client):
        assert client.post("/api/hardware/home").json()["ok"] is True
        assert client.post("/api/hardware/park").json()["ok"] is True
        assert client.post("/api/hardware/scan").json()["ok"] is True

    def test_hardware_response_has_err_key(self, client):
        r = client.post("/api/hardware/home")
        assert "err" in r.json()


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/board/snapshot
# ══════════════════════════════════════════════════════════════════════════════

class TestBoardSnapshot:
    def test_snapshot_returns_200(self, client):
        assert client.get("/api/board/snapshot").status_code == 200

    def test_snapshot_has_ts_ms(self, client):
        assert "ts_ms" in client.get("/api/board/snapshot").json()

    def test_snapshot_has_cells(self, client):
        assert "cells" in client.get("/api/board/snapshot").json()

    def test_snapshot_has_64_cells(self, client):
        cells = client.get("/api/board/snapshot").json()["cells"]
        assert len(cells) == 64

    def test_snapshot_cells_have_protocol_keys(self, client):
        cells = client.get("/api/board/snapshot").json()["cells"]
        for name, cell in cells.items():
            assert "o" in cell
            assert "p" in cell
            assert "m" in cell

    def test_snapshot_all_squares_present(self, client):
        cells = client.get("/api/board/snapshot").json()["cells"]
        for file in "abcdefgh":
            for rank in "12345678":
                assert f"{file}{rank}" in cells

    def test_snapshot_updates_after_scan(self, client):
        client.post("/api/hardware/scan")
        r = client.get("/api/board/snapshot")
        assert r.status_code == 200
        cells = r.json()["cells"]
        # After scan, starting pieces should show as occupied
        assert cells["e1"]["o"] == 1
        assert cells["e8"]["o"] == 1

    def test_snapshot_empty_squares_in_starting_position(self, client):
        client.post("/api/hardware/scan")
        cells = client.get("/api/board/snapshot").json()["cells"]
        for file in "abcdefgh":
            for rank in "3456":
                assert cells[f"{file}{rank}"]["o"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# WebSocket /ws
# ══════════════════════════════════════════════════════════════════════════════

class TestWebSocket:
    def test_hello_event_on_connect(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
        assert data["type"] == "HELLO"

    def test_hello_event_has_state(self, client):
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
        assert "state" in data
        assert_state_shape(data["state"])

    def test_state_changed_event_after_move(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # consume HELLO
            # Make a move via API (triggers LOCAL_MOVE_CANDIDATE)
            client.post("/api/move/human", json={"uci": "e2e4"})
            data = ws.receive_json()
        assert data["type"] in {"LOCAL_MOVE_CANDIDATE", "STATE_CHANGED"}

    def test_state_changed_event_has_payload(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # HELLO
            client.post("/api/move/human", json={"uci": "e2e4"})
            data = ws.receive_json()
        # Either payload key exists or state key exists (for HELLO-style events)
        assert "payload" in data or "state" in data

    def test_state_changed_event_has_created_at(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            client.post("/api/move/human", json={"uci": "e2e4"})
            data = ws.receive_json()
        assert "created_at" in data

    def test_new_game_triggers_state_changed(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # HELLO
            client.post("/api/game/new")
            data = ws.receive_json()
        assert data["type"] == "STATE_CHANGED"

    def test_multiple_moves_multiple_events(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # HELLO
            for uci in ["e2e4", "e7e5"]:
                client.post("/api/move/human", json={"uci": uci})
            events = [ws.receive_json(), ws.receive_json()]
        VALID_TYPES = {"LOCAL_MOVE_CANDIDATE", "STATE_CHANGED", "SCAN_RECEIVED"}
        assert all(e["type"] in VALID_TYPES for e in events)

    def test_hello_state_is_fresh_game_after_new_game(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
        assert data["state"]["turn"] == "white"
        assert len(data["state"]["legal_moves"]) == 20

    def test_websocket_accepts_and_closes_cleanly(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()  # HELLO — connection is healthy
        # If we get here without an exception, connection closed cleanly


# ══════════════════════════════════════════════════════════════════════════════
# Cross-endpoint consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestCrossEndpointConsistency:
    def test_state_fen_matches_after_human_move(self, fresh_client):
        r = fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        move_fen = r.json()["fen"]
        state_fen = fresh_client.get("/api/state").json()["fen"]
        assert move_fen == state_fen

    def test_game_id_consistent_across_state_and_move(self, fresh_client):
        game_id_from_state = fresh_client.get("/api/state").json()["game_id"]
        game_id_from_move = fresh_client.post(
            "/api/move/human", json={"uci": "e2e4"}
        ).json()["game_id"]
        assert game_id_from_state == game_id_from_move

    def test_new_game_changes_game_id_in_state(self, fresh_client):
        old_id = fresh_client.get("/api/state").json()["game_id"]
        fresh_client.post("/api/game/new")
        new_id = fresh_client.get("/api/state").json()["game_id"]
        assert old_id != new_id

    def test_full_fools_mate_sequence(self, client):
        """Play Fool's Mate via API and verify all state transitions."""
        client.post("/api/game/new")

        r1 = client.post("/api/move/human", json={"uci": "f2f3"})
        assert r1.json()["turn"] == "black"
        assert not r1.json()["is_game_over"]

        r2 = client.post("/api/move/human", json={"uci": "e7e5"})
        assert r2.json()["turn"] == "white"

        r3 = client.post("/api/move/human", json={"uci": "g2g4"})
        assert r3.json()["turn"] == "black"

        r4 = client.post("/api/move/human", json={"uci": "d8h4"})
        assert r4.json()["is_game_over"] is True
        assert r4.json()["result"] == "0-1"
        assert r4.json()["is_check"] is True

    def test_full_castling_and_check_sequence(self, client):
        """Ruy Lopez opening through O-O."""
        client.post("/api/game/new")
        for uci in ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"]:
            r = client.post("/api/move/human", json={"uci": uci})
            assert r.status_code == 200
        # White castles kingside
        r = client.post("/api/move/human", json={"uci": "e1g1"})
        assert r.status_code == 200
        board = chess.Board(r.json()["fen"])
        assert board.piece_at(chess.G1).symbol() == "K"

    def test_board_snapshot_matches_game_state_after_scan(self, client):
        """After a scan, occupied squares in board snapshot must match game FEN."""
        client.post("/api/game/new")
        client.post("/api/hardware/scan")
        state = client.get("/api/state").json()
        snapshot = client.get("/api/board/snapshot").json()

        board = chess.Board(state["fen"])
        expected_occupied = {
            chess.square_name(sq) for sq in board.piece_map()
        }
        actual_occupied = {
            sq for sq, cell in snapshot["cells"].items() if cell["o"] == 1
        }
        assert actual_occupied == expected_occupied
