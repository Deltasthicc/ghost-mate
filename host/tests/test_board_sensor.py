"""
Comprehensive tests for host.app.hardware.board_sensor

Covers:
- CellState construction and from_protocol / to_protocol
- BoardSnapshot.empty()
- BoardSnapshot.from_scan_event() (both protocol variants)
- BoardSnapshot.occupied_squares()
- BoardSnapshot.diff()
- BoardSnapshot.to_payload()
- BoardSensorService.update_from_event()
- Edge cases: partial scan events, all-empty board, full board
"""
from __future__ import annotations

import time

import pytest

from host.app.hardware.board_sensor import BoardSnapshot, BoardSensorService, CellState


# ──────────────────────────────────────────────────────────────────────────────
# CellState
# ──────────────────────────────────────────────────────────────────────────────

class TestCellState:
    def test_basic_construction(self):
        c = CellState(True, -1, 750)
        assert c.occupied is True
        assert c.polarity == -1
        assert c.magnitude == 750

    def test_empty_cell(self):
        c = CellState(False, 0, 0)
        assert not c.occupied
        assert c.polarity == 0
        assert c.magnitude == 0

    def test_frozen_dataclass_immutable(self):
        c = CellState(True, 1, 600)
        with pytest.raises((AttributeError, TypeError)):
            c.occupied = False  # type: ignore[misc]

    def test_from_protocol_compact_keys(self):
        c = CellState.from_protocol({"o": 1, "p": -1, "m": 812})
        assert c.occupied is True
        assert c.polarity == -1
        assert c.magnitude == 812

    def test_from_protocol_verbose_keys(self):
        c = CellState.from_protocol({"occ": 1, "sign": 1, "mag": 500})
        assert c.occupied is True
        assert c.polarity == 1
        assert c.magnitude == 500

    def test_from_protocol_compact_takes_priority_over_verbose(self):
        c = CellState.from_protocol({"o": 0, "occ": 1, "p": -1, "sign": 1, "m": 100, "mag": 200})
        assert c.occupied is False  # "o" wins
        assert c.polarity == -1    # "p" wins
        assert c.magnitude == 100  # "m" wins

    def test_from_protocol_empty_dict_defaults_to_unoccupied(self):
        c = CellState.from_protocol({})
        assert not c.occupied
        assert c.polarity == 0
        assert c.magnitude == 0

    def test_from_protocol_zero_values(self):
        c = CellState.from_protocol({"o": 0, "p": 0, "m": 0})
        assert not c.occupied

    def test_to_protocol_returns_compact_keys(self):
        c = CellState(True, -1, 812)
        d = c.to_protocol()
        assert d == {"o": 1, "p": -1, "m": 812}

    def test_to_protocol_empty_cell(self):
        d = CellState(False, 0, 0).to_protocol()
        assert d == {"o": 0, "p": 0, "m": 0}

    def test_round_trip_via_protocol(self):
        original = CellState(True, 1, 650)
        restored = CellState.from_protocol(original.to_protocol())
        assert original == restored

    def test_equality(self):
        assert CellState(True, 1, 800) == CellState(True, 1, 800)
        assert CellState(True, 1, 800) != CellState(True, -1, 800)

    def test_polarity_positive_is_black(self):
        c = CellState.from_protocol({"o": 1, "p": 1, "m": 600})
        assert c.polarity == 1  # black piece convention

    def test_polarity_negative_is_white(self):
        c = CellState.from_protocol({"o": 1, "p": -1, "m": 600})
        assert c.polarity == -1  # white piece convention


# ──────────────────────────────────────────────────────────────────────────────
# BoardSnapshot.empty()
# ──────────────────────────────────────────────────────────────────────────────

class TestBoardSnapshotEmpty:
    def test_has_64_cells(self):
        snap = BoardSnapshot.empty()
        assert len(snap.cells) == 64

    def test_all_cells_unoccupied(self):
        snap = BoardSnapshot.empty()
        assert all(not c.occupied for c in snap.cells.values())

    def test_all_polarities_zero(self):
        snap = BoardSnapshot.empty()
        assert all(c.polarity == 0 for c in snap.cells.values())

    def test_all_magnitudes_zero(self):
        snap = BoardSnapshot.empty()
        assert all(c.magnitude == 0 for c in snap.cells.values())

    def test_contains_all_64_square_names(self):
        snap = BoardSnapshot.empty()
        for file in "abcdefgh":
            for rank in "12345678":
                assert f"{file}{rank}" in snap.cells

    def test_no_duplicate_squares(self):
        snap = BoardSnapshot.empty()
        assert len(snap.cells) == len(set(snap.cells.keys()))

    def test_ts_ms_is_set(self):
        before = int(time.time() * 1000)
        snap = BoardSnapshot.empty()
        after = int(time.time() * 1000)
        assert before <= snap.ts_ms <= after + 100


# ──────────────────────────────────────────────────────────────────────────────
# BoardSnapshot.from_scan_event()
# ──────────────────────────────────────────────────────────────────────────────

class TestBoardSnapshotFromScanEvent:
    def test_single_cell_update_compact(self):
        event = {"ts_ms": 1000, "cells": {"e4": {"o": 1, "p": -1, "m": 800}}}
        snap = BoardSnapshot.from_scan_event(event)
        assert snap.cells["e4"].occupied is True
        assert snap.cells["e4"].polarity == -1
        assert snap.cells["e4"].magnitude == 800

    def test_single_cell_update_verbose(self):
        event = {"ts_ms": 1000, "squares": {"d5": {"occ": 1, "sign": 1, "mag": 700}}}
        snap = BoardSnapshot.from_scan_event(event)
        assert snap.cells["d5"].occupied is True

    def test_timestamp_is_taken_from_event(self):
        event = {"ts_ms": 99999, "cells": {}}
        snap = BoardSnapshot.from_scan_event(event)
        assert snap.ts_ms == 99999

    def test_missing_timestamp_defaults_to_now(self):
        before = int(time.time() * 1000)
        snap = BoardSnapshot.from_scan_event({"cells": {}})
        after = int(time.time() * 1000)
        assert before <= snap.ts_ms <= after + 100

    def test_previous_snapshot_is_base(self):
        previous = BoardSnapshot.empty()
        previous.cells["a1"] = CellState(True, -1, 800)
        event = {"ts_ms": 2000, "cells": {"e4": {"o": 1, "p": -1, "m": 800}}}
        snap = BoardSnapshot.from_scan_event(event, previous=previous)
        # Both the old cell and the new cell should be in the new snapshot
        assert snap.cells["a1"].occupied is True
        assert snap.cells["e4"].occupied is True

    def test_event_overwrites_previous(self):
        previous = BoardSnapshot.empty()
        previous.cells["e4"] = CellState(True, -1, 800)
        event = {"ts_ms": 2000, "cells": {"e4": {"o": 0, "p": 0, "m": 0}}}
        snap = BoardSnapshot.from_scan_event(event, previous=previous)
        assert snap.cells["e4"].occupied is False

    def test_full_64_cell_scan_event(self):
        cells = {}
        for file in "abcdefgh":
            for rank in "12345678":
                cells[f"{file}{rank}"] = {"o": 0, "p": 0, "m": 0}
        event = {"ts_ms": 5000, "cells": cells}
        snap = BoardSnapshot.from_scan_event(event)
        assert len(snap.cells) == 64

    def test_none_previous_creates_empty_base(self):
        event = {"ts_ms": 1000, "cells": {"a1": {"o": 1, "p": -1, "m": 900}}}
        snap = BoardSnapshot.from_scan_event(event, previous=None)
        assert snap.cells["a1"].occupied is True
        assert not snap.cells["b1"].occupied  # all others default to empty

    def test_empty_cells_dict_leaves_board_unchanged(self):
        previous = BoardSnapshot.empty()
        previous.cells["h8"] = CellState(True, 1, 500)
        snap = BoardSnapshot.from_scan_event({"ts_ms": 1, "cells": {}}, previous=previous)
        assert snap.cells["h8"].occupied is True


# ──────────────────────────────────────────────────────────────────────────────
# BoardSnapshot.occupied_squares()
# ──────────────────────────────────────────────────────────────────────────────

class TestOccupiedSquares:
    def test_empty_board_has_no_occupied_squares(self):
        assert BoardSnapshot.empty().occupied_squares() == set()

    def test_one_occupied_square(self):
        snap = BoardSnapshot.empty()
        snap.cells["e4"] = CellState(True, -1, 800)
        assert snap.occupied_squares() == {"e4"}

    def test_starting_position_has_32_occupied(self):
        from host.tests.conftest import starting_snapshot
        snap = starting_snapshot()
        assert len(snap.occupied_squares()) == 32

    def test_occupied_squares_only_includes_occupied_cells(self):
        snap = BoardSnapshot.empty()
        snap.cells["a1"] = CellState(True, -1, 800)
        snap.cells["h8"] = CellState(True, 1, 700)
        occupied = snap.occupied_squares()
        assert "a1" in occupied
        assert "h8" in occupied
        assert "e4" not in occupied

    def test_starting_position_white_pieces(self):
        from host.tests.conftest import starting_snapshot
        snap = starting_snapshot()
        for file in "abcdefgh":
            assert f"{file}1" in snap.occupied_squares()
            assert f"{file}2" in snap.occupied_squares()

    def test_starting_position_black_pieces(self):
        from host.tests.conftest import starting_snapshot
        snap = starting_snapshot()
        for file in "abcdefgh":
            assert f"{file}7" in snap.occupied_squares()
            assert f"{file}8" in snap.occupied_squares()

    def test_starting_position_middle_ranks_empty(self):
        from host.tests.conftest import starting_snapshot
        snap = starting_snapshot()
        for file in "abcdefgh":
            for rank in "3456":
                assert f"{file}{rank}" not in snap.occupied_squares()


# ──────────────────────────────────────────────────────────────────────────────
# BoardSnapshot.diff()
# ──────────────────────────────────────────────────────────────────────────────

class TestBoardSnapshotDiff:
    def test_identical_snapshots_have_no_diff(self):
        snap = BoardSnapshot.empty()
        assert snap.diff(snap) == {}

    def test_single_square_change_detected(self):
        before = BoardSnapshot.empty()
        after = BoardSnapshot.empty()
        after.cells["e2"] = CellState(True, -1, 800)
        diff = before.diff(after)
        assert "e2" in diff

    def test_diff_captures_old_and_new_state(self):
        before = BoardSnapshot.empty()
        after = BoardSnapshot.empty()
        before.cells["e2"] = CellState(True, -1, 800)
        after.cells["e4"] = CellState(True, -1, 800)
        diff = before.diff(after)
        assert "e2" in diff
        assert "e4" in diff
        old_e2, new_e2 = diff["e2"]
        assert old_e2.occupied is True
        assert new_e2.occupied is False

    def test_two_square_move_produces_two_diffs(self):
        from host.tests.conftest import snapshot_from_board
        import chess
        board = chess.Board()
        before = snapshot_from_board(board)
        board.push(chess.Move.from_uci("e2e4"))
        after = snapshot_from_board(board)
        diff = before.diff(after)
        assert "e2" in diff
        assert "e4" in diff
        assert len(diff) == 2

    def test_castling_produces_four_diffs(self):
        from host.tests.conftest import snapshot_from_board
        import chess
        board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        before = snapshot_from_board(board)
        board.push(chess.Move.from_uci("e1g1"))
        after = snapshot_from_board(board)
        diff = before.diff(after)
        assert "e1" in diff
        assert "g1" in diff
        assert "h1" in diff
        assert "f1" in diff
        assert len(diff) == 4

    def test_diff_is_not_symmetric(self):
        before = BoardSnapshot.empty()
        after = BoardSnapshot.empty()
        after.cells["a1"] = CellState(True, -1, 800)
        d_ab = before.diff(after)
        d_ba = after.diff(before)
        # Both should see a1 as changed but with swapped old/new
        assert "a1" in d_ab
        assert "a1" in d_ba
        old_ab, new_ab = d_ab["a1"]
        old_ba, new_ba = d_ba["a1"]
        assert old_ab == new_ba
        assert new_ab == old_ba


# ──────────────────────────────────────────────────────────────────────────────
# BoardSnapshot.to_payload()
# ──────────────────────────────────────────────────────────────────────────────

class TestBoardSnapshotToPayload:
    def test_payload_has_ts_ms_key(self):
        snap = BoardSnapshot.empty()
        payload = snap.to_payload()
        assert "ts_ms" in payload

    def test_payload_has_cells_key(self):
        payload = BoardSnapshot.empty().to_payload()
        assert "cells" in payload

    def test_payload_cells_has_64_entries(self):
        payload = BoardSnapshot.empty().to_payload()
        assert len(payload["cells"]) == 64

    def test_payload_cell_has_protocol_keys(self):
        payload = BoardSnapshot.empty().to_payload()
        cell = payload["cells"]["e4"]
        assert set(cell.keys()) == {"o", "p", "m"}

    def test_payload_ts_ms_matches(self):
        snap = BoardSnapshot(cells=BoardSnapshot.empty().cells, ts_ms=12345)
        assert snap.to_payload()["ts_ms"] == 12345

    def test_payload_round_trips_via_from_scan_event(self):
        original = BoardSnapshot.empty()
        original.cells["e4"] = CellState(True, -1, 800)
        payload = original.to_payload()
        restored = BoardSnapshot.from_scan_event(payload)
        assert restored.cells["e4"].occupied is True
        assert restored.cells["e4"].polarity == -1


# ──────────────────────────────────────────────────────────────────────────────
# BoardSensorService
# ──────────────────────────────────────────────────────────────────────────────

class TestBoardSensorService:
    def test_initial_snapshot_is_empty(self):
        svc = BoardSensorService()
        assert svc.latest.occupied_squares() == set()

    def test_update_from_event_updates_latest(self):
        svc = BoardSensorService()
        event = {"ts_ms": 1000, "cells": {"e4": {"o": 1, "p": -1, "m": 800}}}
        svc.update_from_event(event)
        assert svc.latest.cells["e4"].occupied is True

    def test_update_from_event_returns_new_snapshot(self):
        svc = BoardSensorService()
        event = {"ts_ms": 1000, "cells": {"e4": {"o": 1, "p": -1, "m": 800}}}
        result = svc.update_from_event(event)
        assert result is svc.latest

    def test_successive_updates_accumulate(self):
        svc = BoardSensorService()
        svc.update_from_event({"ts_ms": 1, "cells": {"a1": {"o": 1, "p": -1, "m": 800}}})
        svc.update_from_event({"ts_ms": 2, "cells": {"h8": {"o": 1, "p": 1, "m": 700}}})
        assert svc.latest.cells["a1"].occupied is True
        assert svc.latest.cells["h8"].occupied is True

    def test_update_clears_cell(self):
        svc = BoardSensorService()
        svc.update_from_event({"ts_ms": 1, "cells": {"e4": {"o": 1, "p": -1, "m": 800}}})
        svc.update_from_event({"ts_ms": 2, "cells": {"e4": {"o": 0, "p": 0, "m": 0}}})
        assert not svc.latest.cells["e4"].occupied

    def test_empty_event_leaves_board_unchanged(self):
        svc = BoardSensorService()
        svc.update_from_event({"ts_ms": 1, "cells": {"d5": {"o": 1, "p": 1, "m": 600}}})
        svc.update_from_event({"ts_ms": 2, "cells": {}})
        assert svc.latest.cells["d5"].occupied is True

    def test_update_uses_verbose_key_fallback(self):
        svc = BoardSensorService()
        svc.update_from_event({"ts_ms": 1, "squares": {"c3": {"occ": 1, "sign": -1, "mag": 500}}})
        assert svc.latest.cells["c3"].occupied is True
