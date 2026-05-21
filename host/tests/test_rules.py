from host.app.chesscore.rules import RulesService


def test_start_position_has_e2e4():
    import chess
    fen = chess.Board().fen()
    assert RulesService.is_legal(fen, "e2e4")
    assert not RulesService.is_legal(fen, "e2e5")
