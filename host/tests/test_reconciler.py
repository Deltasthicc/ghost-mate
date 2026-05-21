import chess

from host.app.domain.move_reconciler import MoveReconciler
from host.app.hardware.board_sensor import BoardSnapshot, CellState


def start_snapshot():
    snap = BoardSnapshot.empty()
    occupied = {f"{f}2" for f in "abcdefgh"} | {f"{f}7" for f in "abcdefgh"} | set(
        ["a1", "b1", "c1", "d1", "e1", "f1", "g1", "h1", "a8", "b8", "c8", "d8", "e8", "f8", "g8", "h8"]
    )
    snap.cells = {sq: CellState(sq in occupied, 1 if sq in occupied else 0, 800 if sq in occupied else 0) for sq in snap.cells}
    return snap


def test_reconcile_e2e4():
    before = start_snapshot()
    after = start_snapshot()
    after.cells["e2"] = CellState(False, 0, 0)
    after.cells["e4"] = CellState(True, 1, 800)
    result = MoveReconciler().reconcile(chess.Board(), before, after)
    assert result.move is not None
    assert result.move.uci() == "e2e4"
