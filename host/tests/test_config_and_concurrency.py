"""Config edge-cases plus a small concurrency stress harness.

Covers:
- Settings field defaults, env aliases, derived properties
- ``capped_engine_live_max_depth`` clamping over a wide range of inputs
- ``sqlite_path`` derivation
- A concurrency stress check: 50 parallel HTTP requests must not deadlock or
  corrupt the in-memory game state, and the response set must be coherent.
- Repeated new-game cycles never leak engine_live state.
"""
from __future__ import annotations

import asyncio
import concurrent.futures as futures

import chess
import pytest

from host.app.config import Settings


# ─────────────────────────────────────────────────────────────────────────────
# Settings
# ─────────────────────────────────────────────────────────────────────────────

class TestSettings:
    def test_default_values_safe(self):
        s = Settings(_env_file=None)
        assert s.serial_baud == 115200
        assert s.serial_mock is True
        assert s.engine_live_max_depth == 15
        assert s.llm_coach_enabled is False
        assert 1 <= s.engine_live_multipv <= 5

    @pytest.mark.parametrize("raw,expected", [
        (-99, 1), (-1, 1), (0, 1), (1, 1),
        (7, 7), (14, 14), (15, 15), (16, 15), (1000, 15),
    ])
    def test_capped_engine_live_max_depth(self, raw, expected):
        s = Settings(_env_file=None)
        s.engine_live_max_depth = raw
        assert s.capped_engine_live_max_depth == expected

    def test_sqlite_path_for_sqlite_url(self):
        s = Settings(_env_file=None, database_url="sqlite:///data/db/foo.db")
        assert s.sqlite_path is not None
        assert s.sqlite_path.name == "foo.db"

    def test_sqlite_path_none_for_other_drivers(self):
        s = Settings(_env_file=None,
                     database_url="postgresql://user:pw@localhost/x")
        assert s.sqlite_path is None

    def test_llm_settings_use_alias(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
        s = Settings(_env_file=None)
        assert s.llm_api_key == "sk-from-env"

    def test_debug_alias(self, monkeypatch):
        monkeypatch.setenv("APP_DEBUG", "true")
        s = Settings(_env_file=None)
        assert s.debug is True


# ─────────────────────────────────────────────────────────────────────────────
# In-memory game concurrency
# ─────────────────────────────────────────────────────────────────────────────

class TestConcurrentApi:
    def test_many_state_reads_are_safe(self, fresh_client):
        # 50 parallel /api/state reads must all return the same FEN.
        def fetch():
            return fresh_client.get("/api/state").json()["fen"]

        with futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: fetch(), range(50)))
        assert all(r == results[0] for r in results)

    def test_sequential_moves_then_concurrent_reads(self, fresh_client):
        for uci in ("e2e4", "e7e5", "g1f3"):
            fresh_client.post("/api/move/human", json={"uci": uci})
        expected = fresh_client.get("/api/state").json()["fen"]
        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(
                lambda _: fresh_client.get("/api/state/pgn").json()["pgn"],
                range(20),
            ))
        assert all("1. e4 e5 2. Nf3" in o for o in outcomes)
        assert all(fresh_client.get("/api/state").json()["fen"] == expected
                   for _ in range(5))

    def test_invalid_moves_in_burst_do_not_corrupt_state(self, fresh_client):
        before = fresh_client.get("/api/state").json()["fen"]
        with futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(
                lambda _: fresh_client.post("/api/move/human",
                                            json={"uci": "z9z9"}),
                range(30),
            ))
        after = fresh_client.get("/api/state").json()["fen"]
        assert before == after

    def test_engine_live_state_leak_across_new_games(self, fresh_client):
        # Repeated /api/game/new must not change engine_live counters.
        for _ in range(5):
            fresh_client.post("/api/game/new")
        assert fresh_client.app.state.engine_live_clients == 0
        assert fresh_client.app.state.engine_live_depths == {}

    def test_ws_open_close_cycle_keeps_counter_at_zero(self, fresh_client):
        for _ in range(3):
            with fresh_client.websocket_connect("/ws?engine=1") as ws:
                ws.receive_json()  # HELLO
            assert fresh_client.app.state.engine_live_clients == 0
            assert fresh_client.app.state.engine_live_depths == {}


# ─────────────────────────────────────────────────────────────────────────────
# Re-export sanity: every public symbol still importable
# ─────────────────────────────────────────────────────────────────────────────

class TestPublicExports:
    def test_coach_module_exports_core_symbols(self):
        from host.app.ai import coach as mod
        for name in ("build_coach_context", "rule_based_coach", "LlmCoach"):
            assert hasattr(mod, name)

    def test_game_state_exports_history_and_pgn(self):
        from host.app.domain import game_state as mod
        assert hasattr(mod.GameState, "move_history")
        assert hasattr(mod.GameState, "pgn")
        assert hasattr(mod.GameState, "load_pgn_game")

    def test_routes_export_new_endpoints(self):
        from host.app.api import routes as mod
        names = {r.path for r in mod.router.routes}
        assert "/state/pgn" in names
        assert "/ai/coach" in names
        assert "/engine/live" in names
        assert "/position/pgn" in names
        assert "/position/fen" in names
