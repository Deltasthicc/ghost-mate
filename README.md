# Ghost Mate — Autonomous CoreXY Chess Robot

Ghost Mate is a pre-hardware software and firmware foundation for an autonomous CoreXY-based chess robot. It is designed to eventually control a physical robotic chessboard that can detect pieces, validate human moves, command an ESP32 motion controller, drive a CoreXY gantry, control an electromagnet or pickup mechanism, and expose everything through a live web dashboard.

The current version is built to run fully in **mock mode** before the real hardware is connected. That means the backend, UI, chess rules engine, WebSocket stream, mock serial protocol, sensor snapshot model, sensor-delta reconciliation, and ESP32 firmware build path can all be tested now without motors, Hall sensors, or an electromagnet.

---

## Current Status

The software side is currently **pre-hardware integration-ready**.

The following pieces are implemented and validated:

- FastAPI backend starts successfully.
- Default dashboard loads at `http://127.0.0.1:8000`.
- Static frontend assets load correctly.
- WebSocket connection opens successfully.
- `python-chess` validates all legal and illegal moves.
- Mock hardware layer supports:
  - Home
  - Park
  - Scan
  - Robot move commands
  - Mock firmware acknowledgements
- Mock Hall sensor snapshot returns all 64 squares.
- Mock sensor polarity is modeled:
  - White pieces: negative polarity
  - Black pieces: positive polarity
  - Empty squares: zero polarity
- Chess edge cases are tested:
  - Castling
  - En passant
  - Promotion
  - Captures
  - Illegal moves
  - Invalid UCI
  - SAN replay
  - Checkmate/result detection
- Sensor-delta reconciliation is tested for:
  - Simple moves
  - Captures
  - En passant
  - Castling
  - Promotion ambiguity
  - Impossible physical sensor deltas
- ESP32 firmware builds successfully through PlatformIO.

The remaining uncertainty is physical hardware behavior, not the core software flow. Real hardware still needs wiring, calibration, safety testing, and mechanical validation.

---

## Table of Contents

1. [Project Goal](#project-goal)
2. [Architecture](#architecture)
3. [Repository Structure](#repository-structure)
4. [Tech Stack](#tech-stack)
5. [Quick Start](#quick-start)
6. [Running the Default Dashboard](#running-the-default-dashboard)
7. [Dashboard Guide](#dashboard-guide)
8. [Backend API Guide](#backend-api-guide)
9. [Mock Hardware Mode](#mock-hardware-mode)
10. [Chess Rules Layer](#chess-rules-layer)
11. [Sensor Snapshot Model](#sensor-snapshot-model)
12. [Sensor-Delta Reconciliation](#sensor-delta-reconciliation)
13. [ESP32 Firmware Layer](#esp32-firmware-layer)
14. [Testing and Validation](#testing-and-validation)
15. [Software Readiness Check](#software-readiness-check)
16. [Hardware Integration Plan](#hardware-integration-plan)
17. [Calibration Plan](#calibration-plan)
18. [Troubleshooting](#troubleshooting)
19. [Development Workflow](#development-workflow)
20. [Git Workflow](#git-workflow)
21. [Known Limitations](#known-limitations)
22. [Future Improvements](#future-improvements)
23. [Safety Notes](#safety-notes)
24. [Final Pre-Hardware Checklist](#final-pre-hardware-checklist)

---

## Project Goal

The long-term goal of Ghost Mate is to build a physical chess-playing robot that can:

1. Detect the board state using sensors.
2. Infer a human move from physical board changes.
3. Validate that move using a chess rules engine.
4. Command a CoreXY gantry to move pieces.
5. Pick and drop pieces using a Z-axis and electromagnet/pickup system.
6. Handle captures and special chess moves.
7. Provide a clean operator dashboard for monitoring and control.
8. Eventually support local engine play, Lichess play, replay, calibration, and remote control.

The current project focuses on the software foundation. It is deliberately structured so that most backend and UI behavior can be tested before physical hardware is available.

---

## Architecture

Ghost Mate uses a split host-plus-firmware architecture.

```text
Browser Dashboard
        |
        | HTTP + WebSocket
        v
FastAPI Host Application
        |
        | Chess logic, move validation, sensor reconciliation
        |
        | JSON-line serial protocol
        v
ESP32 Firmware
        |
        | CoreXY motion, Z-axis, Hall sensors, electromagnet, endstops
        v
Physical Chess Robot
```

### Why this split matters

The host should handle high-level logic:

- Chess legality
- UI state
- Move interpretation
- PGN/SAN replay
- Sensor reconciliation
- Route orchestration
- WebSocket event broadcasting

The ESP32 should handle real-time hardware work:

- Step timing
- Motor movement
- Endstop readings
- Hall sensor scanning
- Electromagnet output
- Low-level safety checks

This keeps time-sensitive motor control away from the Python app and keeps complex chess/state logic away from firmware.

---

## Repository Structure

A simplified repository map:

```text
Ghost-mate/
├── README.md
├── pyproject.toml
├── .env.example
├── host/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── routes.py
│   │   │   └── ws.py
│   │   ├── chesscore/
│   │   │   ├── rules.py
│   │   │   ├── engine_service.py
│   │   │   ├── pgn_store.py
│   │   │   └── replay.py
│   │   ├── domain/
│   │   │   ├── game_state.py
│   │   │   ├── move_reconciler.py
│   │   │   ├── board_resync.py
│   │   │   ├── calibration.py
│   │   │   └── events.py
│   │   ├── hardware/
│   │   │   ├── serial_link.py
│   │   │   ├── motion_service.py
│   │   │   ├── board_sensor.py
│   │   │   ├── square_mapper.py
│   │   │   └── safety_monitor.py
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── session.py
│   │   ├── providers/
│   │   │   ├── base.py
│   │   │   ├── local_engine.py
│   │   │   ├── lichess_board.py
│   │   │   ├── lichess_bot.py
│   │   │   └── cloud_relay.py
│   │   └── ui/
│   │       ├── templates/
│   │       │   └── index.html
│   │       └── static/
│   │           ├── style.css
│   │           └── app.js
│   └── tests/
│       ├── test_full_stack_api.py
│       ├── test_chess_edge_cases_api.py
│       ├── test_pgn_replay_and_results.py
│       ├── test_sensor_delta_reconciler.py
│       ├── test_reconciler.py
│       └── test_rules.py
├── firmware/
│   └── esp32/
│       ├── platformio.ini
│       ├── include/
│       └── src/
├── scripts/
│   ├── smoke_check.py
│   ├── software_ready_check.py
│   ├── record_calibration.py
│   └── replay_pgn.py
├── docs/
├── cad/
└── electronics/
```

---

## Tech Stack

### Backend

- Python
- FastAPI
- Starlette
- Uvicorn
- Jinja2
- Pydantic
- SQLModel
- `python-chess`
- PySerial
- PySerial AsyncIO
- WebSockets

### Frontend

- HTML
- CSS
- Vanilla JavaScript
- Fetch API
- Browser WebSocket API

No frontend build tool is currently required.

### Firmware

- ESP32
- PlatformIO
- Arduino framework
- FastAccelStepper
- ArduinoJson

### Testing

- Pytest
- FastAPI TestClient
- Smoke check script
- Software readiness script
- PlatformIO firmware build

---

## Quick Start

These commands assume Windows PowerShell and VS Code.

### 1. Open the project folder

```powershell
cd C:\Users\shash\Downloads\Ghost-mate
```

### 2. Create a virtual environment

```powershell
python -m venv venv
```

### 3. Activate the virtual environment

```powershell
.\venv\Scripts\activate
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\venv\Scripts\activate
```

### 4. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install "uvicorn[standard]" jinja2 httpx
```

### 5. Create `.env`

```powershell
copy .env.example .env
```

### 6. Run the site

```powershell
uvicorn host.app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

---

## Running the Default Dashboard

Start the backend:

```powershell
uvicorn host.app.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000
```

If the browser still shows an old version, hard refresh:

```text
Ctrl + Shift + R
```

The dashboard should show:

- Header/hero section
- WebSocket status
- Host status
- Live chessboard
- Move input
- Legal move explorer
- Game state/FEN panel
- Hardware controls
- Robot move tester
- Hall matrix snapshot
- Live event console

---

## Dashboard Guide

### Live Chessboard

The chessboard is rendered from the current backend FEN string.

It supports:

- Piece display
- Click-to-select piece
- Click-to-target square
- Legal target highlighting
- Last move highlighting
- Board flipping
- Manual UCI move input

The board is forced into a true 8x8 grid using CSS:

```css
grid-template-columns: repeat(8, minmax(0, 1fr));
grid-template-rows: repeat(8, minmax(0, 1fr));
aspect-ratio: 1 / 1;
```

This prevents the uneven-square issue that can happen when piece content affects grid row height.

### Move Input

The move input accepts UCI notation:

```text
e2e4
g1f3
e7e8q
```

Promotion examples:

```text
a7a8q   promote to queen
a7a8r   promote to rook
a7a8b   promote to bishop
a7a8n   promote to knight
```

### Legal Move Explorer

The dashboard displays legal moves returned by the backend.

The frontend does not decide what is legal. The backend, through `python-chess`, is the authority.

### Game State Panel

The readable state panel shows:

- Game ID
- Check status
- FEN

The raw console can also display the full JSON state.

### Hardware Controls

The hardware control area includes:

- Home
- Park
- Scan
- Robot move test

In mock mode, these commands do not move physical hardware. They only test the software command path.

### Hall Matrix Snapshot

The Hall sensor grid shows the latest board sensor snapshot.

Each square contains:

```json
{
  "o": 1,
  "p": -1,
  "m": 800
}
```

Meaning:

```text
o = occupied flag
p = polarity
m = magnitude
```

Mock convention:

```text
White piece: p = -1
Black piece: p = 1
Empty square: p = 0
```

### Event Console

The event console shows live UI and WebSocket activity, such as:

- WebSocket connection
- New game
- Move accepted
- Move rejected
- Hardware command sent
- Scan event received
- Robot command sent

---

## Backend API Guide

### Health Check

```http
GET /api/health
```

PowerShell:

```powershell
curl.exe http://127.0.0.1:8000/api/health
```

Expected:

```json
{"status":"ok"}
```

---

### Current Game State

```http
GET /api/state
```

PowerShell:

```powershell
curl.exe http://127.0.0.1:8000/api/state
```

Returns:

```json
{
  "game_id": "game-...",
  "fen": "...",
  "turn": "white",
  "legal_moves": [],
  "is_check": false,
  "is_game_over": false,
  "result": null,
  "robot_busy": false,
  "last_error": null
}
```

---

### Start New Game

```http
POST /api/game/new
```

PowerShell:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/game/new"
```

Start from a custom FEN:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/game/new?fen=r3k2r/8/8/8/8/8/8/R3K2R%20w%20KQkq%20-%200%201"
```

---

### Submit Human Move

```http
POST /api/move/human
```

PowerShell:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/move/human" -H "Content-Type: application/json" --data-raw '{"uci":"e2e4"}'
```

Important PowerShell note: use single quotes around the JSON body.

---

### Robot Move Test

```http
POST /api/move/robot
```

PowerShell:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/move/robot" -H "Content-Type: application/json" --data-raw '{"source":"g1","target":"f3","capture":false}'
```

This tests the robot motion service path. It does not replace the chess legality system.

---

### Hardware Home

```http
POST /api/hardware/home
```

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/hardware/home"
```

---

### Hardware Park

```http
POST /api/hardware/park
```

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/hardware/park"
```

---

### Hardware Scan

```http
POST /api/hardware/scan
```

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/hardware/scan"
```

---

### Board Snapshot

```http
GET /api/board/snapshot
```

```powershell
curl.exe http://127.0.0.1:8000/api/board/snapshot
```

---

## Mock Hardware Mode

Mock mode exists so the software can be developed without hardware.

It simulates:

- Serial acknowledgements
- Motion completion events
- Board scan events
- Full 64-square occupancy grid
- White/black polarity
- Basic piece movement inside the fake hardware state

This lets the software prove:

- API routes work
- UI buttons work
- WebSocket events work
- Board snapshot format works
- Move reconciliation logic works
- Robot commands have a realistic reply shape

Mock mode is not real hardware validation. It does not prove motor direction, endstop polarity, sensor thresholds, electromagnet strength, or mechanical repeatability.

---

## Chess Rules Layer

The backend uses `python-chess` as the rules authority.

Main behavior:

- Legal moves are generated by the backend.
- Illegal moves are rejected.
- Game result is computed through the board state.
- Check and checkmate are detected.
- Custom FEN positions can be loaded for testing.
- SAN moves can be replayed.

The `GameState` object handles:

- `new_game()`
- `push_uci()`
- `push_san()`
- `legal_uci_moves()`
- `snapshot()`
- `result_if_game_over()`

Every new game receives a fresh `game_id`.

---

## Sensor Snapshot Model

The board sensor model represents each square as a cell:

```json
{
  "o": 1,
  "p": -1,
  "m": 800
}
```

Fields:

- `o`: occupied flag
- `p`: polarity
- `m`: magnitude

In real hardware, this will come from Hall sensor readings. In mock mode, it is generated from a fake board map.

---

## Sensor-Delta Reconciliation

The robot needs to infer human moves from physical board changes.

The general idea is:

```text
before snapshot + after snapshot + current legal moves = inferred move
```

The reconciler compares every legal move against the observed occupancy delta and picks the move that explains the sensor change.

Tested reconciliation cases:

- Simple pawn move
- Normal capture
- En passant
- Kingside castling
- Queenside castling
- Promotion ambiguity
- Impossible sensor delta

### Promotion ambiguity

With occupancy-only sensing, all of these can look the same:

```text
a7a8q
a7a8r
a7a8b
a7a8n
```

All four remove a pawn from `a7` and place a piece on `a8`.

That means the reconciler may correctly return:

```text
multiple legal moves match occupancy
```

This is expected. A real product should resolve this with:

- UI confirmation
- Default promotion to queen
- Piece-type classification
- Manual override
- Extra sensor information

---

## ESP32 Firmware Layer

The firmware is in:

```text
firmware/esp32/
```

Build it with:

```powershell
cd firmware\esp32
python -m platformio run
```

Or from the project root:

```powershell
python .\scripts\software_ready_check.py --firmware
```

The firmware currently targets:

```text
ESP32 Dev Module
Arduino framework
PlatformIO
```

Firmware responsibilities:

- Read JSON-line serial commands
- Send JSON-line acknowledgements
- Control CoreXY motion
- Control Z-axis/servo
- Control electromagnet output
- Scan Hall sensor matrix
- Monitor endstops
- Report safety/fault events

The firmware can build before hardware is connected. Actual movement must wait for wiring and safety validation.

---

## Testing and Validation

### Python compile check

```powershell
python -m compileall host scripts
```

### Pytest suite

```powershell
pytest -q
```

Expected current result:

```text
30 passed
```

The test suite covers:

- Static site loading
- Static asset loading
- API health
- Game state
- New game
- Legal moves
- Illegal moves
- Castling
- En passant
- Promotion
- Captures
- SAN replay
- Checkmate/result detection
- Mock hardware scan/home/park
- Board snapshot shape
- WebSocket hello event
- Sensor-delta reconciliation
- Promotion ambiguity
- Impossible sensor delta

### HTTP/API smoke check

```powershell
python .\scripts\smoke_check.py
```

This validates:

- `GET /`
- `GET /static/style.css`
- `GET /static/app.js`
- `GET /api/health`
- `GET /api/state`
- `POST /api/game/new`
- `POST /api/move/human`
- `POST /api/hardware/scan`
- `GET /api/board/snapshot`
- `POST /api/hardware/home`
- `POST /api/hardware/park`

### Full software readiness check

Without firmware:

```powershell
python .\scripts\software_ready_check.py
```

With firmware:

```powershell
python .\scripts\software_ready_check.py --firmware
```

This runs:

1. Python compile check
2. Pytest suite
3. HTTP/API smoke check
4. Optional ESP32 firmware build

Expected final message:

```text
SOFTWARE READINESS CHECK PASSED
```

---

## Software Readiness Check

Before committing major changes, run:

```powershell
python -m compileall host scripts
pytest -q
python .\scripts\smoke_check.py
python .\scripts\software_ready_check.py
python .\scripts\software_ready_check.py --firmware
```

If all pass, the software side is in a good state.

---

## Hardware Integration Plan

Do not connect motors or electromagnets directly without checks.

Before real movement:

1. Confirm ESP32 pin mapping.
2. Confirm motor driver wiring.
3. Confirm stepper current limits.
4. Confirm motor power supply rating.
5. Confirm common ground.
6. Confirm X-axis motor direction.
7. Confirm Y-axis motor direction.
8. Confirm CoreXY belt routing.
9. Confirm endstop wiring.
10. Confirm endstop polarity.
11. Confirm emergency stop behavior.
12. Confirm Hall sensor voltage levels.
13. Confirm Hall sensor baseline readings.
14. Confirm electromagnet MOSFET wiring.
15. Confirm flyback diode placement.
16. Confirm electromagnet current draw.
17. Confirm safe pickup/drop timing.
18. Test without chess pieces.
19. Test without electromagnet first.
20. Test slow single-axis motion before full XY movement.

---

## Calibration Plan

### Motion calibration

The robot must learn or be configured with:

- Board origin
- Square size/pitch
- Travel bounds
- Safe Z height
- Pickup Z height
- Drop Z height
- Capture zone
- Motor direction
- Steps per millimeter
- Maximum safe speed
- Maximum safe acceleration

### Square mapping

Each square must map to an XY coordinate.

Example:

```text
a1 -> x0, y0
b1 -> x0 + square_size, y0
a2 -> x0, y0 + square_size
```

The square mapper should eventually account for:

- Board rotation
- X/Y inversion
- Mechanical offsets
- Real measured square pitch
- Gantry origin
- Safe movement margins

### Sensor calibration

Hall sensors will need:

- Empty-board baseline readings
- White-piece readings
- Black-piece readings
- Per-square threshold values
- Noise filtering
- Occupancy threshold
- Polarity threshold
- Magnitude normalization

### Electromagnet calibration

The pickup system must be tested for:

- Reliable pickup
- Reliable drop
- Heat buildup
- Power draw
- Flyback diode protection
- Maximum safe activation time
- Sensor interference
- Piece alignment tolerance

---

## Troubleshooting

### Site does not open

Start the server:

```powershell
uvicorn host.app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

If port 8000 is stuck:

```powershell
$ports = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($ports) {
  $ports | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
  }
}
```

Then restart Uvicorn.

---

### Browser shows old UI

Hard refresh:

```text
Ctrl + Shift + R
```

---

### PowerShell curl JSON fails

Use:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/move/human" -H "Content-Type: application/json" --data-raw '{"uci":"e2e4"}'
```

Avoid:

```powershell
-d "{\"uci\":\"e2e4\"}"
```

PowerShell can parse escaped quotes strangely.

---

### Pytest collects backup files

Avoid backup files like:

```text
test_something.backup.py
```

Pytest may collect them.

Use:

```text
something.backup.txt
something.disabled
```

Or move backups outside `host/tests`.

---

### Favicon 404

This is harmless.

Browsers often request:

```text
/favicon.ico
```

If no favicon exists, the server logs a 404. The app still works.

---

### `pio` command not found

Use:

```powershell
python -m platformio run
```

instead of:

```powershell
pio run
```

Or install PlatformIO:

```powershell
python -m pip install -U platformio
```

---

### PlatformIO changes backend dependencies

If the environment gets weird after installing PlatformIO, reinstall backend dependencies:

```powershell
python -m pip install -e ".[dev]"
python -m pip install "uvicorn[standard]" jinja2 httpx
```

---

## Development Workflow

Recommended daily loop:

```powershell
.\venv\Scripts\activate
python -m compileall host scripts
pytest -q
python .\scripts\smoke_check.py
python .\scripts\software_ready_check.py
uvicorn host.app.main:app --reload
```

For firmware validation:

```powershell
python .\scripts\software_ready_check.py --firmware
```

---

## Git Workflow

Check status:

```powershell
git status
```

Add changes:

```powershell
git add .
```

Commit:

```powershell
git commit -m "Describe your change"
```

Push:

```powershell
git push
```

Remote repository:

```text
https://github.com/Deltasthicc/ghost-mate.git
```

Check remote:

```powershell
git remote -v
```

---

## Known Limitations

The system is strong in mock mode, but the following are not solved until physical hardware exists:

- Real Hall sensor thresholds
- Real magnetic piece classification
- Real electromagnet pickup/drop reliability
- Real CoreXY calibration
- Stepper motor direction
- Step loss detection
- Endstop debounce
- Capture-zone mechanics
- Collision avoidance around crowded board states
- Real serial latency under load
- Power rail noise
- Electromagnet heat and duty cycle
- Mechanical repeatability

Promotion ambiguity is expected with occupancy-only sensor deltas.

---

## Future Improvements

Good next software improvements:

- Promotion confirmation modal
- PGN export/download
- Move history panel
- Calibration dashboard
- Sensor heatmap
- Manual jog controls
- Hardware lock/unlock mode
- Real serial connection status
- Stockfish move suggestions
- Lichess integration
- Board replay mode
- Per-square sensor calibration storage
- Capture-zone path planning
- Movement queue visualization
- Startup hardware checklist
- Favicon and basic app branding assets

---

## Safety Notes

This project will involve moving belts, motors, magnets, powered coils, and possibly exposed electronics.

Important rules:

- Do not power motors without current limiting.
- Do not energize the electromagnet without a flyback diode.
- Do not touch belts or pulleys during motion.
- Do not test at full speed first.
- Do not leave the electromagnet energized continuously.
- Do not connect motor power to logic rails.
- Always verify common ground.
- Always verify supply voltages.
- Keep an emergency cutoff nearby.
- Test motion without chess pieces first.
- Test pickup/drop only after motion is reliable.

---

## Final Pre-Hardware Checklist

Before connecting physical hardware, this should pass:

```powershell
python .\scripts\software_ready_check.py --firmware
```

Expected:

```text
SOFTWARE READINESS CHECK PASSED
ESP32 firmware build passed
```

If this passes, software is ready for controlled hardware integration.

---

## Summary

Ghost Mate currently has a complete pre-hardware software foundation:

- FastAPI backend
- Interactive dashboard
- WebSocket live events
- Mock serial/hardware layer
- Chess rules engine
- Board sensor snapshot model
- Sensor-delta reconciliation
- Deep chess edge-case tests
- Full readiness checker
- ESP32 firmware build path

The next phase is hardware integration: wiring, calibration, real sensor readings, real motion, and safe physical testing.
