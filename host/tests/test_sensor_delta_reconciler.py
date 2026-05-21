import chess

from host.app.domain.move_reconciler import MoveReconciler
from host.app.hardware.board_sensor import BoardSnapshot, CellState


def snapshot_from_board(board: chess.Board) -> BoardSnapshot:
    cells = {}

    for square in chess.SQUARES:
        name = chess.square_name(square)
        piece = board.piece_at(square)

        if piece is None:
            cells[name] = CellState(False, 0, 0)
        else:
            polarity = -1 if piece.color == chess.WHITE else 1
            cells[name] = CellState(True, polarity, 800)

    return BoardSnapshot(cells=cells, ts_ms=1)


def reconcile_after_move(fen: str, uci: str):
    before_board = chess.Board(fen)
    after_board = chess.Board(fen)
    move = chess.Move.from_uci(uci)
    after_board.push(move)

    before = snapshot_from_board(before_board)
    after = snapshot_from_board(after_board)

    return MoveReconciler().reconcile(before_board, before, after)


def test_reconcile_simple_pawn_move():
    result = reconcile_after_move(chess.STARTING_FEN, "e2e4")

    assert result.move is not None
    assert result.move.uci() == "e2e4"
    assert result.confidence == 1.0


def test_reconcile_normal_capture():
    fen = "4k3/8/8/8/3p4/4P3/8/4K3 w - - 0 1"
    result = reconcile_after_move(fen, "e3d4")

    assert result.move is not None
    assert result.move.uci() == "e3d4"
    assert result.reason == "single legal occupancy match"


def test_reconcile_en_passant():
    fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
    result = reconcile_after_move(fen, "e5d6")

    assert result.move is not None
    assert result.move.uci() == "e5d6"
    assert result.confidence == 1.0


def test_reconcile_kingside_castling():
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    result = reconcile_after_move(fen, "e1g1")

    assert result.move is not None
    assert result.move.uci() == "e1g1"
    assert result.confidence == 1.0


def test_reconcile_queenside_castling():
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    result = reconcile_after_move(fen, "e1c1")

    assert result.move is not None
    assert result.move.uci() == "e1c1"
    assert result.confidence == 1.0


def test_reconcile_promotion_is_ambiguous_with_occupancy_only():
    fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
    result = reconcile_after_move(fen, "a7a8q")

    assert result.move is None
    assert result.confidence == 0.4
    assert result.reason == "multiple legal moves match occupancy"
    assert set(result.candidates) == {"a7a8q", "a7a8r", "a7a8b", "a7a8n"}


def test_reconcile_no_legal_sensor_delta_match():
    board = chess.Board()
    before = snapshot_from_board(board)
    after = snapshot_from_board(board)

    # Impossible sensor delta: remove a white rook without any legal move.
    after.cells["a1"] = CellState(False, 0, 0)

    result = MoveReconciler().reconcile(board, before, after)

    assert result.move is None
    assert result.confidence == 0.0
    assert result.reason == "no legal move matches sensor delta"
