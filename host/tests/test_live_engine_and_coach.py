from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from host.app.ai.coach import build_coach_context, rule_based_coach
from host.app.api.routes import _cap_engine_depth
from host.app.api.ws import _cap_engine_depth as _cap_ws_depth
from host.app.domain.events import EventBus, EventType
from host.app.domain.game_state import GameState
from host.app.main import app, publish_live_engine_updates


class _Settings:
    engine_live_push_enabled = True
    engine_live_interval_s = 0.01
    engine_live_multipv = 1
    engine_live_max_depth = 3
    engine_live_search_time_s = 0.1

    @property
    def capped_engine_live_max_depth(self) -> int:
        return min(30, max(1, self.engine_live_max_depth))


class _FakeStockfish:
    def __init__(self) -> None:
        self.depths: list[int] = []
        self.threads = 1
        self.hash_mb = 128

    async def analysis(self, board, *, multipv, depth, use_cache, time_s=None):
        self.depths.append(depth)
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn else "black",
            "current_display": "+0.10",
            "depth": depth,
            "elapsed_ms": depth * 10,
            "best_moves": [
                {
                    "rank": 1,
                    "uci": "e2e4",
                    "san": "e4",
                    "score_display": "+0.10",
                    "pv": ["e4", "e5"],
                }
            ],
        }


def test_engine_depth_clamps_negative_invalid_and_over_cap():
    assert _cap_engine_depth(-5) == 1
    assert _cap_engine_depth(None, fallback=7) == 7
    assert _cap_engine_depth(99) == 30
    assert _cap_ws_depth("bad") == 15
    assert _cap_ws_depth("0") == 1
    assert _cap_ws_depth("20") == 20


@pytest.mark.asyncio
async def test_live_engine_publisher_walks_depths_and_marks_final():
    events = EventBus(default_max=10)
    queue = await events.subscribe()
    fake = _FakeStockfish()
    fake_app = SimpleNamespace(
        state=SimpleNamespace(
            settings=_Settings(),
            events=events,
            game=GameState(),
            stockfish=fake,
            engine_live_clients=1,
            engine_live_depths={1: 3},
        )
    )

    task = asyncio.create_task(publish_live_engine_updates(fake_app))
    try:
        received = []
        for _ in range(3):
            event = await asyncio.wait_for(queue.get(), timeout=1.0)
            assert event.type == EventType.ENGINE_UPDATE
            received.append(event.payload["analysis"])
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert [item["depth_requested"] for item in received] == [1, 2, 3]
    assert received[-1]["is_final_depth"] is True
    assert received[-1]["max_depth"] == 3
    assert fake.depths == [1, 2, 3]


def test_engine_live_endpoint_uses_capped_depth(monkeypatch):
    class FakeRouteStockfish:
        is_available = True
        threads = 1
        hash_mb = 128

        async def start(self):
            return None

        async def analysis(self, board, *, multipv, time_s=None, depth=None, use_cache=True):
            return {
                "fen": board.fen(),
                "turn": "white",
                "current_display": "0.00",
                "depth": depth,
                "depth_requested": depth,
                "best_moves": [],
            }

    with TestClient(app) as client:
        client.app.state.stockfish = FakeRouteStockfish()
        response = client.get("/api/engine/live?multipv=2&max_depth=99")

    assert response.status_code == 200
    assert response.json()["depth_requested"] == 30


def test_coach_context_and_fallback_teach_without_boilerplate():
    snapshot = GameState().snapshot()
    analysis = {
        "current_display": "+0.20",
        "depth": 5,
        "best_moves": [
            {"rank": 1, "uci": "e2e4", "san": "e4", "score_display": "+0.20", "pv": ["e4", "e5"]}
        ],
    }
    context = build_coach_context(snapshot, analysis)
    answer = rule_based_coach(context, "Why is this move good?")

    assert context["fen"] == snapshot["fen"]
    assert context["stockfish"]["best_moves"][0]["uci"] == "e2e4"
    assert context["position_features"]["phase"] == "opening"
    assert "Best move" in answer
    assert "e4" in answer
    forbidden = [
        "advisory only",
        "tactical anchor",
        "physical move",
        "robot commands",
        "Source: local_fallback",
    ]
    for phrase in forbidden:
        assert phrase not in answer, f"Coach output should not contain '{phrase}'"


def test_ai_coach_endpoint_returns_local_fallback(monkeypatch):
    class FakeRouteStockfish:
        async def analysis(self, board, *, multipv, depth, use_cache):
            return {
                "fen": board.fen(),
                "turn": "white",
                "current_display": "+0.15",
                "depth": depth,
                "best_moves": [
                    {"rank": 1, "uci": "e2e4", "san": "e4", "score_display": "+0.15", "pv": ["e4"]}
                ],
            }

    with TestClient(app) as client:
        client.app.state.stockfish = FakeRouteStockfish()
        client.app.state.settings.llm_coach_enabled = False
        response = client.post("/api/ai/coach", json={"question": "Teach me this position"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "local_fallback"
    assert payload["configured"] is False
    assert "Stockfish" in payload["answer"]
    assert "advisory only" not in payload["answer"]
    assert "Source: local_fallback" not in payload["answer"]


def test_game_state_tracks_move_history_and_pgn():
    game = GameState()
    game.new_game()
    game.push_uci("e2e4")
    game.push_uci("e7e5")
    game.push_uci("g1f3")

    snapshot = game.snapshot()
    history = snapshot["move_history"]
    assert len(history) == 3
    assert [entry["san"] for entry in history] == ["e4", "e5", "Nf3"]
    assert history[0]["move_number"] == 1
    assert history[0]["color"] == "white"
    assert history[1]["color"] == "black"
    assert history[2]["move_number"] == 2

    pgn_text = game.pgn()
    assert "1. e4 e5 2. Nf3" in pgn_text
    assert "[Event \"GhostMate Session\"]" in pgn_text


def test_state_pgn_endpoint_returns_serialised_game():
    with TestClient(app) as client:
        client.post("/api/game/new")
        for move in ("e2e4", "c7c5", "g1f3"):
            assert client.post("/api/move/human", json={"uci": move}).status_code == 200
        response = client.get("/api/state/pgn")

    assert response.status_code == 200
    payload = response.json()
    assert "1. e4 c5 2. Nf3" in payload["pgn"]
    assert payload["ply"] == 3
    assert payload["start_fen"].startswith("rnbqkbnr/pppppppp")


def test_load_pgn_preserves_move_history():
    pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 *"
    with TestClient(app) as client:
        load = client.post("/api/position/pgn", json={"pgn": pgn})
        assert load.status_code == 200
        snapshot = load.json()
        history = snapshot["move_history"]
        assert [entry["san"] for entry in history] == ["e4", "e5", "Nf3", "Nc6", "Bb5"]

        pgn_export = client.get("/api/state/pgn").json()["pgn"]
        assert "1. e4 e5 2. Nf3 Nc6 3. Bb5" in pgn_export
