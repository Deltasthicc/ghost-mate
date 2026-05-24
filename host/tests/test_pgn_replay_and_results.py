import chess
import pytest

from host.app.domain.game_state import GameState


def test_san_replay_with_castling():
    game = GameState()

    for san in ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "O-O"]:
        game.push_san(san)

    assert game.board.piece_at(chess.G1).symbol() == "K"
    assert game.board.piece_at(chess.F1).symbol() == "R"
    assert game.board.turn == chess.BLACK


def test_fools_mate_result_detection():
    game = GameState()

    for san in ["f3", "e5", "g4", "Qh4#"]:
        game.push_san(san)

    snapshot = game.snapshot()

    assert snapshot["is_check"] is True
    assert snapshot["is_game_over"] is True
    assert snapshot["result"] == "0-1"


def test_san_illegal_move_rejected():
    game = GameState()

    with pytest.raises(ValueError):
        game.push_san("Qh5")
