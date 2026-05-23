"""Shared fixtures for the Ghost Mate comprehensive test suite."""
from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path

import chess
import pytest
from fastapi.testclient import TestClient

from host.app.domain.game_state import GameState
from host.app.hardware.board_sensor import BoardSnapshot, CellState
from host.app.domain.move_reconciler import MoveReconciler
from host.app.hardware.square_mapper import SquareMapper


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI client fixture (shared by all API and WebSocket tests)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    """Fresh TestClient for each test — lifespan runs in full."""
    from host.app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fresh_client(client):
    """Client with a guaranteed fresh game at start-of-test."""
    client.post("/api/game/new")
    return client


# ──────────────────────────────────────────────────────────────────────────────
# Domain-level helpers
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def game():
    return GameState()


@pytest.fixture()
def reconciler():
    return MoveReconciler()


@pytest.fixture()
def mapper():
    return SquareMapper()


# ──────────────────────────────────────────────────────────────────────────────
# Board-snapshot builders
# ──────────────────────────────────────────────────────────────────────────────

def snapshot_from_board(board: chess.Board) -> BoardSnapshot:
    """Build a BoardSnapshot from a python-chess Board (realistic polarity)."""
    cells: dict[str, CellState] = {}
    for sq in chess.SQUARES:
        name = chess.square_name(sq)
        piece = board.piece_at(sq)
        if piece is None:
            cells[name] = CellState(False, 0, 0)
        else:
            polarity = -1 if piece.color == chess.WHITE else 1
            cells[name] = CellState(True, polarity, 800)
    return BoardSnapshot(cells=cells, ts_ms=1)


def starting_snapshot() -> BoardSnapshot:
    return snapshot_from_board(chess.Board())


def reconcile_move(fen: str, uci: str) -> "ReconcileResult":
    """Helper: build before/after snapshots for a given move and reconcile."""
    before_board = chess.Board(fen)
    after_board = chess.Board(fen)
    after_board.push(chess.Move.from_uci(uci))
    before = snapshot_from_board(before_board)
    after = snapshot_from_board(after_board)
    return MoveReconciler().reconcile(before_board, before, after)


@pytest.fixture()
def tmp_pgn_dir(tmp_path):
    return tmp_path
