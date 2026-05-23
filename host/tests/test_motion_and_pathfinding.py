"""
Comprehensive tests for host.app.hardware.motion_service.MotionService
and host.app.hardware.serial_link.MockJsonLineClient / CommandReply.

MotionService is a thin wrapper over the serial client exposing:
  home(), park(), scan(), set_electromagnet(), move_square_to_square(), capture_move()

All tests use MockJsonLineClient so no hardware is needed.
"""
from __future__ import annotations

import asyncio

import pytest

from host.app.hardware.motion_service import MotionService
from host.app.hardware.serial_link import CommandReply, MockJsonLineClient


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
async def client():
    c = MockJsonLineClient()
    await c.start()
    yield c
    await c.stop()


@pytest.fixture()
async def svc(client):
    return MotionService(serial=client)


# ══════════════════════════════════════════════════════════════════════════════
# MockJsonLineClient lifecycle
# ══════════════════════════════════════════════════════════════════════════════

class TestMockClientLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_started_flag(self):
        c = MockJsonLineClient()
        assert c._started is False
        await c.start()
        assert c._started is True

    @pytest.mark.asyncio
    async def test_stop_clears_started_flag(self):
        c = MockJsonLineClient()
        await c.start()
        await c.stop()
        assert c._started is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self):
        c = MockJsonLineClient()
        await c.start()
        await c.start()
        assert c._started is True

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        c = MockJsonLineClient()
        await c.stop()  # must not raise
        assert c._started is False


# ══════════════════════════════════════════════════════════════════════════════
# MockJsonLineClient command routing
# ══════════════════════════════════════════════════════════════════════════════

class TestMockClientCommands:
    @pytest.mark.asyncio
    async def test_home_returns_ok(self, client):
        r = await client.send_command("home")
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_park_returns_ok(self, client):
        r = await client.send_command("park")
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_set_em_on_returns_ok(self, client):
        r = await client.send_command("set_em", on=True)
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_set_em_off_returns_ok(self, client):
        r = await client.send_command("set_em", on=False)
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_unknown_command_returns_not_ok(self, client):
        r = await client.send_command("nonexistent_cmd")
        assert r.ok is False

    @pytest.mark.asyncio
    async def test_unknown_command_has_error_message(self, client):
        r = await client.send_command("nonexistent_cmd")
        assert r.err is not None
        assert len(r.err) > 0

    @pytest.mark.asyncio
    async def test_ids_increment(self, client):
        r1 = await client.send_command("home")
        r2 = await client.send_command("park")
        assert r2.id == r1.id + 1

    @pytest.mark.asyncio
    async def test_ids_start_at_1(self):
        c = MockJsonLineClient()
        await c.start()
        r = await c.send_command("home")
        assert r.id == 1

    @pytest.mark.asyncio
    async def test_reply_has_raw_dict(self, client):
        r = await client.send_command("home")
        assert r.raw is not None
        assert isinstance(r.raw, dict)

    @pytest.mark.asyncio
    async def test_reply_raw_contains_id_and_ok(self, client):
        r = await client.send_command("home")
        assert "id" in r.raw
        assert "ok" in r.raw

    @pytest.mark.asyncio
    async def test_many_sequential_commands(self, client):
        cmds = ["home", "park", "home", "set_em", "park", "home"]
        for cmd in cmds:
            r = await client.send_command(cmd)
            assert isinstance(r, CommandReply)


# ══════════════════════════════════════════════════════════════════════════════
# MockJsonLineClient — move command
# ══════════════════════════════════════════════════════════════════════════════

class TestMockClientMove:
    @pytest.mark.asyncio
    async def test_move_returns_ok(self, client):
        r = await client.send_command("move", **{"from": "e2", "to": "e4", "capture": False})
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_move_updates_piece_map_src_gone(self, client):
        await client.send_command("move", **{"from": "e2", "to": "e4", "capture": False})
        assert "e2" not in client._pieces

    @pytest.mark.asyncio
    async def test_move_updates_piece_map_dst_occupied(self, client):
        await client.send_command("move", **{"from": "e2", "to": "e4", "capture": False})
        assert client._pieces.get("e4") == "white"

    @pytest.mark.asyncio
    async def test_move_preserves_color(self, client):
        await client.send_command("move", **{"from": "e7", "to": "e5", "capture": False})
        assert client._pieces.get("e5") == "black"

    @pytest.mark.asyncio
    async def test_move_via_move_square_to_square_alias(self, client):
        r = await client.send_command("move_square_to_square",
                                      **{"from": "d2", "to": "d4", "capture": False})
        assert r.ok is True
        assert client._pieces.get("d4") == "white"

    @pytest.mark.asyncio
    async def test_move_emits_motion_done_event(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.send_command("move", **{"from": "e2", "to": "e4", "capture": False})
        motion_events = [e for e in events if e.get("type") == "motion_done"]
        assert len(motion_events) == 1

    @pytest.mark.asyncio
    async def test_motion_done_event_has_matching_id(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        reply = await client.send_command("move", **{"from": "e2", "to": "e4", "capture": False})
        done = next(e for e in events if e.get("type") == "motion_done")
        assert done["id"] == reply.id

    @pytest.mark.asyncio
    async def test_move_nonexistent_piece_no_crash(self, client):
        # e4 is empty in starting position
        r = await client.send_command("move", **{"from": "e4", "to": "e5", "capture": False})
        assert r.ok is True  # mock doesn't enforce piece presence

    @pytest.mark.asyncio
    async def test_all_starting_pawn_moves(self, client):
        for file in "abcdefgh":
            r = await client.send_command(
                "move", **{"from": f"{file}2", "to": f"{file}4", "capture": False}
            )
            assert r.ok is True
            assert client._pieces.get(f"{file}4") == "white"


# ══════════════════════════════════════════════════════════════════════════════
# MockJsonLineClient — capture_move command
# ══════════════════════════════════════════════════════════════════════════════

class TestMockClientCaptureMove:
    @pytest.mark.asyncio
    async def test_capture_returns_ok(self, client):
        r = await client.send_command(
            "capture_move", victim="d5", **{"from": "e4", "to": "d5"}
        )
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_capture_removes_victim(self, client):
        # Set up pieces manually
        client._pieces["d5"] = "black"
        client._pieces["e4"] = "white"
        await client.send_command("capture_move", victim="d5",
                                  **{"from": "e4", "to": "d5"})
        # After capture, d5 should have the attacker's color
        assert client._pieces.get("d5") == "white"

    @pytest.mark.asyncio
    async def test_capture_removes_source(self, client):
        client._pieces["d5"] = "black"
        client._pieces["e4"] = "white"
        await client.send_command("capture_move", victim="d5",
                                  **{"from": "e4", "to": "d5"})
        assert "e4" not in client._pieces

    @pytest.mark.asyncio
    async def test_capture_emits_motion_done(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        client._pieces["d5"] = "black"
        client._pieces["e4"] = "white"
        await client.send_command("capture_move", victim="d5",
                                  **{"from": "e4", "to": "d5"})
        assert any(e.get("type") == "motion_done" for e in events)


# ══════════════════════════════════════════════════════════════════════════════
# MockJsonLineClient — scan command
# ══════════════════════════════════════════════════════════════════════════════

class TestMockClientScan:
    @pytest.mark.asyncio
    async def test_scan_returns_ok(self, client):
        r = await client.send_command("scan", full=True)
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_scan_emits_scan_event(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.send_command("scan", full=True)
        assert any(e.get("type") == "scan" for e in events)

    @pytest.mark.asyncio
    async def test_scan_event_has_64_cells(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.send_command("scan", full=True)
        scan = next(e for e in events if e.get("type") == "scan")
        assert len(scan["cells"]) == 64

    @pytest.mark.asyncio
    async def test_scan_event_has_ts_ms(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.send_command("scan", full=True)
        scan = next(e for e in events if e.get("type") == "scan")
        assert "ts_ms" in scan

    @pytest.mark.asyncio
    async def test_scan_starting_position_white_pieces_negative_polarity(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.send_command("scan", full=True)
        scan = next(e for e in events if e.get("type") == "scan")
        assert scan["cells"]["e1"]["o"] == 1
        assert scan["cells"]["e1"]["p"] == -1

    @pytest.mark.asyncio
    async def test_scan_starting_position_black_pieces_positive_polarity(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.send_command("scan", full=True)
        scan = next(e for e in events if e.get("type") == "scan")
        assert scan["cells"]["e8"]["o"] == 1
        assert scan["cells"]["e8"]["p"] == 1

    @pytest.mark.asyncio
    async def test_scan_empty_squares_zero_values(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.send_command("scan", full=True)
        scan = next(e for e in events if e.get("type") == "scan")
        assert scan["cells"]["e4"]["o"] == 0
        assert scan["cells"]["e4"]["p"] == 0
        assert scan["cells"]["e4"]["m"] == 0

    @pytest.mark.asyncio
    async def test_scan_reflects_updated_piece_map(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        # Move e2 pawn to e4
        await client.send_command("move", **{"from": "e2", "to": "e4", "capture": False})
        events.clear()
        await client.send_command("scan", full=True)
        scan = next(e for e in events if e.get("type") == "scan")
        assert scan["cells"]["e4"]["o"] == 1
        assert scan["cells"]["e2"]["o"] == 0

    @pytest.mark.asyncio
    async def test_scan_all_cells_have_o_p_m_keys(self, client):
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.send_command("scan", full=True)
        scan = next(e for e in events if e.get("type") == "scan")
        for square, cell in scan["cells"].items():
            assert "o" in cell, f"Missing 'o' in {square}"
            assert "p" in cell, f"Missing 'p' in {square}"
            assert "m" in cell, f"Missing 'm' in {square}"


# ══════════════════════════════════════════════════════════════════════════════
# MockJsonLineClient — starting piece map
# ══════════════════════════════════════════════════════════════════════════════

class TestMockClientPieceMap:
    def test_starting_piece_map_has_32_pieces(self):
        c = MockJsonLineClient()
        assert len(c._pieces) == 32

    def test_white_pieces_on_ranks_1_and_2(self):
        c = MockJsonLineClient()
        for file in "abcdefgh":
            assert c._pieces.get(f"{file}1") == "white"
            assert c._pieces.get(f"{file}2") == "white"

    def test_black_pieces_on_ranks_7_and_8(self):
        c = MockJsonLineClient()
        for file in "abcdefgh":
            assert c._pieces.get(f"{file}7") == "black"
            assert c._pieces.get(f"{file}8") == "black"

    def test_middle_ranks_empty(self):
        c = MockJsonLineClient()
        for file in "abcdefgh":
            for rank in "3456":
                assert f"{file}{rank}" not in c._pieces

    def test_no_duplicate_squares(self):
        c = MockJsonLineClient()
        assert len(c._pieces) == len(set(c._pieces.keys()))


# ══════════════════════════════════════════════════════════════════════════════
# CommandReply dataclass
# ══════════════════════════════════════════════════════════════════════════════

class TestCommandReply:
    def test_ok_reply(self):
        r = CommandReply(id=1, ok=True)
        assert r.ok is True
        assert r.err is None

    def test_error_reply(self):
        r = CommandReply(id=2, ok=False, err="timeout")
        assert r.ok is False
        assert r.err == "timeout"

    def test_raw_field_stores_dict(self):
        raw = {"id": 3, "ok": True}
        r = CommandReply(id=3, ok=True, raw=raw)
        assert r.raw == raw

    def test_raw_defaults_to_none(self):
        r = CommandReply(id=4, ok=True)
        assert r.raw is None

    def test_id_stored(self):
        r = CommandReply(id=99, ok=True)
        assert r.id == 99


# ══════════════════════════════════════════════════════════════════════════════
# MotionService wraps serial correctly
# ══════════════════════════════════════════════════════════════════════════════

class TestMotionService:
    @pytest.mark.asyncio
    async def test_home_calls_home_command(self, client):
        calls = []
        orig = client.send_command

        async def spy(cmd, **kw):
            calls.append(cmd)
            return await orig(cmd, **kw)

        client.send_command = spy
        svc = MotionService(serial=client)
        await svc.home()
        assert "home" in calls

    @pytest.mark.asyncio
    async def test_home_returns_command_reply(self, svc):
        r = await svc.home()
        assert isinstance(r, CommandReply)

    @pytest.mark.asyncio
    async def test_home_ok(self, svc):
        r = await svc.home()
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_park_calls_park_command(self, client):
        calls = []
        orig = client.send_command

        async def spy(cmd, **kw):
            calls.append(cmd)
            return await orig(cmd, **kw)

        client.send_command = spy
        svc = MotionService(serial=client)
        await svc.park()
        assert "park" in calls

    @pytest.mark.asyncio
    async def test_park_ok(self, svc):
        r = await svc.park()
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_scan_calls_scan_command(self, client):
        calls = []
        orig = client.send_command

        async def spy(cmd, **kw):
            calls.append(cmd)
            return await orig(cmd, **kw)

        client.send_command = spy
        svc = MotionService(serial=client)
        await svc.scan()
        assert "scan" in calls

    @pytest.mark.asyncio
    async def test_scan_ok(self, svc):
        r = await svc.scan()
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_scan_full_parameter_passed(self, client):
        calls = []
        orig = client.send_command

        async def spy(cmd, **kw):
            calls.append((cmd, kw))
            return await orig(cmd, **kw)

        client.send_command = spy
        svc = MotionService(serial=client)
        await svc.scan(full=False)
        assert any(cmd == "scan" and kw.get("full") is False for cmd, kw in calls)

    @pytest.mark.asyncio
    async def test_set_electromagnet_on(self, client):
        calls = []
        orig = client.send_command

        async def spy(cmd, **kw):
            calls.append((cmd, kw))
            return await orig(cmd, **kw)

        client.send_command = spy
        svc = MotionService(serial=client)
        await svc.set_electromagnet(True)
        assert any(cmd == "set_em" and kw.get("on") is True for cmd, kw in calls)

    @pytest.mark.asyncio
    async def test_set_electromagnet_off(self, client):
        calls = []
        orig = client.send_command

        async def spy(cmd, **kw):
            calls.append((cmd, kw))
            return await orig(cmd, **kw)

        client.send_command = spy
        svc = MotionService(serial=client)
        await svc.set_electromagnet(False)
        assert any(cmd == "set_em" and kw.get("on") is False for cmd, kw in calls)

    @pytest.mark.asyncio
    async def test_move_square_to_square_ok(self, svc):
        r = await svc.move_square_to_square("e2", "e4")
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_move_square_to_square_updates_mock(self, client):
        svc = MotionService(serial=client)
        await svc.move_square_to_square("e2", "e4")
        assert client._pieces.get("e4") == "white"
        assert "e2" not in client._pieces

    @pytest.mark.asyncio
    async def test_move_square_to_square_capture_flag_passed(self, client):
        calls = []
        orig = client.send_command

        async def spy(cmd, **kw):
            calls.append((cmd, kw))
            return await orig(cmd, **kw)

        client.send_command = spy
        svc = MotionService(serial=client)
        await svc.move_square_to_square("e4", "d5", capture=True)
        move_call = next(c for c, kw in calls if c == "move")
        assert move_call == "move"

    @pytest.mark.asyncio
    async def test_capture_move_ok(self, svc, client):
        client._pieces["d5"] = "black"
        client._pieces["e4"] = "white"
        r = await svc.capture_move("d5", "e4", "d5")
        assert r.ok is True

    @pytest.mark.asyncio
    async def test_capture_move_removes_victim(self, svc, client):
        client._pieces["d5"] = "black"
        client._pieces["e4"] = "white"
        await svc.capture_move("d5", "e4", "d5")
        assert client._pieces.get("d5") == "white"
        assert "e4" not in client._pieces

    @pytest.mark.asyncio
    async def test_capture_move_calls_capture_command(self, client):
        calls = []
        orig = client.send_command

        async def spy(cmd, **kw):
            calls.append(cmd)
            return await orig(cmd, **kw)

        client.send_command = spy
        svc = MotionService(serial=client)
        client._pieces["d5"] = "black"
        client._pieces["e4"] = "white"
        await svc.capture_move("d5", "e4", "d5")
        assert "capture_move" in calls

    @pytest.mark.asyncio
    async def test_home_park_scan_sequence(self, svc):
        assert (await svc.home()).ok is True
        assert (await svc.park()).ok is True
        assert (await svc.scan()).ok is True

    @pytest.mark.asyncio
    async def test_multiple_moves_sequential(self, svc, client):
        pairs = [("e2", "e4"), ("d2", "d4"), ("g1", "f3"), ("b1", "c3")]
        for src, dst in pairs:
            r = await svc.move_square_to_square(src, dst)
            assert r.ok is True
        assert client._pieces.get("e4") == "white"
        assert client._pieces.get("d4") == "white"
        assert client._pieces.get("f3") == "white"
        assert client._pieces.get("c3") == "white"


# ══════════════════════════════════════════════════════════════════════════════
# Integration: MotionService + GameState
# ══════════════════════════════════════════════════════════════════════════════

class TestMotionServiceIntegration:
    @pytest.mark.asyncio
    async def test_five_move_game(self):
        """GameState tracks moves; MotionService executes each physically."""
        from host.app.domain.game_state import GameState
        import chess

        c = MockJsonLineClient()
        await c.start()
        svc = MotionService(serial=c)
        game = GameState()

        moves = [("e2", "e4"), ("e7", "e5"), ("g1", "f3"), ("b8", "c6"), ("f1", "b5")]
        for src, dst in moves:
            game.push_uci(f"{src}{dst}")
            r = await svc.move_square_to_square(src, dst)
            assert r.ok is True

        assert not game.snapshot()["is_game_over"]
        assert game.board.piece_at(chess.B5).symbol() == "B"

    @pytest.mark.asyncio
    async def test_capture_integration(self):
        from host.app.domain.game_state import GameState

        c = MockJsonLineClient()
        await c.start()
        svc = MotionService(serial=c)

        fen = "4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1"
        game = GameState()
        game.new_game(fen)
        c._pieces = {"e4": "white", "d5": "black", "e1": "white", "e8": "black"}

        game.push_uci("e4d5")
        r = await svc.capture_move("d5", "e4", "d5")
        assert r.ok is True
        assert c._pieces.get("d5") == "white"

    @pytest.mark.asyncio
    async def test_scan_reflects_game_state(self):
        """After moves, scan event should match updated piece map."""
        c = MockJsonLineClient()
        await c.start()
        svc = MotionService(serial=c)

        events = []

        async def cb(e):
            events.append(e)

        c.set_event_callback(cb)
        await svc.move_square_to_square("e2", "e4")
        events.clear()
        await svc.scan(full=True)

        scan = next(e for e in events if e.get("type") == "scan")
        assert scan["cells"]["e4"]["o"] == 1
        assert scan["cells"]["e2"]["o"] == 0

    @pytest.mark.asyncio
    async def test_fools_mate_all_moves_execute(self):
        from host.app.domain.game_state import GameState

        c = MockJsonLineClient()
        await c.start()
        svc = MotionService(serial=c)
        game = GameState()

        move_pairs = [("f2", "f3"), ("e7", "e5"), ("g2", "g4"), ("d8", "h4")]
        for src, dst in move_pairs:
            game.push_uci(f"{src}{dst}")
            r = await svc.move_square_to_square(src, dst)
            assert r.ok is True

        assert game.snapshot()["is_game_over"] is True
        assert game.snapshot()["result"] == "0-1"
