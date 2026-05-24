import pytest
from fastapi.testclient import TestClient

from host.app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def assert_game_state_shape(state: dict) -> None:
    assert "game_id" in state
    assert "fen" in state
    assert "turn" in state
    assert state["turn"] in {"white", "black"}
    assert "legal_moves" in state
    assert isinstance(state["legal_moves"], list)
    assert "is_check" in state
    assert "is_game_over" in state
    assert "robot_busy" in state
    assert "last_error" in state


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Autonomous Chess Robot Control" in response.text
    assert "/static/style.css" in response.text
    assert "/static/app.js" in response.text


def test_static_assets_load(client):
    css = client.get("/static/style.css")
    js = client.get("/static/app.js")

    assert css.status_code == 200
    assert js.status_code == 200

    assert "grid-template-rows: repeat(8" in css.text
    assert "aspect-ratio: 1 / 1" in css.text
    assert "DOMContentLoaded" in js.text
    assert "UI boot failed" in js.text


def test_new_game_state_shape_and_starting_legal_moves(client):
    response = client.post("/api/game/new")
    assert response.status_code == 200

    state = response.json()
    assert_game_state_shape(state)
    assert state["turn"] == "white"
    assert "e2e4" in state["legal_moves"]
    assert "g1f3" in state["legal_moves"]


def test_legal_and_illegal_human_moves(client):
    client.post("/api/game/new")

    legal = client.post("/api/move/human", json={"uci": "e2e4"})
    assert legal.status_code == 200

    state = legal.json()
    assert_game_state_shape(state)
    assert state["turn"] == "black"
    assert "4P3" in state["fen"]

    illegal = client.post("/api/move/human", json={"uci": "e2e5"})
    assert illegal.status_code >= 400
    assert "Illegal move" in illegal.text


def test_knight_move_after_new_game(client):
    client.post("/api/game/new")

    response = client.post("/api/move/human", json={"uci": "g1f3"})
    assert response.status_code == 200

    state = response.json()
    assert_game_state_shape(state)
    assert "5N2" in state["fen"]
    assert state["turn"] == "black"


def test_hardware_home_park_scan_cycle(client):
    home = client.post("/api/hardware/home")
    park = client.post("/api/hardware/park")
    scan = client.post("/api/hardware/scan")

    assert home.status_code == 200
    assert park.status_code == 200
    assert scan.status_code == 200

    assert home.json()["ok"] is True
    assert park.json()["ok"] is True
    assert scan.json()["ok"] is True


def test_board_snapshot_shape_after_scan(client):
    client.post("/api/hardware/scan")

    response = client.get("/api/board/snapshot")
    assert response.status_code == 200

    snapshot = response.json()
    assert "ts_ms" in snapshot
    assert "cells" in snapshot

    cells = snapshot["cells"]
    assert isinstance(cells, dict)
    assert len(cells) == 64

    for square in ["a1", "h1", "a8", "h8", "e4"]:
        assert square in cells
        assert set(cells[square].keys()) >= {"o", "p", "m"}


def test_robot_move_mock_endpoint(client):
    client.post("/api/game/new")

    response = client.post(
        "/api/move/robot",
        json={"source": "g1", "target": "f3", "capture": False},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_websocket_hello_event(client):
    with client.websocket_connect("/ws") as websocket:
        data = websocket.receive_json()

    assert data["type"] == "HELLO"
    assert "state" in data
    assert_game_state_shape(data["state"])
