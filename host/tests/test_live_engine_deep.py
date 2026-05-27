"""Deep tests for the depth-driven live engine update loop.

These cover the publisher coroutine in ``host.app.main`` and the WebSocket
endpoint behaviour around client counting and max-depth negotiation.

The Stockfish process is replaced by a deterministic in-memory fake so the
tests are fast and reproducible.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import chess
import pytest

from host.app.api.ws import _cap_engine_depth as _cap_ws_depth
from host.app.api.routes import _cap_engine_depth as _cap_route_depth
from host.app.domain.events import EventBus, EventType
from host.app.domain.game_state import GameState
from host.app.main import publish_live_engine_updates


class _Settings:
    """Minimal settings stub matching what publish_live_engine_updates reads."""
    def __init__(self, max_depth: int = 3, enabled: bool = True,
                 interval_s: float = 0.01, multipv: int = 1):
        self.engine_live_push_enabled = enabled
        self.engine_live_interval_s = interval_s
        self.engine_live_multipv = multipv
        self.engine_live_max_depth = max_depth
        self.engine_live_search_time_s = 0.1

    @property
    def capped_engine_live_max_depth(self) -> int:
        return max(1, min(30, int(self.engine_live_max_depth)))


class _FakeStockfish:
    def __init__(self, raise_on_depth: int | None = None,
                 raise_count: int = 0):
        self.calls: list[tuple[str, int]] = []
        self.raise_on_depth = raise_on_depth
        self.raise_count = raise_count
        self.threads = 1
        self.hash_mb = 128

    async def analysis(self, board, *, multipv, depth, use_cache, time_s=None):
        self.calls.append((board.fen(), depth))
        if self.raise_count > 0 and depth == self.raise_on_depth:
            self.raise_count -= 1
            raise RuntimeError("simulated stockfish hiccup")
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn else "black",
            "current_display": "+0.10",
            "depth": depth,
            "elapsed_ms": depth * 10,
            "best_moves": [{
                "rank": 1, "uci": "e2e4", "san": "e4",
                "score_display": "+0.10", "pv": ["e4", "e5"],
            }],
        }


def _make_app(stockfish, *, game=None, settings=None,
              clients: int = 1, requested_depths: dict | None = None):
    """Build a fake app object the publisher coroutine can read from."""
    return SimpleNamespace(state=SimpleNamespace(
        settings=settings or _Settings(),
        events=EventBus(default_max=64),
        game=game or GameState(),
        stockfish=stockfish,
        engine_live_clients=clients,
        engine_live_depths=requested_depths or {},
    ))


# ─────────────────────────────────────────────────────────────────────────────
# _cap_engine_depth helpers (route + ws)
# ─────────────────────────────────────────────────────────────────────────────

class TestCapEngineDepth:
    @pytest.mark.parametrize("value,expected", [
        (None, 15),
        (0, 1),
        (1, 1),
        (8, 8),
        (15, 15),
        (16, 16),
        (30, 30),
        (-99, 1),
        (99, 30),
    ])
    def test_route_cap(self, value, expected):
        assert _cap_route_depth(value) == expected

    @pytest.mark.parametrize("raw,expected", [
        (None, 15),
        ("0", 1),
        ("8", 8),
        ("15", 15),
        ("30", 30),
        ("99", 30),
        ("not a number", 15),
        ("", 15),
    ])
    def test_ws_cap(self, raw, expected):
        assert _cap_ws_depth(raw) == expected

    def test_route_cap_with_custom_fallback(self):
        assert _cap_route_depth(None, fallback=4) == 4
        assert _cap_route_depth(None, fallback=99) == 30  # fallback also clamped


# ─────────────────────────────────────────────────────────────────────────────
# Publisher behaviour
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestLiveEnginePublisher:
    async def _drain(self, queue, n, timeout=1.0):
        out = []
        for _ in range(n):
            ev = await asyncio.wait_for(queue.get(), timeout=timeout)
            out.append(ev)
        return out

    async def test_walks_depth_1_to_n_and_marks_final(self):
        fake = _FakeStockfish()
        app = _make_app(fake, requested_depths={"a": 3})
        queue = await app.state.events.subscribe()

        task = asyncio.create_task(publish_live_engine_updates(app))
        try:
            events = await self._drain(queue, 3)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        depths = [e.payload["analysis"]["depth_requested"] for e in events]
        assert depths == [1, 2, 3]
        assert events[-1].payload["analysis"]["is_final_depth"] is True
        assert events[-1].payload["analysis"]["max_depth"] == 3
        for e in events:
            assert e.type == EventType.ENGINE_UPDATE
            assert "search_elapsed_ms" in e.payload["analysis"]

    async def test_picks_max_of_requested_depths(self):
        fake = _FakeStockfish()
        app = _make_app(fake, requested_depths={"a": 2, "b": 5, "c": 4})
        queue = await app.state.events.subscribe()

        task = asyncio.create_task(publish_live_engine_updates(app))
        try:
            events = await self._drain(queue, 5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        depths = [e.payload["analysis"]["depth_requested"] for e in events]
        assert depths == [1, 2, 3, 4, 5]
        # max_depth on every event must be the negotiated cap (5)
        for e in events:
            assert e.payload["analysis"]["max_depth"] == 5

    async def test_no_clients_idles_without_calling_stockfish(self):
        fake = _FakeStockfish()
        app = _make_app(fake, clients=0)
        await app.state.events.subscribe()  # subscriber not strictly needed

        task = asyncio.create_task(publish_live_engine_updates(app))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert fake.calls == []

    async def test_push_disabled_skips_analysis(self):
        fake = _FakeStockfish()
        app = _make_app(fake, settings=_Settings(enabled=False))
        await app.state.events.subscribe()

        task = asyncio.create_task(publish_live_engine_updates(app))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert fake.calls == []

    async def test_position_change_resets_depth_counter(self):
        # Use a high max_depth so we can mutate mid-search and observe the
        # publisher restart at depth 1 on the new position.
        fake = _FakeStockfish()
        app = _make_app(
            fake,
            requested_depths={"a": 12},
            settings=_Settings(max_depth=12),
        )
        queue = await app.state.events.subscribe()
        start_fen = app.state.game.board.fen()

        task = asyncio.create_task(publish_live_engine_updates(app))
        try:
            # Let a couple of depths happen, then mutate the position.
            await self._drain(queue, 2)
            app.state.game.push_uci("e2e4")

            # Read until we observe an event whose FEN reflects the new
            # position. The first such event must restart at depth 1.
            for _ in range(20):
                event = await asyncio.wait_for(queue.get(), timeout=1.5)
                analysis = event.payload["analysis"]
                if analysis["fen"] != start_fen:
                    assert analysis["depth_requested"] == 1
                    break
            else:  # pragma: no cover - safety net
                pytest.fail("Never observed analysis for the new position.")
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    async def test_stockfish_exception_does_not_kill_publisher(self):
        # Fail once at depth 1, then succeed normally.
        fake = _FakeStockfish(raise_on_depth=1, raise_count=1)
        app = _make_app(
            fake,
            requested_depths={"a": 2},
            settings=_Settings(max_depth=2, interval_s=0.01),
        )
        queue = await app.state.events.subscribe()

        task = asyncio.create_task(publish_live_engine_updates(app))
        try:
            # Despite the hiccup, the loop should keep going and eventually
            # emit at least 2 events.
            events = await self._drain(queue, 2, timeout=3.0)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert all(e.type == EventType.ENGINE_UPDATE for e in events)

    async def test_cancellation_is_clean(self):
        fake = _FakeStockfish()
        app = _make_app(fake, requested_depths={"a": 3})
        await app.state.events.subscribe()

        task = asyncio.create_task(publish_live_engine_updates(app))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Task is truly done after cancellation
        assert task.done()
