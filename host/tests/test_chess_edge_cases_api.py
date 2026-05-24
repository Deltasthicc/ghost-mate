import chess
import pytest
from fastapi.testclient import TestClient

from host.app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def test_new_game_resets_game_id(client):
    first = client.post("/api/game/new").json()
    second = client.post("/api/game/new").json()

    assert first["game_id"] != second["game_id"]


def test_kingside_castling_via_api(client):
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    state = client.post("/api/game/new", params={"fen": fen}).json()

    assert "e1g1" in state["legal_moves"]

    after = client.post("/api/move/human", json={"uci": "e1g1"})
    assert after.status_code == 200

    board = chess.Board(after.json()["fen"])
    assert board.piece_at(chess.G1).symbol() == "K"
    assert board.piece_at(chess.F1).symbol() == "R"
    assert board.piece_at(chess.E1) is None
    assert board.piece_at(chess.H1) is None


def test_queenside_castling_via_api(client):
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    state = client.post("/api/game/new", params={"fen": fen}).json()

    assert "e1c1" in state["legal_moves"]

    after = client.post("/api/move/human", json={"uci": "e1c1"})
    assert after.status_code == 200

    board = chess.Board(after.json()["fen"])
    assert board.piece_at(chess.C1).symbol() == "K"
    assert board.piece_at(chess.D1).symbol() == "R"
    assert board.piece_at(chess.E1) is None
    assert board.piece_at(chess.A1) is None


def test_en_passant_via_api(client):
    fen = "8/8/8/3pP3/8/8/8/4K2k w - d6 0 1"
    state = client.post("/api/game/new", params={"fen": fen}).json()

    assert "e5d6" in state["legal_moves"]

    after = client.post("/api/move/human", json={"uci": "e5d6"})
    assert after.status_code == 200

    board = chess.Board(after.json()["fen"])
    assert board.piece_at(chess.D6).symbol() == "P"
    assert board.piece_at(chess.E5) is None
    assert board.piece_at(chess.D5) is None


def test_promotion_via_api(client):
    fen = "4k3/P7/8/8/8/8/8/4K3 w - - 0 1"
    state = client.post("/api/game/new", params={"fen": fen}).json()

    assert "a7a8q" in state["legal_moves"]

    after = client.post("/api/move/human", json={"uci": "a7a8q"})
    assert after.status_code == 200

    board = chess.Board(after.json()["fen"])
    assert board.piece_at(chess.A8).symbol() == "Q"
    assert board.piece_at(chess.A7) is None


def test_normal_capture_via_api(client):
    fen = "4k3/8/8/8/3p4/4P3/8/4K3 w - - 0 1"
    state = client.post("/api/game/new", params={"fen": fen}).json()

    assert "e3d4" in state["legal_moves"]

    after = client.post("/api/move/human", json={"uci": "e3d4"})
    assert after.status_code == 200

    board = chess.Board(after.json()["fen"])
    assert board.piece_at(chess.D4).symbol() == "P"
    assert board.piece_at(chess.E3) is None


def test_illegal_capture_attempt_is_rejected(client):
    client.post("/api/game/new")

    response = client.post("/api/move/human", json={"uci": "e2e5"})

    assert response.status_code == 400
    assert "Illegal move" in response.text


def test_invalid_uci_shape_is_rejected(client):
    client.post("/api/game/new")

    response = client.post("/api/move/human", json={"uci": "not-a-move"})

    assert response.status_code >= 400
