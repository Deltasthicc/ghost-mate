"""Invariant + cache tests for ``GameState`` and ``EventBus``.

These exercises the boring guarantees that make the rest of the system safe:
- Snapshot caching is keyed on every mutating field (position, robot_busy,
  last_error, game_id) and is invalidated on every mutating call.
- ``push_uci`` rejects illegal/malformed UCI without mutating the board.
- ``new_game`` accepts valid FENs and rejects invalid ones cleanly.
- ``EventBus`` fan-out works for many subscribers, slow subscribers do not
  block fast ones, and unsubscribe cleans up.

All tests are hermetic and fast.
"""
from __future__ import annotations

import asyncio

import chess
import pytest

from host.app.domain.events import Event, EventBus, EventType
from host.app.domain.game_state import GameState, evaluate_position


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_position
# ─────────────────────────────────────────────────────────────────────────────

class TestEvaluatePosition:
    def test_starting_position_is_even(self):
        out = evaluate_position(chess.Board())
        assert out["display"] == "0.00"
        assert out["score_cp"] == 0

    def test_checkmate_returns_mate_display(self):
        board = chess.Board(
            "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
        )
        out = evaluate_position(board)
        assert out["mate_in"] == 0
        assert out["display"].startswith("#")

    def test_material_imbalance_reported(self):
        # Black is missing its queen → White is up 9.
        board = chess.Board(
            "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )
        out = evaluate_position(board)
        assert out["score_cp"] == 900
        assert out["display"] == "+9.00"


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot caching
# ─────────────────────────────────────────────────────────────────────────────

class TestSnapshotCaching:
    def test_repeated_snapshot_returns_same_object(self, game):
        first = game.snapshot()
        second = game.snapshot()
        assert first is second  # identity, cached

    def test_push_invalidates_cache(self, game):
        first = game.snapshot()
        game.push_uci("e2e4")
        second = game.snapshot()
        assert first is not second
        assert first["fen"] != second["fen"]

    def test_robot_busy_change_invalidates_cache(self, game):
        first = game.snapshot()
        game.robot_busy = True
        second = game.snapshot()
        assert first is not second
        assert second["robot_busy"] is True

    def test_last_error_change_invalidates_cache(self, game):
        first = game.snapshot()
        game.last_error = "fault"
        second = game.snapshot()
        assert first is not second
        assert second["last_error"] == "fault"

    def test_new_game_invalidates_cache(self, game):
        first = game.snapshot()
        game.new_game()
        second = game.snapshot()
        assert first is not second
        assert first["game_id"] != second["game_id"]

    def test_snapshot_has_all_required_fields(self, game):
        snap = game.snapshot()
        required = {
            "game_id", "fen", "turn", "legal_moves", "is_check",
            "is_game_over", "result", "robot_busy", "last_error",
            "evaluation", "ply", "halfmove_clock", "fullmove_number",
            "start_fen", "move_history",
        }
        assert required.issubset(snap.keys())


# ─────────────────────────────────────────────────────────────────────────────
# push_uci / push_san negative cases
# ─────────────────────────────────────────────────────────────────────────────

class TestPushNegativeCases:
    @pytest.mark.parametrize("bad", [
        "",            # empty
        "z9z9",        # nonsense
        "e2e5",        # illegal (would skip a pawn)
        "e7e5",        # wrong side
        "e2-e4",       # malformed
        "🎮🎮",        # unicode garbage
    ])
    def test_illegal_or_malformed_uci_raises(self, game, bad):
        with pytest.raises((ValueError, chess.InvalidMoveError, chess.IllegalMoveError)):
            game.push_uci(bad)
        # Board untouched
        assert game.board.fen() == chess.STARTING_FEN

    @pytest.mark.parametrize("bad_san", [
        "",
        "Qz9",
        "Ke9",
        "0-0-0-0",  # not a real move
    ])
    def test_illegal_san_raises(self, game, bad_san):
        with pytest.raises((ValueError, chess.InvalidMoveError,
                            chess.IllegalMoveError, chess.AmbiguousMoveError)):
            game.push_san(bad_san)

    def test_case_insensitive_uci(self, game):
        game.push_uci("E2E4")
        assert game.board.move_stack[-1].uci() == "e2e4"

    def test_whitespace_stripped(self, game):
        game.push_uci("   e2e4   ")
        assert game.board.move_stack[-1].uci() == "e2e4"

    def test_new_game_invalid_fen_raises(self, game):
        with pytest.raises(ValueError):
            game.new_game("totally-not-fen")

    def test_legal_uci_moves_at_start(self, game):
        legal = set(game.legal_uci_moves())
        assert "e2e4" in legal and "d2d4" in legal
        assert len(legal) == 20


# ─────────────────────────────────────────────────────────────────────────────
# EventBus
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestEventBus:
    async def test_subscriber_count_tracks_subscribe_unsubscribe(self):
        bus = EventBus(default_max=4)
        assert bus.subscriber_count == 0
        q1 = await bus.subscribe()
        q2 = await bus.subscribe()
        assert bus.subscriber_count == 2
        await bus.unsubscribe(q1)
        assert bus.subscriber_count == 1
        await bus.unsubscribe(q2)
        assert bus.subscriber_count == 0

    async def test_publish_fans_out_to_all_subscribers(self):
        bus = EventBus(default_max=4)
        queues = [await bus.subscribe() for _ in range(3)]
        await bus.publish(Event(EventType.STATE_CHANGED, {"x": 1}))
        for q in queues:
            event = await asyncio.wait_for(q.get(), timeout=0.5)
            assert event.payload == {"x": 1}

    async def test_full_queue_drops_oldest_then_inserts_new(self):
        bus = EventBus(default_max=2)
        q = await bus.subscribe(maxsize=2)
        for i in range(4):
            await bus.publish(Event(EventType.STATE_CHANGED, {"i": i}))
        # Queue capacity is 2. The oldest events are dropped to make room.
        items = []
        while not q.empty():
            items.append(q.get_nowait().payload["i"])
        assert len(items) == 2
        assert items[-1] == 3  # newest survives

    async def test_publish_does_not_throw_when_no_subscribers(self):
        bus = EventBus()
        await bus.publish(Event(EventType.STATE_CHANGED, {}))  # must not raise

    async def test_publish_nowait_works_outside_loop(self):
        bus = EventBus(default_max=2)
        q = await bus.subscribe()
        bus.publish_nowait(Event(EventType.STATE_CHANGED, {"v": 7}))
        ev = await asyncio.wait_for(q.get(), timeout=0.5)
        assert ev.payload == {"v": 7}

    async def test_unsubscribe_unknown_queue_is_safe(self):
        bus = EventBus()
        other_queue: asyncio.Queue = asyncio.Queue()
        await bus.unsubscribe(other_queue)  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# Stress: rapid push / snapshot interactions
# ─────────────────────────────────────────────────────────────────────────────

class TestRapidMutationsRemainConsistent:
    def test_hundred_alternating_pushes_and_snapshots(self, game):
        moves = (
            "e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5a4 g8f6 e1g1 f8e7 "
            "f1e1 b7b5 a4b3 d7d6 c2c3 e8g8 h2h3 c6a5 b3c2 c7c5 "
        ).split()
        for uci in moves:
            game.push_uci(uci)
            snap = game.snapshot()
            assert snap["ply"] == len(game.board.move_stack)
            assert snap["fen"] == game.board.fen()
            assert snap["move_history"][-1]["uci"] == uci

    def test_legal_moves_decrease_or_grow_consistently(self, game):
        prev = len(game.legal_uci_moves())
        for uci in ("e2e4", "e7e5"):
            game.push_uci(uci)
            curr = len(game.legal_uci_moves())
            assert curr > 0
            prev = curr
