"""
Comprehensive tests for the remaining host modules:
- SquareMapper (square→mm coordinate translation, capture slots)
- SafetyMonitor (motion gate, fault handling)
- BoardResync (expected vs physical occupancy)
- BoardCalibration / SquareCalibration (ADC classify)
- RulesService (static chess rule helpers)
- PgnStore (file I/O)
- PgnReplay (load moves from PGN file)
- EventBus (async pub/sub)
- CommandReply and MockJsonLineClient protocol
"""
from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

import chess
import chess.pgn
import pytest

from host.app.hardware.board_sensor import BoardSnapshot, CellState
from host.app.hardware.square_mapper import SquareMapper, XY
from host.app.hardware.safety_monitor import SafetyMonitor
from host.app.hardware.serial_link import CommandReply, MockJsonLineClient
from host.app.domain.board_resync import BoardResync
from host.app.domain.calibration import BoardCalibration, SquareCalibration
from host.app.domain.events import Event, EventBus, EventType
from host.app.chesscore.rules import RulesService
from host.app.chesscore.pgn_store import PgnStore
from host.app.chesscore.replay import PgnReplay
from host.tests.conftest import snapshot_from_board


# ══════════════════════════════════════════════════════════════════════════════
# SquareMapper
# ══════════════════════════════════════════════════════════════════════════════

class TestSquareMapper:
    def test_a1_is_at_origin_offset(self):
        m = SquareMapper(square_size_mm=50.0, origin_x_mm=0.0, origin_y_mm=0.0)
        xy = m.square_to_xy("a1")
        assert xy.x_mm == pytest.approx(25.0)
        assert xy.y_mm == pytest.approx(25.0)

    def test_h8_is_at_far_corner(self):
        m = SquareMapper(square_size_mm=50.0, origin_x_mm=0.0, origin_y_mm=0.0)
        xy = m.square_to_xy("h8")
        assert xy.x_mm == pytest.approx(375.0)
        assert xy.y_mm == pytest.approx(375.0)

    def test_e4_center_correct(self):
        m = SquareMapper(square_size_mm=50.0, origin_x_mm=0.0, origin_y_mm=0.0)
        xy = m.square_to_xy("e4")
        # e = index 4, so x = (4+0.5)*50 = 225; rank 4 = index 3, y = (3+0.5)*50 = 175
        assert xy.x_mm == pytest.approx(225.0)
        assert xy.y_mm == pytest.approx(175.0)

    def test_all_64_squares_return_xy(self):
        m = SquareMapper()
        centers = m.all_square_centers()
        assert len(centers) == 64
        for sq, xy in centers.items():
            assert isinstance(xy, XY)
            assert xy.x_mm > 0
            assert xy.y_mm > 0

    def test_all_squares_have_unique_coordinates(self):
        m = SquareMapper()
        positions = list(m.all_square_centers().values())
        coords = [(p.x_mm, p.y_mm) for p in positions]
        assert len(coords) == len(set(coords))

    def test_invalid_square_raises(self):
        m = SquareMapper()
        with pytest.raises(ValueError):
            m.square_to_xy("z9")

    def test_invalid_square_empty_string_raises(self):
        m = SquareMapper()
        with pytest.raises(ValueError):
            m.square_to_xy("")

    def test_invalid_square_too_long_raises(self):
        m = SquareMapper()
        with pytest.raises(ValueError):
            m.square_to_xy("e44")

    def test_square_size_scales_coordinates(self):
        m40 = SquareMapper(square_size_mm=40.0)
        m50 = SquareMapper(square_size_mm=50.0)
        xy40 = m40.square_to_xy("h8")
        xy50 = m50.square_to_xy("h8")
        ratio = xy50.x_mm / xy40.x_mm
        assert ratio == pytest.approx(50 / 40)

    def test_origin_offset_shifts_all_squares(self):
        m_zero = SquareMapper(square_size_mm=50.0, origin_x_mm=0.0, origin_y_mm=0.0)
        m_off = SquareMapper(square_size_mm=50.0, origin_x_mm=10.0, origin_y_mm=20.0)
        xy_zero = m_zero.square_to_xy("c3")
        xy_off = m_off.square_to_xy("c3")
        assert xy_off.x_mm == pytest.approx(xy_zero.x_mm + 10.0)
        assert xy_off.y_mm == pytest.approx(xy_zero.y_mm + 20.0)

    def test_capture_slot_white_left_side(self):
        m = SquareMapper(square_size_mm=50.0, capture_left_x_mm=-60.0)
        xy = m.capture_slot_xy("white", 0)
        assert xy.x_mm == pytest.approx(-60.0)
        assert xy.y_mm == pytest.approx(25.0)

    def test_capture_slot_black_right_side(self):
        m = SquareMapper(square_size_mm=50.0, capture_right_x_mm=460.0)
        xy = m.capture_slot_xy("black", 0)
        assert xy.x_mm == pytest.approx(460.0)

    def test_capture_slot_wraps_every_8(self):
        m = SquareMapper(square_size_mm=50.0)
        xy0 = m.capture_slot_xy("white", 0)
        xy8 = m.capture_slot_xy("white", 8)
        assert xy0.y_mm == pytest.approx(xy8.y_mm)

    def test_capture_slot_negative_index_raises(self):
        m = SquareMapper()
        with pytest.raises(ValueError):
            m.capture_slot_xy("white", -1)

    def test_capture_slot_case_insensitive(self):
        m = SquareMapper()
        xy_lower = m.capture_slot_xy("white", 2)
        xy_upper = m.capture_slot_xy("WHITE", 2)
        assert xy_lower.x_mm == pytest.approx(xy_upper.x_mm)

    def test_adjacent_squares_are_one_square_size_apart(self):
        m = SquareMapper(square_size_mm=50.0)
        a1 = m.square_to_xy("a1")
        b1 = m.square_to_xy("b1")
        assert (b1.x_mm - a1.x_mm) == pytest.approx(50.0)
        assert b1.y_mm == pytest.approx(a1.y_mm)

    def test_vertically_adjacent_squares(self):
        m = SquareMapper(square_size_mm=50.0)
        a1 = m.square_to_xy("a1")
        a2 = m.square_to_xy("a2")
        assert a1.x_mm == pytest.approx(a2.x_mm)
        assert (a2.y_mm - a1.y_mm) == pytest.approx(50.0)


# ══════════════════════════════════════════════════════════════════════════════
# SafetyMonitor
# ══════════════════════════════════════════════════════════════════════════════

class TestSafetyMonitor:
    def test_initial_state(self):
        sm = SafetyMonitor()
        assert sm.homed is False
        assert sm.robot_busy is False
        assert sm.electromagnet_on is False
        assert sm.fault_code is None

    def test_assert_can_move_raises_if_not_homed(self):
        sm = SafetyMonitor()
        with pytest.raises(RuntimeError, match="hom"):
            sm.assert_can_move()

    def test_assert_can_move_raises_if_busy(self):
        sm = SafetyMonitor()
        sm.homed = True
        sm.robot_busy = True
        with pytest.raises(RuntimeError, match="busy"):
            sm.assert_can_move()

    def test_assert_can_move_raises_if_fault_active(self):
        sm = SafetyMonitor()
        sm.homed = True
        sm.set_fault("pickup_lost")
        with pytest.raises(RuntimeError, match="fault"):
            sm.assert_can_move()

    def test_assert_can_move_passes_when_ready(self):
        sm = SafetyMonitor()
        sm.homed = True
        sm.assert_can_move()  # must not raise

    def test_set_fault_stores_code(self):
        sm = SafetyMonitor()
        sm.set_fault("motor_stall")
        assert sm.fault_code == "motor_stall"

    def test_set_fault_clears_busy(self):
        sm = SafetyMonitor()
        sm.robot_busy = True
        sm.set_fault("motor_stall")
        assert sm.robot_busy is False

    def test_set_fault_turns_off_electromagnet(self):
        sm = SafetyMonitor()
        sm.electromagnet_on = True
        sm.set_fault("motor_stall")
        assert sm.electromagnet_on is False

    def test_clear_fault_removes_code(self):
        sm = SafetyMonitor()
        sm.set_fault("motor_stall")
        sm.clear_fault()
        assert sm.fault_code is None

    def test_clear_fault_allows_movement_after_homing(self):
        sm = SafetyMonitor()
        sm.homed = True
        sm.set_fault("motor_stall")
        sm.clear_fault()
        sm.assert_can_move()  # must not raise

    def test_set_multiple_faults_last_wins(self):
        sm = SafetyMonitor()
        sm.set_fault("fault_a")
        sm.set_fault("fault_b")
        assert sm.fault_code == "fault_b"

    def test_clear_fault_when_no_fault_is_noop(self):
        sm = SafetyMonitor()
        sm.clear_fault()
        assert sm.fault_code is None


# ══════════════════════════════════════════════════════════════════════════════
# BoardResync
# ══════════════════════════════════════════════════════════════════════════════

class TestBoardResync:
    def test_start_position_no_mismatch(self):
        board = chess.Board()
        snap = snapshot_from_board(board)
        result = BoardResync().mismatch(board, snap)
        assert result["missing_on_board"] == []
        assert result["extra_on_board"] == []

    def test_missing_piece_detected(self):
        board = chess.Board()
        snap = snapshot_from_board(board)
        snap.cells["e2"] = CellState(False, 0, 0)  # white pawn missing
        result = BoardResync().mismatch(board, snap)
        assert "e2" in result["missing_on_board"]
        assert result["extra_on_board"] == []

    def test_extra_piece_detected(self):
        board = chess.Board()
        snap = snapshot_from_board(board)
        snap.cells["e4"] = CellState(True, -1, 800)  # phantom piece
        result = BoardResync().mismatch(board, snap)
        assert "e4" in result["extra_on_board"]
        assert result["missing_on_board"] == []

    def test_piece_moved_shows_as_both_missing_and_extra(self):
        board = chess.Board()
        snap = snapshot_from_board(board)
        snap.cells["e2"] = CellState(False, 0, 0)  # e2 vacated
        snap.cells["e5"] = CellState(True, -1, 800)  # e5 filled (illegal teleport)
        result = BoardResync().mismatch(board, snap)
        assert "e2" in result["missing_on_board"]
        assert "e5" in result["extra_on_board"]

    def test_empty_board_vs_starting_snap(self):
        board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        snap = snapshot_from_board(chess.Board())  # starting position snapshot
        result = BoardResync().mismatch(board, snap)
        assert len(result["extra_on_board"]) == 30  # 32 - 2 kings

    def test_expected_occupied_squares_starting_position(self):
        board = chess.Board()
        expected = BoardResync.expected_occupied_squares(board)
        assert len(expected) == 32

    def test_physical_occupied_squares_from_snapshot(self):
        snap = snapshot_from_board(chess.Board())
        physical = BoardResync.physical_occupied_squares(snap)
        assert len(physical) == 32

    def test_sorted_output(self):
        board = chess.Board()
        snap = snapshot_from_board(board)
        snap.cells["e2"] = CellState(False, 0, 0)
        snap.cells["d2"] = CellState(False, 0, 0)
        result = BoardResync().mismatch(board, snap)
        assert result["missing_on_board"] == sorted(result["missing_on_board"])


# ══════════════════════════════════════════════════════════════════════════════
# BoardCalibration / SquareCalibration
# ══════════════════════════════════════════════════════════════════════════════

class TestSquareCalibration:
    def test_above_threshold_is_occupied(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 + 200)  # +200 delta
        assert result["o"] == 1

    def test_below_threshold_is_empty(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 + 50)  # +50 delta — below threshold
        assert result["o"] == 0

    def test_exactly_at_threshold_is_occupied(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 + 120)
        assert result["o"] == 1

    def test_negative_delta_negative_polarity(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 - 200)  # white piece (north pole)
        assert result["p"] == -1
        assert result["o"] == 1

    def test_positive_delta_positive_polarity(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 + 200)  # black piece (south pole)
        assert result["p"] == 1
        assert result["o"] == 1

    def test_empty_square_zero_polarity(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 + 30)
        assert result["p"] == 0
        assert result["o"] == 0

    def test_magnitude_is_absolute_delta(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 - 300)
        assert result["m"] == 300

    def test_magnitude_positive_case(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 + 400)
        assert result["m"] == 400

    def test_empty_returns_zero_magnitude(self):
        cal = SquareCalibration(baseline=2048, occupancy_threshold=120)
        result = cal.classify(2048 + 10)
        assert result["m"] == 10  # magnitude is always abs(delta) regardless of threshold


class TestBoardCalibration:
    def test_default_has_64_squares(self):
        cal = BoardCalibration()
        assert len(cal.squares) == 64

    def test_classify_scan_returns_64_cells(self):
        cal = BoardCalibration()
        raw = {f"{f}{r}": 2048 for r in "12345678" for f in "abcdefgh"}
        result = cal.classify_scan(raw)
        assert len(result) == 64

    def test_classify_scan_strong_signal_occupied(self):
        cal = BoardCalibration()
        raw = {f"{f}{r}": 2048 for r in "12345678" for f in "abcdefgh"}
        raw["e4"] = 2048 + 500  # strong signal
        result = cal.classify_scan(raw)
        assert result["e4"]["o"] == 1

    def test_classify_scan_weak_signal_empty(self):
        cal = BoardCalibration()
        raw = {f"{f}{r}": 2048 for r in "12345678" for f in "abcdefgh"}
        raw["e4"] = 2048 + 50  # noise level
        result = cal.classify_scan(raw)
        assert result["e4"]["o"] == 0

    def test_to_payload_and_from_payload_round_trip(self):
        cal = BoardCalibration()
        cal.squares["e4"] = SquareCalibration(baseline=2000, occupancy_threshold=100)
        payload = cal.to_payload()
        restored = BoardCalibration.from_payload(payload)
        assert restored.squares["e4"].baseline == 2000
        assert restored.squares["e4"].occupancy_threshold == 100

    def test_from_payload_empty_dict_gives_defaults(self):
        cal = BoardCalibration.from_payload({})
        # All squares should have default calibration
        assert all(sq.baseline == 2048 for sq in cal.squares.values())

    def test_from_payload_partial_squares(self):
        payload = {"squares": {"a1": {"baseline": 1500, "occupancy_threshold": 80,
                                      "white_polarity_negative": True}}}
        cal = BoardCalibration.from_payload(payload)
        assert cal.squares["a1"].baseline == 1500
        assert cal.squares["e4"].baseline == 2048  # default


# ══════════════════════════════════════════════════════════════════════════════
# RulesService
# ══════════════════════════════════════════════════════════════════════════════

class TestRulesService:
    def test_legal_move_is_legal(self):
        assert RulesService.is_legal(chess.Board().fen(), "e2e4") is True

    def test_illegal_move_is_not_legal(self):
        assert RulesService.is_legal(chess.Board().fen(), "e2e5") is False

    def test_invalid_uci_string_returns_false(self):
        assert RulesService.is_legal(chess.Board().fen(), "zzzzz") is False

    def test_empty_uci_returns_false(self):
        assert RulesService.is_legal(chess.Board().fen(), "") is False

    def test_legal_moves_starting_count(self):
        moves = RulesService.legal_moves(chess.Board().fen())
        assert len(moves) == 20

    def test_legal_moves_returns_strings(self):
        moves = RulesService.legal_moves(chess.Board().fen())
        assert all(isinstance(m, str) for m in moves)

    def test_apply_move_returns_new_fen(self):
        fen = chess.Board().fen()
        new_fen = RulesService.apply_move(fen, "e2e4")
        assert new_fen != fen
        assert "4P3" in new_fen

    def test_apply_illegal_move_raises(self):
        fen = chess.Board().fen()
        with pytest.raises(ValueError):
            RulesService.apply_move(fen, "e2e5")

    def test_apply_castling(self):
        fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
        new_fen = RulesService.apply_move(fen, "e1g1")
        board = chess.Board(new_fen)
        assert board.piece_at(chess.G1).symbol() == "K"

    def test_apply_en_passant(self):
        fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
        new_fen = RulesService.apply_move(fen, "e5d6")
        board = chess.Board(new_fen)
        assert board.piece_at(chess.D6).symbol() == "P"
        assert board.piece_at(chess.D5) is None

    def test_apply_promotion(self):
        fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
        new_fen = RulesService.apply_move(fen, "a7a8q")
        board = chess.Board(new_fen)
        assert board.piece_at(chess.A8).symbol() == "Q"

    def test_legal_moves_checkmate_position_is_empty(self):
        # Fool's mate final position
        fen = "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
        board = chess.Board(fen)
        if board.is_checkmate():
            moves = RulesService.legal_moves(fen)
            assert moves == []

    def test_legal_moves_stalemate_is_empty(self):
        fen = "7k/8/6Q1/8/8/8/8/K7 b - - 0 1"
        moves = RulesService.legal_moves(fen)
        assert moves == []


# ══════════════════════════════════════════════════════════════════════════════
# PgnStore
# ══════════════════════════════════════════════════════════════════════════════

class TestPgnStore:
    def test_save_game_creates_file(self, tmp_path):
        store = PgnStore(directory=tmp_path)
        game = chess.pgn.Game()
        path = store.save_game(game, "test-game-001")
        assert path.exists()

    def test_save_game_path_includes_game_id(self, tmp_path):
        store = PgnStore(directory=tmp_path)
        game = chess.pgn.Game()
        path = store.save_game(game, "my-game-xyz")
        assert "my-game-xyz" in path.name

    def test_save_game_file_has_pgn_extension(self, tmp_path):
        store = PgnStore(directory=tmp_path)
        game = chess.pgn.Game()
        path = store.save_game(game, "game-1")
        assert path.suffix == ".pgn"

    def test_save_game_with_moves(self, tmp_path):
        store = PgnStore(directory=tmp_path)
        game = chess.pgn.Game()
        node = game
        board = chess.Board()
        for uci in ["e2e4", "e7e5", "g1f3"]:
            move = chess.Move.from_uci(uci)
            node = node.add_variation(move)
            board.push(move)
        path = store.save_game(game, "game-with-moves")
        content = path.read_text()
        assert "e4" in content

    def test_save_game_creates_directory_if_missing(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        store = PgnStore(directory=nested)
        game = chess.pgn.Game()
        path = store.save_game(game, "test")
        assert path.exists()

    def test_save_game_returns_path_object(self, tmp_path):
        store = PgnStore(directory=tmp_path)
        path = store.save_game(chess.pgn.Game(), "x")
        assert isinstance(path, Path)

    def test_overwrite_same_game_id(self, tmp_path):
        store = PgnStore(directory=tmp_path)
        game1 = chess.pgn.Game()
        game1.headers["Event"] = "First"
        store.save_game(game1, "same-id")
        game2 = chess.pgn.Game()
        game2.headers["Event"] = "Second"
        store.save_game(game2, "same-id")
        content = (tmp_path / "same-id.pgn").read_text()
        assert "Second" in content


# ══════════════════════════════════════════════════════════════════════════════
# PgnReplay
# ══════════════════════════════════════════════════════════════════════════════

class TestPgnReplay:
    def _write_pgn(self, path: Path, moves: list[str]) -> None:
        game = chess.pgn.Game()
        node = game
        board = chess.Board()
        for uci in moves:
            move = chess.Move.from_uci(uci)
            node = node.add_variation(move)
            board.push(move)
        path.write_text(str(game))

    def test_load_simple_game(self, tmp_path):
        moves = ["e2e4", "e7e5", "g1f3"]
        pgn_file = tmp_path / "test.pgn"
        self._write_pgn(pgn_file, moves)
        loaded = PgnReplay().load_moves(pgn_file)
        assert loaded == moves

    def test_load_empty_game(self, tmp_path):
        pgn_file = tmp_path / "empty.pgn"
        pgn_file.write_text(str(chess.pgn.Game()))
        loaded = PgnReplay().load_moves(pgn_file)
        assert loaded == []

    def test_load_game_with_castling(self, tmp_path):
        moves = ["e2e4", "e7e5", "f1c4", "b8c6", "g1f3", "g8f6", "e1g1"]
        pgn_file = tmp_path / "castle.pgn"
        self._write_pgn(pgn_file, moves)
        loaded = PgnReplay().load_moves(pgn_file)
        assert "e1g1" in loaded

    def test_load_game_with_en_passant(self, tmp_path):
        # Build directly with a position
        pgn = "[FEN \"8/8/8/3pP3/8/8/8/4K2k w - d6 0 1\"]\n\n1. exd6 *\n"
        pgn_file = tmp_path / "ep.pgn"
        pgn_file.write_text(pgn)
        loaded = PgnReplay().load_moves(pgn_file)
        assert loaded[0] == "e5d6"

    def test_load_promotion_game(self, tmp_path):
        pgn = "[FEN \"4k3/P7/8/8/8/8/8/4K3 w - - 0 1\"]\n\n1. a8=Q *\n"
        pgn_file = tmp_path / "promo.pgn"
        pgn_file.write_text(pgn)
        loaded = PgnReplay().load_moves(pgn_file)
        assert loaded[0] == "a7a8q"

    def test_load_fools_mate(self, tmp_path):
        moves = ["f2f3", "e7e5", "g2g4", "d8h4"]
        pgn_file = tmp_path / "fools.pgn"
        self._write_pgn(pgn_file, moves)
        loaded = PgnReplay().load_moves(pgn_file)
        assert loaded == moves

    def test_load_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(Exception):
            PgnReplay().load_moves(tmp_path / "no_such.pgn")

    def test_load_returns_list_of_strings(self, tmp_path):
        moves = ["e2e4", "d7d5"]
        pgn_file = tmp_path / "t.pgn"
        self._write_pgn(pgn_file, moves)
        loaded = PgnReplay().load_moves(pgn_file)
        assert all(isinstance(m, str) for m in loaded)


# ══════════════════════════════════════════════════════════════════════════════
# EventBus
# ══════════════════════════════════════════════════════════════════════════════

class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscriber_receives_published_event(self):
        bus = EventBus()
        queue = await bus.subscribe()
        event = Event(EventType.STATE_CHANGED, {"x": 1})
        await bus.publish(event)
        received = queue.get_nowait()
        assert received.type == EventType.STATE_CHANGED
        assert received.payload == {"x": 1}

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_receive(self):
        bus = EventBus()
        q1 = await bus.subscribe()
        q2 = await bus.subscribe()
        await bus.publish(Event(EventType.FAULT, {"code": "test"}))
        assert not q1.empty()
        assert not q2.empty()

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        bus = EventBus()
        queue = await bus.subscribe()
        await bus.unsubscribe(queue)
        await bus.publish(Event(EventType.STATE_CHANGED, {}))
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_publish_multiple_events_ordered(self):
        bus = EventBus()
        queue = await bus.subscribe()
        for i in range(5):
            await bus.publish(Event(EventType.STATE_CHANGED, {"i": i}))
        received = [queue.get_nowait() for _ in range(5)]
        assert [e.payload["i"] for e in received] == list(range(5))

    @pytest.mark.asyncio
    async def test_full_queue_drops_event_not_crash(self):
        bus = EventBus()
        queue = await bus.subscribe(maxsize=1)
        # Fill the queue
        await bus.publish(Event(EventType.STATE_CHANGED, {"a": 1}))
        # Second publish should not raise (dead queue is purged)
        await bus.publish(Event(EventType.STATE_CHANGED, {"b": 2}))

    @pytest.mark.asyncio
    async def test_no_subscribers_publish_is_noop(self):
        bus = EventBus()
        await bus.publish(Event(EventType.GAME_END, {}))  # must not raise

    @pytest.mark.asyncio
    async def test_event_types_all_valid(self):
        bus = EventBus()
        queue = await bus.subscribe()
        for et in EventType:
            await bus.publish(Event(et, {}))
        count = 0
        while not queue.empty():
            queue.get_nowait()
            count += 1
        assert count == len(EventType)

    def test_event_created_at_is_utc(self):
        from datetime import timezone
        event = Event(EventType.FAULT, {})
        assert event.created_at.tzinfo == timezone.utc

    def test_event_payload_defaults_to_empty_dict(self):
        event = Event(EventType.FAULT)
        assert event.payload == {}


# ══════════════════════════════════════════════════════════════════════════════
# MockJsonLineClient
# ══════════════════════════════════════════════════════════════════════════════

class TestMockJsonLineClient:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        client = MockJsonLineClient()
        await client.start()
        assert client._started is True
        await client.stop()
        assert client._started is False

    @pytest.mark.asyncio
    async def test_home_returns_ok(self):
        client = MockJsonLineClient()
        await client.start()
        reply = await client.send_command("home")
        assert reply.ok is True

    @pytest.mark.asyncio
    async def test_park_returns_ok(self):
        client = MockJsonLineClient()
        await client.start()
        reply = await client.send_command("park")
        assert reply.ok is True

    @pytest.mark.asyncio
    async def test_set_em_on_returns_ok(self):
        client = MockJsonLineClient()
        await client.start()
        reply = await client.send_command("set_em", on=True)
        assert reply.ok is True

    @pytest.mark.asyncio
    async def test_set_em_off_returns_ok(self):
        client = MockJsonLineClient()
        await client.start()
        reply = await client.send_command("set_em", on=False)
        assert reply.ok is True

    @pytest.mark.asyncio
    async def test_move_updates_piece_map(self):
        client = MockJsonLineClient()
        await client.start()
        reply = await client.send_command("move", **{"from": "e2", "to": "e4", "capture": False})
        assert reply.ok is True
        assert "e4" in client._pieces
        assert "e2" not in client._pieces

    @pytest.mark.asyncio
    async def test_capture_move_removes_victim(self):
        client = MockJsonLineClient()
        await client.start()
        # Set up: white pawn on e4, black pawn on d5
        client._pieces["e4"] = "white"
        client._pieces["d5"] = "black"
        reply = await client.send_command(
            "capture_move", victim="d5", **{"from": "e4", "to": "d5"}
        )
        assert reply.ok is True
        assert "d5" in client._pieces
        assert client._pieces["d5"] == "white"

    @pytest.mark.asyncio
    async def test_move_emits_motion_done_event(self):
        client = MockJsonLineClient()
        events = []
        client.set_event_callback(lambda e: events.append(e) or asyncio.sleep(0))
        await client.start()
        await client.send_command("move", **{"from": "e2", "to": "e4", "capture": False})
        motion_done_events = [e for e in events if e.get("type") == "motion_done"]
        assert len(motion_done_events) == 1

    @pytest.mark.asyncio
    async def test_scan_emits_scan_event(self):
        client = MockJsonLineClient()
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.start()
        await client.send_command("scan", full=True)
        scan_events = [e for e in events if e.get("type") == "scan"]
        assert len(scan_events) == 1

    @pytest.mark.asyncio
    async def test_scan_event_has_64_cells(self):
        client = MockJsonLineClient()
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.start()
        await client.send_command("scan", full=True)
        scan_event = next(e for e in events if e.get("type") == "scan")
        assert len(scan_event["cells"]) == 64

    @pytest.mark.asyncio
    async def test_starting_piece_map_has_32_pieces(self):
        client = MockJsonLineClient()
        assert len(client._pieces) == 32

    @pytest.mark.asyncio
    async def test_starting_piece_map_white_pieces_on_ranks_1_2(self):
        client = MockJsonLineClient()
        for file in "abcdefgh":
            assert client._pieces.get(f"{file}1") == "white"
            assert client._pieces.get(f"{file}2") == "white"

    @pytest.mark.asyncio
    async def test_starting_piece_map_black_pieces_on_ranks_7_8(self):
        client = MockJsonLineClient()
        for file in "abcdefgh":
            assert client._pieces.get(f"{file}7") == "black"
            assert client._pieces.get(f"{file}8") == "black"

    @pytest.mark.asyncio
    async def test_unknown_command_returns_not_ok(self):
        client = MockJsonLineClient()
        await client.start()
        reply = await client.send_command("nonexistent_cmd")
        assert reply.ok is False

    @pytest.mark.asyncio
    async def test_command_ids_increment(self):
        client = MockJsonLineClient()
        await client.start()
        r1 = await client.send_command("home")
        r2 = await client.send_command("park")
        assert r2.id == r1.id + 1

    @pytest.mark.asyncio
    async def test_scan_cells_correct_polarity_for_white(self):
        client = MockJsonLineClient()
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.start()
        await client.send_command("scan", full=True)
        scan_event = next(e for e in events if e.get("type") == "scan")
        cells = scan_event["cells"]
        # White pieces have negative polarity
        assert cells["e1"]["p"] == -1
        assert cells["e1"]["o"] == 1

    @pytest.mark.asyncio
    async def test_scan_cells_correct_polarity_for_black(self):
        client = MockJsonLineClient()
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.start()
        await client.send_command("scan", full=True)
        scan_event = next(e for e in events if e.get("type") == "scan")
        cells = scan_event["cells"]
        assert cells["e8"]["p"] == 1
        assert cells["e8"]["o"] == 1

    @pytest.mark.asyncio
    async def test_scan_empty_squares_have_zero_values(self):
        client = MockJsonLineClient()
        events = []

        async def cb(e):
            events.append(e)

        client.set_event_callback(cb)
        await client.start()
        await client.send_command("scan", full=True)
        scan_event = next(e for e in events if e.get("type") == "scan")
        cells = scan_event["cells"]
        # e4 is empty in starting position
        assert cells["e4"]["o"] == 0
        assert cells["e4"]["p"] == 0
        assert cells["e4"]["m"] == 0


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
