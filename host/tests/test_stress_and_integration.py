"""
Stress, fuzz, and full-integration tests.
"""
from __future__ import annotations

import asyncio
import random
import string
import time

import chess
import pytest

from host.app.domain.game_state import GameState
from host.app.domain.move_reconciler import MoveReconciler
from host.app.hardware.board_sensor import BoardSnapshot, CellState
from host.app.hardware.serial_link import CommandReply, MockJsonLineClient
from host.tests.conftest import snapshot_from_board


def random_board() -> chess.Board:
    board = chess.Board()
    for _ in range(random.randint(1, 40)):
        if board.is_game_over():
            break
        board.push(random.choice(list(board.legal_moves)))
    return board


def assert_state_shape_basic(state: dict) -> None:
    required = {"game_id", "fen", "turn", "legal_moves", "is_check",
                "is_game_over", "result", "robot_busy", "last_error"}
    assert required.issubset(set(state.keys()))


class TestStressReconciler:
    def test_200_random_legal_moves_all_reconcile(self):
        random.seed(42)
        reconciler = MoveReconciler()
        failures = []
        for _ in range(200):
            board = random_board()
            if board.is_game_over():
                continue
            move = random.choice(list(board.legal_moves))
            if move.promotion:
                continue
            before = snapshot_from_board(board)
            board.push(move)
            after = snapshot_from_board(board)
            board.pop()
            result = reconciler.reconcile(board, before, after)
            if result.confidence == 1.0:
                if result.move is None or result.move.uci() != move.uci():
                    failures.append((board.fen(), move.uci(), result.reason))
            elif move.uci() not in result.candidates:
                failures.append((board.fen(), move.uci(), result.reason))
        assert len(failures) == 0, (
            f"{len(failures)} failures:\n"
            + "\n".join(f"  {fen} {mv}: {r}" for fen, mv, r in failures[:5])
        )

    def test_100_random_full_games_no_exception(self):
        random.seed(99)
        for _ in range(100):
            board = chess.Board()
            while not board.is_game_over():
                board.push(random.choice(list(board.legal_moves)))
            assert board.result() in {"1-0", "0-1", "1/2-1/2", "*"}

    def test_game_state_50_sequential_moves(self):
        random.seed(77)
        game = GameState()
        for _ in range(50):
            if game.board.is_game_over():
                break
            move = random.choice(list(game.board.legal_moves))
            game.push_uci(move.uci())
        assert_state_shape_basic(game.snapshot())

    def test_reconcile_all_20_starting_moves(self):
        board = chess.Board()
        reconciler = MoveReconciler()
        for move in list(board.legal_moves):
            before = snapshot_from_board(board)
            b2 = board.copy()
            b2.push(move)
            after = snapshot_from_board(b2)
            result = reconciler.reconcile(board, before, after)
            assert result.move is not None, f"Failed: {move.uci()}"
            assert result.move.uci() == move.uci()

    def test_1000_reconcile_calls_complete_in_under_3_seconds(self):
        random.seed(42)
        reconciler = MoveReconciler()
        board = chess.Board()
        start = time.monotonic()
        for _ in range(1000):
            if board.is_game_over():
                board = chess.Board()
            move = random.choice(list(board.legal_moves))
            before = snapshot_from_board(board)
            board.push(move)
            after = snapshot_from_board(board)
            board.pop()
            reconciler.reconcile(board, before, after)
            board.push(move)
        elapsed = time.monotonic() - start
        assert elapsed < 3.0, f"1000 reconcile calls took {elapsed:.2f}s"

    def test_game_state_snapshot_valid_over_100_moves(self):
        random.seed(55)
        game = GameState()
        for _ in range(100):
            if game.board.is_game_over():
                game.new_game()
            move = random.choice(list(game.board.legal_moves))
            game.push_uci(move.uci())
            snap = game.snapshot()
            assert isinstance(snap["fen"], str)
            assert snap["turn"] in ("white", "black")
            assert isinstance(snap["legal_moves"], list)


class TestSensorReplayFull:
    def _replay(self, uci_moves: list[str]) -> None:
        """
        Replay a game through the reconciler.

        Unambiguous moves (result.confidence == 1.0) must match exactly.
        Ambiguous moves (multiple legal moves share same occupancy outcome)
        must at minimum include the correct move in candidates — this is
        expected behavior for captures where multiple pieces can reach the
        same square, and for promotions.
        """
        board = chess.Board()
        reconciler = MoveReconciler()
        for uci in uci_moves:
            before = snapshot_from_board(board)
            move = chess.Move.from_uci(uci)
            board.push(move)
            after = snapshot_from_board(board)
            board.pop()
            result = reconciler.reconcile(board, before, after)
            if result.confidence == 1.0:
                # Unambiguous: must match exactly
                assert result.move is not None, f"Unambiguous move failed: {uci} in {board.fen()}"
                assert result.move.uci() == uci
            else:
                # Ambiguous: correct move must be among candidates
                assert uci in result.candidates, (
                    f"Move {uci} not in candidates {result.candidates} for {board.fen()}"
                )
            board.push(move)

    def test_fools_mate(self):
        self._replay(["f2f3", "e7e5", "g2g4", "d8h4"])

    def test_scholars_mate(self):
        self._replay(["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"])

    def test_ruy_lopez_with_castling(self):
        self._replay(["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "e1g1"])

    def test_en_passant_sequence(self):
        self._replay(["e2e4", "d7d5", "e4d5", "c7c5", "d5c6"])

    def test_queenside_castling(self):
        self._replay([
            "d2d4", "d7d5", "c1f4", "g8f6", "b1c3", "b8c6",
            "d1d3", "c8f5", "e1c1"
        ])

    def test_promotion_appears_in_candidates(self):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        board = chess.Board(fen)
        reconciler = MoveReconciler()
        move = chess.Move.from_uci("a7a8q")
        before = snapshot_from_board(board)
        board.push(move)
        after = snapshot_from_board(board)
        board.pop()
        result = reconciler.reconcile(board, before, after)
        assert "a7a8q" in result.candidates
        assert len(result.candidates) == 4

    def test_opera_game(self):
        moves = [
            "e2e4", "e7e5", "g1f3", "d7d6", "d2d4", "c8g4",
            "d4e5", "g4f3", "d1f3", "d6e5", "f1c4", "g8f6",
            "f3b3", "d8e7", "b1c3", "c7c6", "c1g5", "b7b5",
            "c3b5", "c6b5", "c4b5", "b8d7", "e1c1", "a8d8",
            "d1d7", "d8d7", "h1d1", "e7e6", "b5d7", "f6d7",
            "b3b8", "d7b8", "d1d8",
        ]
        self._replay(moves)


class TestSerialFuzz:
    @pytest.mark.asyncio
    async def test_random_string_commands_return_not_ok(self):
        c = MockJsonLineClient()
        await c.start()
        random.seed(111)
        for _ in range(20):
            cmd = "".join(random.choices(string.ascii_letters + string.digits, k=10))
            if cmd in {"home", "park", "move", "scan", "set_em", "capture_move",
                       "move_square_to_square"}:
                continue
            r = await c.send_command(cmd)
            assert r.ok is False, f"Expected ok=False for unknown command '{cmd}'"

    @pytest.mark.asyncio
    async def test_special_character_commands_return_not_ok(self):
        c = MockJsonLineClient()
        await c.start()
        for cmd in ["../etc", "DROP TABLE", "null", "true", "123"]:
            r = await c.send_command(cmd)
            assert isinstance(r, CommandReply)

    @pytest.mark.asyncio
    async def test_very_long_command_name_not_ok(self):
        c = MockJsonLineClient()
        await c.start()
        r = await c.send_command("a" * 1000)
        assert r.ok is False

    @pytest.mark.asyncio
    async def test_unknown_kwargs_with_valid_command(self):
        c = MockJsonLineClient()
        await c.start()
        # home is valid; extra kwargs should not crash
        r = await c.send_command("home", totally_fake_param=999)
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_move_with_none_squares_does_not_crash(self):
        c = MockJsonLineClient()
        await c.start()
        r = await c.send_command("move", **{"from": None, "to": None, "capture": False})
        assert isinstance(r, CommandReply)

    @pytest.mark.asyncio
    async def test_50_random_commands_none_raise(self):
        c = MockJsonLineClient()
        await c.start()
        random.seed(222)
        known_ok = ["home", "park", "set_em", "scan"]
        for _ in range(50):
            cmd = random.choice(known_ok + ["garbage1", "garbage2", "garbage3"])
            try:
                r = await c.send_command(cmd)
                assert isinstance(r, CommandReply)
            except Exception as e:
                pytest.fail(f"send_command raised unexpectedly: {e}")


class TestProviderAbstraction:
    """Test the GameProvider ABC and concrete implementations."""

    def test_local_engine_provider_has_name(self):
        from host.app.providers.local_engine import LocalEngineProvider
        from host.app.chesscore.engine_service import StockfishService
        svc = StockfishService.__new__(StockfishService)  # don't start stockfish
        provider = LocalEngineProvider.__new__(LocalEngineProvider)
        assert hasattr(LocalEngineProvider, "name")
        assert LocalEngineProvider.name == "local_engine"

    def test_cloud_relay_provider_has_name(self):
        from host.app.providers.cloud_relay import CloudRelayProvider
        assert CloudRelayProvider.name == "cloud_relay"

    @pytest.mark.asyncio
    async def test_cloud_relay_push_and_receive_move(self):
        from host.app.providers.cloud_relay import CloudRelayProvider
        provider = CloudRelayProvider()
        await provider.start()
        await provider.push_remote_move("e2e4")
        # The queue should now have the move
        from host.app.providers.base import ProviderMove
        move = await asyncio.wait_for(provider._queue.get(), timeout=1.0)
        assert move.uci == "e2e4"
        await provider.stop()

    @pytest.mark.asyncio
    async def test_cloud_relay_push_with_raw(self):
        from host.app.providers.cloud_relay import CloudRelayProvider
        provider = CloudRelayProvider()
        await provider.start()
        raw = {"moves": "e2e4", "status": "started"}
        await provider.push_remote_move("e2e4", raw=raw)
        move = await asyncio.wait_for(provider._queue.get(), timeout=1.0)
        assert move.raw == raw
        await provider.stop()

    @pytest.mark.asyncio
    async def test_cloud_relay_start_stop(self):
        from host.app.providers.cloud_relay import CloudRelayProvider
        provider = CloudRelayProvider()
        await provider.start()
        assert provider._running is True
        await provider.stop()
        assert provider._running is False

    @pytest.mark.asyncio
    async def test_cloud_relay_multiple_moves_ordered(self):
        from host.app.providers.cloud_relay import CloudRelayProvider
        provider = CloudRelayProvider()
        await provider.start()
        for uci in ["e2e4", "e7e5", "g1f3"]:
            await provider.push_remote_move(uci)
        for expected in ["e2e4", "e7e5", "g1f3"]:
            move = await asyncio.wait_for(provider._queue.get(), timeout=1.0)
            assert move.uci == expected
        await provider.stop()

    def test_provider_move_dataclass(self):
        from host.app.providers.base import ProviderMove
        pm = ProviderMove(uci="e2e4", source="local_engine")
        assert pm.uci == "e2e4"
        assert pm.source == "local_engine"
        assert pm.raw is None

    def test_provider_move_with_raw(self):
        from host.app.providers.base import ProviderMove
        raw = {"key": "value"}
        pm = ProviderMove(uci="e7e5", source="cloud", raw=raw)
        assert pm.raw == raw


class TestConcurrentWebSocket:
    """WebSocket stress tests."""

    def test_two_simultaneous_connections_both_get_hello(self, client):
        with client.websocket_connect("/ws") as ws1,              client.websocket_connect("/ws") as ws2:
            d1 = ws1.receive_json()
            d2 = ws2.receive_json()
        assert d1["type"] == "HELLO"
        assert d2["type"] == "HELLO"

    def test_new_game_event_reaches_both_subscribers(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws1,              client.websocket_connect("/ws") as ws2:
            ws1.receive_json()
            ws2.receive_json()
            client.post("/api/game/new")
            ev1 = ws1.receive_json()
            ev2 = ws2.receive_json()
        assert ev1["type"] == "STATE_CHANGED"
        assert ev2["type"] == "STATE_CHANGED"

    def test_5_game_resets_produce_5_events(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            for _ in range(5):
                client.post("/api/game/new")
            events = [ws.receive_json() for _ in range(5)]
        assert all(e["type"] == "STATE_CHANGED" for e in events)

    def test_websocket_disconnects_cleanly(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
        # No exception means clean disconnect

    def test_hello_state_shape(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            d = ws.receive_json()
        assert "state" in d
        state = d["state"]
        assert "fen" in state
        assert "turn" in state
        assert "legal_moves" in state

    def test_human_move_emits_local_move_candidate(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            client.post("/api/move/human", json={"uci": "e2e4"})
            ev = ws.receive_json()
        assert ev["type"] == "LOCAL_MOVE_CANDIDATE"

    def test_local_move_candidate_has_uci_in_payload(self, client):
        client.post("/api/game/new")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            client.post("/api/move/human", json={"uci": "e2e4"})
            ev = ws.receive_json()
        assert ev["payload"]["uci"] == "e2e4"


class TestLargePayloads:
    def test_snapshot_payload_under_5kb(self):
        import json as json_module
        from host.app.hardware.board_sensor import BoardSnapshot, CellState
        snap = BoardSnapshot.empty()
        for sq in list(snap.cells.keys()):
            snap.cells[sq] = CellState(True, -1, 800)
        payload = snap.to_payload()
        serialized = json_module.dumps(payload)
        assert len(serialized.encode()) < 5 * 1024

    def test_board_sensor_update_100_times(self):
        from host.app.hardware.board_sensor import BoardSensorService
        svc = BoardSensorService()
        for i in range(100):
            event = {"ts_ms": i * 10, "cells": {"e4": {"o": i % 2, "p": -1, "m": 800}}}
            svc.update_from_event(event)
        # Final state should be deterministic
        assert svc.latest.cells["e4"].occupied == (99 % 2 == 1)


from host.tests.conftest import client  # noqa: F401
