from __future__ import annotations

import chess


class RulesService:
    @staticmethod
    def legal_moves(fen: str) -> list[str]:
        board = chess.Board(fen)
        return [m.uci() for m in board.legal_moves]

    @staticmethod
    def is_legal(fen: str, uci: str) -> bool:
        board = chess.Board(fen)
        try:
            move = chess.Move.from_uci(uci)
        except ValueError:
            return False
        return move in board.legal_moves

    @staticmethod
    def apply_move(fen: str, uci: str) -> str:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"Illegal move: {uci}")
        board.push(move)
        return board.fen()
