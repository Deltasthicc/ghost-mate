import sys
from fastapi.testclient import TestClient
from host.app.main import app

def check(condition, message):
    if not condition:
        raise AssertionError(message)

with TestClient(app) as client:
    checks = [
        ("GET /", client.get("/")),
        ("GET /static/style.css", client.get("/static/style.css")),
        ("GET /static/app.js", client.get("/static/app.js")),
        ("GET /api/health", client.get("/api/health")),
        ("GET /api/state", client.get("/api/state")),
        ("POST /api/game/new", client.post("/api/game/new")),
        ("POST /api/move/human e2e4", client.post("/api/move/human", json={"uci": "e2e4"})),
        ("POST /api/hardware/scan", client.post("/api/hardware/scan")),
        ("GET /api/board/snapshot", client.get("/api/board/snapshot")),
        ("POST /api/hardware/home", client.post("/api/hardware/home")),
        ("POST /api/hardware/park", client.post("/api/hardware/park")),
    ]

    for name, response in checks:
        print(f"{name}: {response.status_code}")
        check(response.status_code < 400, f"{name} failed: {response.text[:500]}")

    html = checks[0][1].text
    css = checks[1][1].text
    js = checks[2][1].text

    check("Autonomous Chess Robot Control" in html, "Homepage HTML missing title")
    check("grid-template-rows: repeat(8" in css, "CSS missing board row fix")
    check("window.addEventListener" in js, "JS missing boot listener")

print("✅ All smoke checks passed. Site should load at http://127.0.0.1:8000")
