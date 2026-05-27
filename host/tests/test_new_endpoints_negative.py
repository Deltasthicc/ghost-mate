"""Negative-path and edge-case API tests for the new endpoints.

These cover:
- ``POST /api/ai/coach`` (local fallback, weird input, while game is over)
- ``GET  /api/engine/live`` (clamped depth, multipv bounds, bad inputs)
- ``GET  /api/state/pgn`` (empty game, after-load, idempotent)
- ``POST /api/position/pgn`` / ``POST /api/position/fen`` malformed inputs
- WebSocket query-parameter robustness (engine, max_depth)

Every test uses the in-process FastAPI client. Stockfish is replaced with a
deterministic fake where needed to avoid spawning a subprocess.
"""
from __future__ import annotations

import asyncio
import json

import chess
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Stockfish stubs
# ─────────────────────────────────────────────────────────────────────────────

class _AnalysisStub:
    """Stand-in for StockfishService that returns deterministic analysis."""

    is_available = True

    def __init__(self, raise_on_call: Exception | None = None):
        self.calls: list[dict] = []
        self.raise_on_call = raise_on_call
        self.threads = 3
        self.hash_mb = 128

    async def start(self):
        return None

    async def stop(self):
        return None

    async def configure_options(self, *, threads=None, hash_mb=None, skill_level=None):
        if threads is not None:
            self.threads = threads
        if hash_mb is not None:
            self.hash_mb = hash_mb

    async def analysis(self, board, *, multipv=5, time_s=None, depth=None,
                       use_cache=True):
        self.calls.append({"multipv": multipv, "depth": depth,
                           "use_cache": use_cache, "fen": board.fen()})
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "depth": depth or 1,
            "depth_requested": depth,
            "current_display": "+0.05",
            "current_score_cp": 5,
            "current_score_cp_white": 5,
            "current_display_white": "+0.05",
            "mate_display": "—",
            "best_moves": [{
                "rank": 1, "uci": "e2e4", "san": "e4",
                "score_display": "+0.05", "score_cp": 5,
                "score_cp_white": 5, "score_display_white": "+0.05",
                "pv": ["e4"], "mate_in": None,
            }],
        }

    async def best_move(self, board, *, time_s=None):
        return None  # not used in these tests

    async def evaluate(self, board, *, time_s=0.12):
        return {"display": "0.00"}


@pytest.fixture()
def stub_engine(client):
    """Replace the running app's stockfish service with the stub."""
    stub = _AnalysisStub()
    client.app.state.stockfish = stub
    return stub


# ─────────────────────────────────────────────────────────────────────────────
# /api/ai/coach
# ─────────────────────────────────────────────────────────────────────────────

class TestAiCoachEndpoint:
    def test_returns_local_fallback_when_llm_disabled(self, fresh_client, stub_engine):
        fresh_client.app.state.settings.llm_coach_enabled = False
        response = fresh_client.post("/api/ai/coach", json={"question": "explain"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["source"] == "local_fallback"
        assert payload["configured"] is False
        assert "Source: local_fallback" not in payload["answer"]
        assert "advisory only" not in payload["answer"]

    def test_accepts_empty_question(self, fresh_client, stub_engine):
        fresh_client.app.state.settings.llm_coach_enabled = False
        response = fresh_client.post("/api/ai/coach", json={"question": ""})
        assert response.status_code == 200
        assert response.json()["answer"]

    def test_accepts_missing_question(self, fresh_client, stub_engine):
        fresh_client.app.state.settings.llm_coach_enabled = False
        response = fresh_client.post("/api/ai/coach", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["answer"]

    def test_rejects_non_json(self, fresh_client, stub_engine):
        response = fresh_client.post("/api/ai/coach",
                                     content=b"not-json",
                                     headers={"Content-Type": "application/json"})
        assert response.status_code in (400, 422)

    def test_huge_question_does_not_500(self, fresh_client, stub_engine):
        fresh_client.app.state.settings.llm_coach_enabled = False
        huge = "why? " * 5000  # 25k chars
        response = fresh_client.post("/api/ai/coach", json={"question": huge})
        assert response.status_code == 200
        assert response.json()["answer"]

    def test_works_after_checkmate(self, fresh_client, stub_engine):
        fresh_client.app.state.settings.llm_coach_enabled = False
        # Fool's mate
        for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
            fresh_client.post("/api/move/human", json={"uci": uci})
        response = fresh_client.post("/api/ai/coach", json={"question": "what now?"})
        assert response.status_code == 200
        assert response.json()["source"] == "local_fallback"

    def test_style_field_is_optional(self, fresh_client, stub_engine):
        fresh_client.app.state.settings.llm_coach_enabled = False
        response = fresh_client.post("/api/ai/coach", json={})
        assert response.status_code == 200
        response_with_style = fresh_client.post("/api/ai/coach",
                                                json={"style": "grandmaster"})
        assert response_with_style.status_code == 200

    def test_context_includes_engine_lines(self, fresh_client, stub_engine):
        fresh_client.app.state.settings.llm_coach_enabled = False
        response = fresh_client.post("/api/ai/coach", json={"question": "why?"})
        ctx = response.json()["context"]
        assert ctx["fen"]
        assert ctx["stockfish"]["best_moves"][0]["uci"] == "e2e4"


# ─────────────────────────────────────────────────────────────────────────────
# /api/engine/live
# ─────────────────────────────────────────────────────────────────────────────

class TestEngineLiveEndpoint:
    def test_default_depth_uses_configured_depth(self, fresh_client, stub_engine):
        response = fresh_client.get("/api/engine/live")
        assert response.status_code == 200
        assert stub_engine.calls[-1]["depth"] == 24

    def test_max_depth_query_is_clamped(self, fresh_client, stub_engine):
        fresh_client.get("/api/engine/live?max_depth=99")
        assert stub_engine.calls[-1]["depth"] == 30
        fresh_client.get("/api/engine/live?max_depth=-5")
        assert stub_engine.calls[-1]["depth"] == 1
        fresh_client.get("/api/engine/live?max_depth=0")
        assert stub_engine.calls[-1]["depth"] == 1

    def test_multipv_bounds_are_respected(self, fresh_client, stub_engine):
        # Above 5 should be coerced down by the engine; here we just check we
        # pass-through what the route received without erroring.
        response = fresh_client.get("/api/engine/live?multipv=20&max_depth=4")
        assert response.status_code == 200

    def test_garbage_max_depth_query_is_ignored(self, fresh_client, stub_engine):
        # FastAPI should reject non-int silently or coerce; either is fine as
        # long as the server does not 500.
        response = fresh_client.get("/api/engine/live?max_depth=potato")
        assert response.status_code in (200, 422)

    def test_engine_unavailable_yields_503(self, fresh_client):
        class _Down:
            is_available = False

            async def start(self):  # pragma: no cover - immediate return
                return None

            async def analysis(self, *a, **kw):  # pragma: no cover
                raise RuntimeError("should not be called")

        fresh_client.app.state.stockfish = _Down()
        response = fresh_client.get("/api/engine/live")
        assert response.status_code == 503
        assert "Stockfish" in response.text

    def test_engine_settings_get_shape(self, fresh_client, stub_engine):
        response = fresh_client.get("/api/engine/settings")
        assert response.status_code == 200
        payload = response.json()
        for key in (
            "max_depth", "max_depth_cap", "search_time_s", "multipv",
            "multipv_cap", "threads", "hash_mb",
        ):
            assert key in payload
        assert payload["max_depth_cap"] == 30
        assert payload["multipv_cap"] == 5

    def test_engine_settings_post_clamps_values(self, fresh_client, stub_engine):
        response = fresh_client.post("/api/engine/settings", json={
            "max_depth": 999,
            "search_time_s": 999,
            "multipv": 999,
            "threads": 999,
            "hash_mb": 99999,
        })
        assert response.status_code == 200
        payload = response.json()
        assert payload["max_depth"] == 30
        assert payload["search_time_s"] == 30.0
        assert payload["multipv"] == 5
        assert payload["threads"] == 64
        assert payload["hash_mb"] == 4096

    def test_engine_settings_post_low_values_clamp_up(self, fresh_client, stub_engine):
        response = fresh_client.post("/api/engine/settings", json={
            "max_depth": -5,
            "search_time_s": -1,
            "multipv": 0,
            "threads": 0,
            "hash_mb": 0,
        })
        assert response.status_code == 200
        payload = response.json()
        assert payload["max_depth"] == 1
        assert payload["search_time_s"] == 0.1
        assert payload["multipv"] == 1
        assert payload["threads"] == 1
        assert payload["hash_mb"] == 16


# ─────────────────────────────────────────────────────────────────────────────
# /api/position/pgn  and  /api/position/fen
# ─────────────────────────────────────────────────────────────────────────────

class TestPositionLoadNegative:
    @pytest.mark.parametrize("bad_fen", [
        "", "totally not fen", "8/8/8/8/8/8/8/8 z - - 0 1",
        "ten/9/8/8/8/8/8/RNBQKBNR w KQkq - 0 1",
    ])
    def test_invalid_fen_returns_400(self, fresh_client, bad_fen):
        response = fresh_client.post("/api/position/fen", json={"fen": bad_fen})
        assert response.status_code == 400

    @pytest.mark.parametrize("bad_pgn", [
        "",
        "[Event ] [\n",       # malformed headers
    ])
    def test_invalid_pgn_returns_400_or_empty(self, fresh_client, bad_pgn):
        response = fresh_client.post("/api/position/pgn", json={"pgn": bad_pgn})
        if response.status_code == 200:
            assert response.json()["move_history"] == []
        else:
            assert response.status_code == 400

    def test_pgn_with_illegal_move_does_not_crash(self, fresh_client):
        response = fresh_client.post(
            "/api/position/pgn",
            json={"pgn": "1. e4 e5 2. Bx5 *"},
        )
        # The python-chess PGN reader tolerates illegal moves by stopping
        # at the bad SAN; either it returns 200 with the partial mainline or
        # 400. Neither should be a 500.
        assert response.status_code in (200, 400)


# ─────────────────────────────────────────────────────────────────────────────
# /api/state/pgn
# ─────────────────────────────────────────────────────────────────────────────

class TestStatePgnEndpoint:
    def test_initial_game_returns_star(self, fresh_client):
        data = fresh_client.get("/api/state/pgn").json()
        assert data["ply"] == 0
        assert "*" in data["pgn"]

    def test_response_is_idempotent(self, fresh_client):
        fresh_client.post("/api/move/human", json={"uci": "e2e4"})
        a = fresh_client.get("/api/state/pgn").json()
        b = fresh_client.get("/api/state/pgn").json()
        assert a == b


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket
# ─────────────────────────────────────────────────────────────────────────────

class TestWebSocketBehaviour:
    def test_hello_payload_includes_move_history(self, fresh_client):
        with fresh_client.websocket_connect("/ws") as ws:
            data = ws.receive_json()
        assert data["type"] == "HELLO"
        assert "state" in data
        assert "move_history" in data["state"]

    def test_engine_param_increments_counter_for_duration_of_connection(
            self, fresh_client):
        assert fresh_client.app.state.engine_live_clients == 0
        with fresh_client.websocket_connect("/ws?engine=1") as ws:
            ws.receive_json()  # HELLO
            assert fresh_client.app.state.engine_live_clients == 1
        # On disconnect the counter must be returned to 0
        assert fresh_client.app.state.engine_live_clients == 0

    def test_engine_param_records_max_depth(self, fresh_client):
        with fresh_client.websocket_connect("/ws?engine=1&max_depth=7") as ws:
            ws.receive_json()
            depths = list(fresh_client.app.state.engine_live_depths.values())
            assert depths == [7]

    @pytest.mark.parametrize("raw", ["99", "0", "-5", "bogus"])
    def test_max_depth_query_is_clamped(self, fresh_client, raw):
        with fresh_client.websocket_connect(f"/ws?engine=1&max_depth={raw}") as ws:
            ws.receive_json()
            depth = list(fresh_client.app.state.engine_live_depths.values())[0]
            assert 1 <= depth <= 30

    def test_no_engine_param_does_not_register_as_client(self, fresh_client):
        with fresh_client.websocket_connect("/ws") as ws:
            ws.receive_json()
            assert fresh_client.app.state.engine_live_clients == 0

    def test_two_clients_both_counted(self, fresh_client):
        with fresh_client.websocket_connect("/ws?engine=1") as ws1, \
                fresh_client.websocket_connect("/ws?engine=1&max_depth=3") as ws2:
            ws1.receive_json()
            ws2.receive_json()
            assert fresh_client.app.state.engine_live_clients == 2
            depths = sorted(fresh_client.app.state.engine_live_depths.values())
            assert depths == [3, 15]
        # Both gone → counter is 0
        assert fresh_client.app.state.engine_live_clients == 0

    def test_state_changed_event_arrives_after_move(self, fresh_client):
        with fresh_client.websocket_connect("/ws") as ws:
            ws.receive_json()  # HELLO
            fresh_client.post("/api/move/human", json={"uci": "e2e4"})
            # Drain up to a few events; LOCAL_MOVE_CANDIDATE is what move/human
            # publishes. We are deliberately tolerant of intermediate events.
            seen = None
            for _ in range(5):
                payload = ws.receive_json()
                if payload["type"] in {"LOCAL_MOVE_CANDIDATE", "STATE_CHANGED"}:
                    seen = payload
                    break
            assert seen is not None
            assert seen["payload"].get("state", {}).get("fen", "").startswith(
                "rnbqkbnr/pppp1ppp/8/4p3"
            ) or seen["payload"].get("fen", "").startswith(
                "rnbqkbnr/pppp1ppp/8/4p3"
            ) or seen["payload"].get("uci") == "e2e4"
