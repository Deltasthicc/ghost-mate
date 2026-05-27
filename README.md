# Ghost Mate — Autonomous CoreXY Chess Robot

> **Current state:** Raspberry Pi 4 host + Teensy 4.0 controller + full chess software stack working.  
> Dashboard at `http://192.168.1.4:8000` (or `http://127.0.0.1:8000` locally).  
> **859 automated tests pass.** Physical motors, Hall sensors, and electromagnet are **not wired yet**.

---

## Table of Contents

1. [What Ghost Mate Is](#1-what-ghost-mate-is)
2. [Architecture](#2-architecture)
3. [Project Structure](#3-project-structure)
4. [What Is Implemented (Complete Checklist)](#4-what-is-implemented-complete-checklist)
5. [Current Phase & Limitations](#5-current-phase--limitations)
6. [Hardware](#6-hardware)
7. [Software Stack](#7-software-stack)
8. [Installation & Setup](#8-installation--setup)
9. [Configuration (`.env`)](#9-configuration-env)
10. [Running the App](#10-running-the-app)
11. [Running Tests & Readiness Checks](#11-running-tests--readiness-checks)
12. [Web Dashboard](#12-web-dashboard)
13. [HTTP API Reference](#13-http-api-reference)
14. [WebSocket Events](#14-websocket-events)
15. [Stockfish Integration](#15-stockfish-integration)
16. [Move History & PGN](#16-move-history--pgn)
17. [AI Coach / LLM Layer](#17-ai-coach--llm-layer)
18. [Teensy 4.0 Firmware](#18-teensy-40-firmware)
19. [Serial Protocol](#19-serial-protocol)
20. [Domain Logic (Reconciler, Sensing, Safety)](#20-domain-logic-reconciler-sensing-safety)
21. [Future Game Modes (Skeleton)](#21-future-game-modes-skeleton)
22. [Scripts](#22-scripts)
23. [Documentation (`docs/`)](#23-documentation-docs)
24. [Safety](#24-safety)
25. [Recommended Hardware Bring-Up Order](#25-recommended-hardware-bring-up-order)
26. [Troubleshooting](#26-troubleshooting)
27. [Development Rules & Handoff Notes](#27-development-rules--handoff-notes)
28. [Migration Notes (ESP32 → Teensy 4.0)](#28-migration-notes-esp32--teensy-40)
29. [Final Checkpoint](#29-final-checkpoint)

---

## 1. What Ghost Mate Is

Ghost Mate is an autonomous chess robot built around a **split architecture**:

```text
Browser (laptop / phone)
        ↓  HTTP + WebSocket
Raspberry Pi 4 host
        ↓  Python · FastAPI · python-chess · Stockfish · SQLite
Teensy 4.0 controller  (USB serial, 115200 baud)
        ↓  CoreXY steppers · Hall matrix · Z servo · electromagnet
Physical chessboard robot
```

The Pi is the **brain** (rules, engine, UI, reconciliation). The Teensy is the **real-time controller** (motion pulses, sensor scanning, safety inputs). Chess legality always goes through **python-chess** on the host; the LLM coach is advisory only and never bypasses safety gates.

---

## 2. Architecture

| Layer | Responsibility |
|-------|----------------|
| **Browser UI** | Live board, Stockfish panel, move history, FEN/PGN tools, AI coach, hardware deck |
| **FastAPI host** | REST API, WebSocket event bus, game state, Stockfish service |
| **python-chess** | Authoritative rules, legality, FEN/PGN, move history |
| **Stockfish** | Persistent engine process, white-centric eval, MultiPV lines |
| **Serial link** | Newline-delimited JSON to/from Teensy (real or mock) |
| **Teensy firmware** | CoreXY motion, Hall scan, Z-axis, electromagnet, endstops, e-stop |
| **SQLite** | Optional persistence for games, moves, calibration records |

See also: [`docs/architecture.md`](docs/architecture.md)

---

## 3. Project Structure

```text
Ghost-mate/
├── README.md                 ← this file
├── OPTIMIZATIONS.md          ← performance pass notes
├── pyproject.toml            ← Python package + dependencies
├── .env / .env.example       ← runtime configuration
│
├── host/
│   ├── app/
│   │   ├── main.py           ← FastAPI factory, lifespan, live engine loop
│   │   ├── config.py         ← Pydantic settings
│   │   ├── api/
│   │   │   ├── routes.py     ← REST endpoints
│   │   │   └── ws.py         ← WebSocket /ws
│   │   ├── ai/
│   │   │   └── coach.py      ← LLM + local teaching fallback
│   │   ├── chesscore/
│   │   │   ├── engine_service.py  ← persistent Stockfish wrapper
│   │   │   ├── rules.py
│   │   │   ├── pgn_store.py
│   │   │   └── replay.py
│   │   ├── domain/
│   │   │   ├── game_state.py      ← authoritative chess state + history
│   │   │   ├── events.py          ← async pub/sub bus
│   │   │   ├── move_reconciler.py ← Hall delta → legal move
│   │   │   ├── board_resync.py
│   │   │   └── calibration.py
│   │   ├── hardware/
│   │   │   ├── serial_link.py     ← JSON-line Teensy transport (mock + real)
│   │   │   ├── motion_service.py
│   │   │   ├── board_sensor.py
│   │   │   ├── square_mapper.py
│   │   │   └── safety_monitor.py
│   │   ├── providers/             ← future Lichess / relay modes (skeleton)
│   │   ├── db/                    ← SQLModel persistence
│   │   └── ui/
│   │       ├── templates/index.html
│   │       └── static/app.js, style.css
│   └── tests/                     ← 859 pytest cases (22 test modules)
│
├── firmware/
│   └── teensy40/                  ← active PlatformIO project (Teensy 4.0 only)
│       ├── platformio.ini
│       ├── include/               ← config, corexy, hall_scan, protocol, safety, z_axis
│       └── src/                   ← main, corexy, hall_scan, protocol, safety, z_axis
│
├── scripts/                       ← readiness checks, dev launchers, firmware flash
└── docs/                          ← architecture, protocol, safety, calibration, modes
```

---

## 4. What Is Implemented (Complete Checklist)

### Host software — chess & game state

- [x] Authoritative in-memory game state backed by **python-chess**
- [x] Cached snapshots (no Stockfish spawn on every state poll)
- [x] `POST /api/game/new` with optional custom FEN
- [x] `POST /api/move/human` with UCI validation (case-insensitive, whitespace trimmed)
- [x] Full support for castling, en passant, promotion (e.g. `e7e8q`), checkmate detection
- [x] Material-only fallback evaluation in snapshots; live Stockfish eval via engine endpoints
- [x] **Move history** in every snapshot: ply, move number, color, UCI, SAN, FEN-after-move
- [x] **`GET /api/state/pgn`** — export current game line as PGN
- [x] **`POST /api/position/fen`** — load a FEN and play from that position
- [x] **`POST /api/position/pgn`** — load a PGN mainline **with full move stack preserved** (not just final FEN)
- [x] `start_fen` tracked for custom starting positions (PGN `SetUp` / FEN loads)

### Stockfish engine

- [x] **Persistent Stockfish process** (no per-request spawn; NNUE stays hot)
- [x] LRU analysis cache (~5000 positions)
- [x] **White-centric evaluation policy** (+ = White better, − = Black better, regardless of side to move)
- [x] MultiPV top-5 move lines with SAN, UCI, score, mate display, principal variation
- [x] `GET /api/engine/analysis` — legacy alias
- [x] `GET /api/engine/live` — depth-capped fresh analysis (`max_depth` clamped **1–30**)
- [x] `GET/POST /api/engine/settings` — live tuning for depth, search time, MultiPV lines, threads, and memory
- [x] `POST /api/engine/bestmove` — engine pick for robot play (future loop)
- [x] **Depth-driven live updates** over WebSocket (`ENGINE_UPDATE` events at depth 1, 2, … N)
- [x] Live engine loop idles when no WebSocket client opts in (`engine=1`)
- [x] Configurable: threads, hash, skill level, move time, live interval, max depth

### Web dashboard (UI)

- [x] Responsive dark-themed control surface
- [x] Live 8×8 board (click-to-move, flip, last-move highlight, annotations)
- [x] Move Studio: UCI input, quick-move chips, legal move explorer with filter
- [x] **Move Explorer / Stockfish panel**: live eval, depth N/30, elapsed time, search time, MultiPV lines, threads, memory, top-5 clickable lines
- [x] Engine controls for max depth, per-depth search time, number of explored lines, threads, and Stockfish hash memory
- [x] **Board support layout** directly beneath the chessboard:
  - **Move History** — scrollable paired notation from game start; click a move to copy its FEN
  - **AI Coach** — question box, coach style selector, teaching response, source pill (local / LLM / error)
- [x] Sidebar **Copy & Share** tools:
  - read-only FEN field + Copy FEN
  - PGN textarea + Refresh / Copy / Download `.pgn`
  - nested Load FEN / PGN card
- [x] Readable State panel (game ID, check, FEN, evaluation)
- [x] Hardware deck: Home, Park, Scan, robot move test sandbox
- [x] Hall matrix snapshot grid (64 cells, polarity legend)
- [x] Events + API console with raw state toggle
- [x] WebSocket-driven updates (no polling `/api/state` after events)
- [x] Diff-based board rendering (DOM built once, mutated in place — Pi-friendly)

### AI Coach

- [x] `POST /api/ai/coach` — structured context (FEN, Stockfish lines, phase, material, king safety, development)
- [x] **Local rule-based teaching fallback** when LLM disabled (substantive chess advice, no boilerplate disclaimers)
- [x] Optional OpenAI-compatible LLM integration (`LLM_COACH_ENABLED`, `LLM_API_KEY`, etc.)
- [x] LLM error path falls back to local coach
- [x] Coach is **advisory only** — never controls motors or bypasses python-chess

### Hardware / serial integration

- [x] JSON-line serial protocol to Teensy 4.0 (115200 baud)
- [x] Stable device path: `/dev/serial/by-id/usb-Teensyduino_USB_Serial_6634680-if00`
- [x] **Mock serial mode** (`SERIAL_MOCK=true`) for development without hardware
- [x] `MotionService`: home, park, scan, move, capture_move, set_em
- [x] `BoardSensorService`: 64-cell snapshot model, diffing
- [x] `MoveReconciler`: map Hall occupancy deltas → legal moves (software-tested)
- [x] `SafetyMonitor`: homed / busy / fault gates
- [x] `SquareMapper`: algebraic square ↔ XY mm including capture trays
- [x] Hardware event handling: scan, motion_done, fault → event bus

### Teensy 4.0 firmware

- [x] Full PlatformIO project at `firmware/teensy40/`
- [x] CoreXY inverse kinematics, blocking step pulses, homing
- [x] Hall matrix scan via 4× CD74HC4067 multiplexers
- [x] Z-axis servo (engage/park)
- [x] Electromagnet control with scan-disable-while-energized
- [x] Safety: e-stop, endstops
- [x] JSON command parser (home, scan, move, capture_move, park, set_em, calibrate)
- [x] Boot message: `{"type":"boot","controller":"teensy40",...}`
- [x] Compiles cleanly via PlatformIO (also checked by `software_ready_check.py --firmware`)

### Testing & quality

- [x] **859 pytest cases** across 22 test modules
- [x] `scripts/software_ready_check.py` — compileall + pytest + HTTP smoke (forces mock serial)
- [x] `scripts/smoke_check.py` — quick API smoke via TestClient
- [x] Deep tests for: coach, move history/PGN, game state invariants, live engine publisher, negative API paths, UI asset contracts, config/concurrency
- [x] Existing comprehensive suites: API, reconciler, board sensor, motion/pathfinding, PGN replay, stress/integration, chess edge cases

### Removed / migrated

- [x] **ESP32 / Nano ESP32 firmware removed** — Teensy 4.0 is the sole microcontroller target
- [x] Per-move Stockfish spawn removed from snapshots (performance)
- [x] Fixed-time engine polling replaced by depth-driven WebSocket pushes

### Not yet implemented (planned)

- [ ] Physical motor/sensor/electromagnet wiring and bench validation
- [ ] Closed loop: physical move detection → reconciler → rules → engine → robot execution
- [ ] Hall sensor calibration on real hardware (`scripts/record_calibration.py` exists)
- [ ] Lichess board / bot / cloud relay modes wired into app lifespan (provider skeletons exist)
- [ ] End-to-end autonomous play (local engine mode from `docs/modes.md`)

---

## 5. Current Phase & Limitations

**Phase:** Software + controller integration. The Pi host, dashboard, chess logic, Stockfish, serial bridge to Teensy, and API are working. Physical motion and sensing are **not validated on real hardware**.

**Expected right now:** Hall snapshot returns all zeros because no sensors are wired:

```json
"a1": {"o": 0, "p": 0, "m": 0}
```

Stockfish uses the internal python-chess state, not physical sensors. This is correct behaviour pre-wiring.

**Do not use for real physical motion yet** (once motors are wired): Home, Park, Robot Move, electromagnet commands — until endstops, homing, and safety interlocks are verified on the bench.

---

## 6. Hardware

### Raspberry Pi 4 (8 GB)

- Runs FastAPI, Stockfish, web dashboard, python-chess
- Talks to Teensy over USB serial
- Typical deployment: `~/Ghost-mate` on the Pi, venv at `~/Ghost-mate/venv`

### Teensy 4.0 (active controller)

- CoreXY stepper pulses, Hall scanning, Z servo, electromagnet, safety inputs
- Detected as:

```text
/dev/serial/by-id/usb-Teensyduino_USB_Serial_6634680-if00
```

Use the **by-id path** in `.env`, not `/dev/ttyACM0` (device numbers can change).

Verify on the Pi:

```bash
ls -l /dev/serial/by-id/
```

### Not yet wired

- CoreXY motors + TMC2209 drivers
- Endstops, e-stop
- 64 Hall sensors + 4× CD74HC4067 muxes
- Z servo mechanism
- Electromagnet + MOSFET driver
- 24 V power rail (steppers must not run from USB)

---

## 7. Software Stack

| Component | Version / notes |
|-----------|-----------------|
| Python | ≥ 3.11 |
| FastAPI | ≥ 0.110 |
| uvicorn | ≥ 0.27 (use `uvloop` on Pi via `scripts/run_host_pi.sh`) |
| python-chess | ≥ 1.999 |
| Stockfish | System binary, e.g. `/usr/games/stockfish` |
| pydantic-settings | `.env` configuration |
| aiohttp | LLM coach HTTP client |
| orjson | Fast WebSocket JSON serialization |
| SQLModel / SQLite | Optional game/calibration persistence |
| PlatformIO | Teensy firmware build (dev dependency) |
| pytest | 859 tests, asyncio mode |

Package name: `autonomous-corexy-chess-robot` v0.2.0 (`pyproject.toml`)

---

## 8. Installation & Setup

### On Raspberry Pi (production)

```bash
cd ~/Ghost-mate
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev,linux]"

# Install Stockfish
sudo apt install stockfish   # or verify: which stockfish

# Copy and edit environment
cp .env.example .env
# Set SERIAL_MOCK=false, SERIAL_PORT to your Teensy by-id path, HOST=0.0.0.0

# Verify
python scripts/software_ready_check.py
```

**Important:** The venv must be a **Linux** venv (`venv/bin/activate`). If you see `Scripts/` and `Lib/` instead of `bin/`, recreate it on the Pi (see [Troubleshooting](#26-troubleshooting)).

### On Windows (development against Pi or mock)

```powershell
cd Ghost-mate
python -m venv venv
.\venv\Scripts\activate
pip install -e ".[dev]"
# Use SERIAL_MOCK=true in .env for local dev without Teensy
```

---

## 9. Configuration (`.env`)

Copy from `.env.example`. Key variables:

```env
# Server
HOST=0.0.0.0          # 0.0.0.0 so LAN clients can reach the dashboard
PORT=8000
APP_DEBUG=false

# Serial / Teensy 4.0
SERIAL_MOCK=false     # true = mock client (no hardware needed)
SERIAL_PORT=/dev/serial/by-id/usb-Teensyduino_USB_Serial_6634680-if00
SERIAL_BAUD=115200
COMMAND_TIMEOUT_S=5.0

# Stockfish
STOCKFISH_PATH=/usr/games/stockfish
ENGINE_MOVE_TIME_S=1.0
ENGINE_EVAL_TIME_S=0.12
ENGINE_LIVE_PUSH_ENABLED=true
ENGINE_LIVE_INTERVAL_S=1.0
ENGINE_LIVE_MULTIPV=5
ENGINE_LIVE_MAX_DEPTH=24    # UI/API cap is 30
ENGINE_LIVE_SEARCH_TIME_S=2.0
ENGINE_HASH_MB=128
# ENGINE_THREADS=3
# ENGINE_SKILL_LEVEL=12       # 0..20 to weaken; unset = full strength

# LLM Coach (optional)
LLM_COACH_ENABLED=false
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_S=20.0
LLM_MAX_TOKENS=700

# Board geometry (mm)
SQUARE_SIZE_MM=50.0
BOARD_ORIGIN_X_MM=0.0
BOARD_ORIGIN_Y_MM=0.0
CAPTURE_TRAY_LEFT_X_MM=-60.0
CAPTURE_TRAY_RIGHT_X_MM=460.0

# Database
DATABASE_URL=sqlite:///data/db/chess_robot.db

# WebSocket tuning
WS_MAX_QUEUE=256
STATE_THROTTLE_MS=16

# Lichess (future modes)
LICHESS_TOKEN=
LICHESS_BOT_TOKEN=
```

Notes:

- `scripts/software_ready_check.py` **forces `SERIAL_MOCK=true`** internally so tests never depend on real hardware.
- `APP_DEBUG` (not `DEBUG`) avoids PlatformIO/shell pollution of boolean env vars.

---

## 10. Running the App

### Production (Pi)

```bash
cd ~/Ghost-mate
source venv/bin/activate
./scripts/run_host_pi.sh
# or manually:
uvicorn host.app.main:app --host 0.0.0.0 --port 8000
```

Open from any device on the LAN:

```text
http://192.168.1.4:8000
```

Hard-refresh after code changes: `Ctrl + Shift + R`

### Development (with auto-reload)

```bash
./scripts/dev_host.sh        # Linux / macOS
# or
.\scripts\dev_host.ps1       # Windows PowerShell
```

### SSH to the Pi (from Windows)

```powershell
ssh shashwat@192.168.1.4
```

If the IP changes, scan the LAN or use `arp -a`. Hostname `ghostmate.local` may work but IP has been more reliable.

### Stop the server

`Ctrl + C` in the terminal. A traceback after interrupt is usually harmless shutdown noise.

---

## 11. Running Tests & Readiness Checks

Always activate the venv first:

```bash
cd ~/Ghost-mate
source venv/bin/activate
which python   # expect .../Ghost-mate/venv/bin/python
```

### Full readiness pipeline

```bash
python scripts/software_ready_check.py
```

Runs: `compileall` → **pytest (859 tests)** → HTTP smoke check.  
Expected final line:

```text
✅ SOFTWARE READINESS CHECK PASSED
```

Include firmware compile:

```bash
python scripts/software_ready_check.py --firmware
```

### Run pytest directly

```bash
SERIAL_MOCK=true python -m pytest host/tests -q
```

### Test modules (22 files, 859 cases)

| Module | Focus |
|--------|-------|
| `test_api_comprehensive.py` | Full HTTP API, static assets, edge cases |
| `test_coach_deep.py` | AI coach helpers, LLM paths, forbidden boilerplate |
| `test_move_history_and_pgn.py` | History shape, PGN export/import, special moves |
| `test_game_state_invariants.py` | Snapshot cache, illegal moves, EventBus |
| `test_live_engine_deep.py` | Depth publisher, client idle, position reset |
| `test_new_endpoints_negative.py` | Coach/engine/PGN negative paths, WebSocket |
| `test_ui_assets_and_source_hygiene.py` | Template/JS/CSS contracts |
| `test_config_and_concurrency.py` | Settings clamping, parallel API safety |
| `test_live_engine_and_coach.py` | Live engine + coach integration |
| `test_game_state.py` | GameState unit tests |
| `test_hardware_and_domain.py` | Hardware + domain layer |
| `test_motion_and_pathfinding.py` | Motion + square mapping |
| `test_reconciler_comprehensive.py` | Move reconciler |
| `test_board_sensor.py` | Board sensor service |
| `test_pgn_and_games.py` | PGN store and replay |
| `test_stress_and_integration.py` | Stress scenarios |
| `test_full_stack_api.py` | End-to-end API flows |
| `test_chess_edge_cases_api.py` | Chess edge cases via API |
| `test_sensor_delta_reconciler.py` | Sensor delta reconciliation |
| `test_pgn_replay_and_results.py` | PGN replay results |
| `test_reconciler.py` | Basic reconciler |
| `test_rules.py` | Rules helpers |

---

## 12. Web Dashboard

### Layout overview

| Section | Contents |
|---------|----------|
| **Hero** | Brand, New Game, Scan Board, connection status, clock |
| **Metric cards** | Turn, legal moves, game status + eval, robot status |
| **Board panel** | Live position, flip/clear, click-to-move, submit bar |
| **Sidebar** | Move Studio, Readable State, Move Explorer (Stockfish top lines) |
| **Board support** | Move History + AI Coach directly beneath the chessboard |
| **Copy & Share** | FEN/PGN copy/export and Load FEN/PGN tools in the sidebar |
| **Hardware deck** | Home, Park, Scan, robot move sandbox, hardware log |
| **Sensors** | 64-cell Hall matrix snapshot |
| **Activity** | WebSocket event feed + raw JSON state toggle |

### Typical usage flow

1. Start the server on the Pi.
2. Open `http://192.168.1.4:8000` and hard-refresh if needed.
3. Click **Start New Game** or load a FEN/PGN from the Copy & Share card.
4. Play moves via the board, UCI input, or Stockfish suggestion clicks.
5. Watch the Stockfish panel update live via WebSocket (`ENGINE_UPDATE`).
6. Review **Move History** from move 1; click any move to copy its FEN.
7. Use **Copy FEN** / **Copy PGN** / **Download .pgn** to export the current game.
8. Ask the **AI Coach** about the position (works without an API key via local fallback).

---

## 13. HTTP API Reference

Base URL: `http://<host>:8000/api`

### Health & state

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | `{"status":"ok"}` |
| GET | `/state` | Full game snapshot (FEN, turn, legal moves, eval, **move_history**, etc.) |
| POST | `/game/new` | New game; optional query `?fen=...` |
| GET | `/state/pgn` | Export `{fen, start_fen, pgn, ply}` |

### Moves

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/move/human` | `{"uci":"e2e4"}` | Apply legal human move |
| POST | `/move/robot` | `{source,target,capture?,victim?}` | Send physical motion command |

### Position loading

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/position/fen` | `{"fen":"..."}` | Load FEN; resets game from that position |
| POST | `/position/pgn` | `{"pgn":"..."}` | Load PGN mainline **with full move history preserved** |

### Stockfish

| Method | Path | Query params | Description |
|--------|------|--------------|-------------|
| GET | `/engine/analysis` | `multipv=5` | Legacy analysis endpoint |
| GET | `/engine/live` | `multipv=5`, `max_depth=24`, `time_s=2.0` | Fresh depth/time-capped analysis (preferred) |
| GET | `/engine/settings` | — | Current live engine settings and caps |
| POST | `/engine/settings` | `{max_depth?, search_time_s?, multipv?, threads?, hash_mb?}` | Update live engine settings |
| POST | `/engine/bestmove` | `time_s` | Engine's best move for current position |

### AI Coach

| Method | Path | Body | Description |
|--------|------|------|-------------|
| POST | `/ai/coach` | `{"question":"...", "style":"student"}` | Teaching response (LLM or local fallback) |

### Hardware

| Method | Path | Description |
|--------|------|-------------|
| POST | `/hardware/home` | Home carriage |
| POST | `/hardware/park` | Park carriage |
| POST | `/hardware/scan` | Hall scan (`?full=true` default) |
| GET | `/board/snapshot` | Latest 64-square sensor payload |

### PowerShell JSON examples

```powershell
# Human move
$body = @{ uci = "e2e4" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/move/human" `
  -ContentType "application/json" -Body $body

# Load FEN
$body = @{ fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/position/fen" `
  -ContentType "application/json" -Body $body

# Export PGN
Invoke-RestMethod -Uri "http://192.168.1.4:8000/api/state/pgn"

# AI Coach
$body = @{ question = "What plan should I follow?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/ai/coach" `
  -ContentType "application/json" -Body $body

# Live engine
curl.exe "http://192.168.1.4:8000/api/engine/live?multipv=5&max_depth=24&time_s=2.0"
```

**PowerShell tip:** Do not use raw single-quoted JSON with `curl.exe -d '{"uci":"e2e4"}'` — PowerShell quoting often produces invalid JSON. Use `Invoke-RestMethod` or `ConvertTo-Json`.

---

## 14. WebSocket Events

**Endpoint:** `ws://<host>:8000/ws`

**Query parameters:**

| Param | Effect |
|-------|--------|
| `engine=1` | Opt in to live `ENGINE_UPDATE` pushes; increments server-side client counter |
| `max_depth=N` | Client depth cap (clamped 1–30) |

**On connect:** server sends `HELLO` with full game snapshot (includes `move_history`).

**Event types** (from `host/app/domain/events.py`):

`LOCAL_MOVE_CANDIDATE` · `REMOTE_MOVE_RECEIVED` · `ROBOT_MOVE_COMPLETE` · `SCAN_RECEIVED` · `SCAN_MISMATCH` · `GAME_END` · `FAULT` · `STATE_CHANGED` · `ENGINE_UPDATE`

**Live engine:** background task publishes `ENGINE_UPDATE` at depth 1, 2, … up to negotiated max when at least one client has `engine=1`. Each payload includes `depth_requested`, `max_depth`, `is_final_depth`, `search_elapsed_ms`.

**Heartbeat:** `PING` every 15 s if no other events.

**Recommended client URL:**

```text
/ws?engine=1&max_depth=24
```

---

## 15. Stockfish Integration

### White-centric evaluation policy

```text
Positive score  →  White is better
Negative score  →  Black is better
```

This holds **regardless of whose turn it is**. Example: Black to move, `+0.38` means White is slightly better — not Black.

### Persistent engine service

- Single Stockfish process for the app lifetime (lazy start on first engine request)
- Async lock serializes engine calls
- LRU cache keyed by transposition key + multipv + depth/time
- Game-over positions short-circuit without touching the engine

### Response fields (typical)

- `fen`, `turn`, `score_view: "white"`
- `current_display`, `current_score_cp`, `mate_display`
- `depth`, `depth_requested`, `elapsed_ms`, `search_elapsed_ms`
- `best_moves[]`: rank, uci, san, score_display, pv (SAN list)
- `cache_hit`, `is_final_depth` (live WebSocket path)

Verify Stockfish on the Pi:

```bash
which stockfish    # expect /usr/games/stockfish
python - <<'PY'
import chess
print("python-chess OK, legal moves:", chess.Board().legal_moves.count())
PY
```

See also: [`OPTIMIZATIONS.md`](OPTIMIZATIONS.md)

---

## 16. Move History & PGN

### In snapshots

Every `GET /api/state` response includes:

```json
"move_history": [
  {
    "ply": 1,
    "move_number": 1,
    "color": "white",
    "uci": "e2e4",
    "san": "e4",
    "fen_after": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
  }
],
"start_fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
```

### Export

```http
GET /api/state/pgn
```

Returns:

```json
{
  "fen": "...",
  "start_fen": "...",
  "pgn": "[Event \"GhostMate Session\"]\n...",
  "ply": 4
}
```

PGN includes `[SetUp "1"]` and `[FEN "..."]` headers when the game started from a custom position.

### Dashboard tools

- **Move History panel** — paired white/black notation from move 1; last move highlighted
- **Copy FEN** — copies current position FEN
- **Copy PGN / Download .pgn** — exports the full game line
- **Load FEN / Load PGN** — set up puzzle positions; PGN load preserves the entire mainline for history display

---

## 17. AI Coach / LLM Layer

The coach explains positions, compares Stockfish lines, and answers student questions. It receives structured context only — **never controls motors** and never bypasses python-chess legality.

### Endpoint

```http
POST /api/ai/coach
Content-Type: application/json

{"question": "Why is Nf3 recommended?", "style": "student"}
```

### Response

```json
{
  "source": "local_fallback",
  "configured": false,
  "answer": "Move 1, white to move. We are in the opening. Stockfish reads +0.30 ...",
  "context": { "fen": "...", "stockfish": { ... }, "position_features": { ... } }
}
```

`source` values: `local_fallback` · `llm` · `llm_error`

### Local fallback (no API key)

When `LLM_COACH_ENABLED=false` or no key is set, a **deterministic teaching response** covers:

- Phase (opening / middlegame / endgame), material balance, side to move, eval
- Best move with plain-language idea and engine line
- Alternative candidates
- Phase-specific planning advice
- Tailored hint based on the question (why / plan / mistake / teach)

The answer body does **not** include boilerplate like "this coach is advisory only" or "Source: local_fallback". The dashboard shows the source in a small pill chip instead.

### Enable LLM

```env
LLM_COACH_ENABLED=true
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

Any OpenAI-compatible `/chat/completions` endpoint works.

### How to integrate a proper LLM coach

The current local coach is deterministic so the dashboard still works without an
API key. To use a real model, keep the same API/UI and configure an
OpenAI-compatible provider:

1. Pick a provider that exposes `/chat/completions` (OpenAI, OpenRouter, local
   vLLM/Ollama-compatible gateway, etc.).
2. Set `LLM_COACH_ENABLED=true`, `LLM_API_BASE`, `LLM_API_KEY`, and `LLM_MODEL`
   in `.env`.
3. Restart the FastAPI app.
4. Ask from the dashboard AI Coach panel and choose a style (`student`,
   `coach`, `grandmaster`, or `brief`).
5. Verify the response source pill says `llm: <model>` instead of `local coach`.

The LLM receives structured chess context, not raw control authority:

- FEN, side to move, check/game-over flags, legal-move count
- Stockfish eval, depth, top lines, SAN/UCI/PV data
- Position features: phase, material, king safety, development
- Robot status and last error

The LLM should explain and teach. Any physical move still has to go through
python-chess legality and the robot safety/motion path.

---

## 18. Teensy 4.0 Firmware

Location: `firmware/teensy40/`

### Build & flash

```bash
cd ~/Ghost-mate
source venv/bin/activate
./scripts/flash_firmware.sh
# or manually:
cd firmware/teensy40
python -m platformio run          # build
python -m platformio run -t upload # flash
python -m platformio device monitor
```

PlatformIO is installed as a dev dependency (`pip install -e ".[dev]"`).

### Firmware modules

| Module | Role |
|--------|------|
| `config.hpp` | Pin map, geometry, timing constants |
| `corexy.cpp` | Inverse kinematics, homing, step pulses |
| `hall_scan.cpp` | 64-cell scan via 4 muxes, baseline subtraction |
| `z_axis.cpp` | Servo engage/park |
| `safety.cpp` | E-stop and endstop reads |
| `protocol.cpp` | JSON parse, ACK/NACK, async events |
| `main.cpp` | Boot loop, safe move sequence (scan → EM on → move → EM off → scan) |

Boot message over serial:

```json
{"type":"boot","controller":"teensy40","fw":"ghostmate-teensy40","baud":115200}
```

---

## 19. Serial Protocol

Newline-delimited JSON. Full spec: [`docs/protocol.md`](docs/protocol.md)

**Host → Teensy commands:**

```json
{"id": 1, "cmd": "home"}
{"id": 2, "cmd": "scan", "full": true}
{"id": 3, "cmd": "move", "from": "e2", "to": "e4", "capture": false}
{"id": 4, "cmd": "capture_move", "victim": "d5", "from": "e4", "to": "d5"}
{"id": 5, "cmd": "park"}
{"id": 6, "cmd": "set_em", "on": true}
```

**Teensy → host replies:**

```json
{"id": 1, "ok": true}
{"id": 3, "ok": false, "err": "not_homed"}
```

**Teensy async events:**

```json
{"type": "scan", "ts_ms": 482310, "cells": {"e2": {"o": 1, "p": 1, "m": 812}}}
{"type": "motion_done", "id": 3}
{"type": "fault", "code": "pickup_lost", "square": "e2"}
```

Cell keys: `o` = occupancy, `p` = polarity (−1 white / +1 black), `m` = magnitude.

---

## 20. Domain Logic (Reconciler, Sensing, Safety)

| Module | Purpose |
|--------|---------|
| `MoveReconciler` | Given before/after Hall snapshots, infer the legal move python-chess would accept |
| `BoardSensorService` | Maintain latest 64-cell snapshot, compute diffs |
| `board_resync` | Compare physical occupancy vs expected python-chess piece map |
| `calibration` | Per-square baseline/threshold model for Hall classification |
| `SafetyMonitor` | Track homed, busy, fault; gate motion commands |
| `SquareMapper` | Map `a1`–`h8` to CoreXY mm coordinates + capture tray positions |
| `MotionService` | Async wrappers over serial for all hardware commands |

These paths are **software-tested** with mock serial and synthetic snapshots. Physical accuracy depends on bench calibration (see [`docs/calibration.md`](docs/calibration.md)).

---

## 21. Future Game Modes (Skeleton)

Provider skeletons exist in `host/app/providers/` but are **not wired into the main app lifespan** yet:

| Mode | File | Description |
|------|------|-------------|
| Local engine | `local_engine.py` | Human vs Stockfish on physical board |
| Lichess board | `lichess_board.py` | Stream remote human opponent moves |
| Lichess bot | `lichess_bot.py` | Bot account with engine assistance |
| Cloud relay | `cloud_relay.py` | External app sends moves via relay server |

See [`docs/modes.md`](docs/modes.md) for intended behaviour.

Configure tokens in `.env`: `LICHESS_TOKEN`, `LICHESS_BOT_TOKEN`

---

## 22. Scripts

| Script | Purpose |
|--------|---------|
| `scripts/software_ready_check.py` | Full pipeline: compileall + pytest + smoke; `--firmware` builds Teensy |
| `scripts/smoke_check.py` | Quick HTTP smoke via TestClient |
| `scripts/run_host_pi.sh` | Production Pi launcher (uvloop, httptools) |
| `scripts/dev_host.sh` | Dev launcher with reload (Linux/macOS) |
| `scripts/dev_host.ps1` | Dev launcher (Windows) |
| `scripts/flash_firmware.sh` | PlatformIO build/upload/monitor for Teensy |
| `scripts/record_calibration.py` | Record Hall baseline from real serial |
| `scripts/replay_pgn.py` | Print UCI moves from a PGN file |

Legacy one-time patch scripts (already applied, kept for reference):

- `patch_stockfish_analysis.py`
- `patch_dynamic_stockfish_v3.py`
- `patch_engine_dynamic_fen_pgn.py`
- `patch_eval_annotations.py`
- `fix_clean_pieces_lines.py`

---

## 23. Documentation (`docs/`)

| File | Contents |
|------|----------|
| [`docs/architecture.md`](docs/architecture.md) | Pi vs Teensy responsibility split |
| [`docs/protocol.md`](docs/protocol.md) | Serial JSON protocol |
| [`docs/safety.md`](docs/safety.md) | Electromagnet, homing, e-stop, power guidance |
| [`docs/calibration.md`](docs/calibration.md) | 4-layer Hall calibration workflow |
| [`docs/modes.md`](docs/modes.md) | Local engine, Lichess, cloud relay modes |

Also at repo root: [`OPTIMIZATIONS.md`](OPTIMIZATIONS.md) (performance notes)

---

## 24. Safety

From [`docs/safety.md`](docs/safety.md):

- Keep the electromagnet normally off.
- Disable Hall scanning while the electromagnet is energized (firmware enforces this).
- Home slowly; confirm directions with belts off or motors lifted first.
- Add physical limit switches and an e-stop.
- Use a fuse on the 24 V input.
- **Never power steppers from USB.**

---

## 25. Recommended Hardware Bring-Up Order

Do not wire everything at once:

1. One endstop switch → confirm Teensy reads it
2. One TMC2209 + one NEMA 17 → tiny step test only
3. Second driver + motor → test independently
4. Attach CoreXY belts → slow X/Y movement
5. Add homing with endstops
6. Add Z servo mechanism
7. Add electromagnet MOSFET circuit
8. Add one 4×4 Hall tile → calibrate
9. Scale to full 8×8 Hall matrix
10. Integrate physical board resync with software state
11. Closed loop: detect human move → engine reply → robot executes

---

## 26. Troubleshooting

### App cannot find Stockfish

```bash
which stockfish   # expect /usr/games/stockfish
```

Set in `.env`: `STOCKFISH_PATH=/usr/games/stockfish`

### Wrong serial device

```bash
ls -l /dev/serial/by-id/
```

Use the Teensy by-id path. Do **not** rely on `/dev/ttyACM0` long-term.

### UI does not update after code changes

Hard refresh: `Ctrl + Shift + R`

Verify WebSocket is Live in the dashboard header. Engine panel should receive `ENGINE_UPDATE` events (not just HTTP polling).

### `POST /api/move/human` returns 400

Usually means python-chess rejected the move: illegal for current position, wrong side, stale UI suggestion, or malformed JSON body. Not necessarily a server bug.

### Board snapshot all zeros

Expected until Hall sensors are wired and calibrated.

### Linux venv shows `Scripts/` instead of `bin/`

Windows venv was copied to the Pi. Recreate:

```bash
cd ~/Ghost-mate
deactivate 2>/dev/null || true
rm -rf venv .venv
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev,linux]"
```

### Uvicorn shutdown traceback

Harmless if it only appears after `Ctrl + C`.

### Favicon 404

Harmless.

### Tests fail on real hardware

Run with mock serial:

```bash
SERIAL_MOCK=true python scripts/software_ready_check.py
```

The readiness script forces mock mode automatically.

---

## 27. Development Rules & Handoff Notes

When continuing development, preserve these rules:

1. **Raspberry Pi** is the host brain; **Teensy 4.0** is the sole hardware controller.
2. Keep the host ↔ Teensy JSON protocol stable (see `docs/protocol.md`).
3. Stockfish evaluation must remain **White-centric**.
4. Dynamic UI should subscribe to `/ws?engine=1&max_depth=24` for pushed `ENGINE_UPDATE` events.
5. Use `/dev/serial/by-id/...Teensyduino...`, not `/dev/ttyACM0`.
6. Software tests must stay hardware-independent (`SERIAL_MOCK=true`).
7. python-chess is the authority for legality; reconciler proposes, host validates.
8. LLM coach is advisory only — never direct motor control.
9. Do not wire motors until endstop and driver bench tests are planned.
10. Do not trust all-zero snapshots until Hall sensors are calibrated.
11. When a test fails, fix the **correct** side (test vs code) — do not weaken assertions to match bugs.

---

## 28. Migration Notes (ESP32 → Teensy 4.0)

The project previously targeted a **Nano ESP32**. That firmware has been **removed**. All microcontroller code now lives in `firmware/teensy40/`.

Changes made during migration:

- Default `SERIAL_PORT` → Teensy by-id USB path, baud **115200**
- Full Teensy firmware port: CoreXY, Hall scan, Z servo, safety, JSON protocol
- `scripts/flash_firmware.sh` → `firmware/teensy40` via venv PlatformIO
- Host comments and docs updated; no ESP32 references in active code paths
- ESP32 used FastAccelStepper; Teensy uses direct step pulses + Arduino Servo library

---

## 29. Final Checkpoint

As of the latest verified state:

```text
✅ Raspberry Pi host works
✅ Linux venv + pip install -e ".[dev,linux]"
✅ 859 pytest cases pass
✅ software_ready_check.py passes (compileall + pytest + smoke)
✅ Dashboard at http://192.168.1.4:8000
✅ Teensy 4.0 detected via stable USB by-id serial path
✅ Mock serial mode for hardware-free development
✅ Stockfish persistent service + white-centric eval
✅ Depth/time-driven live ENGINE_UPDATE over WebSocket (default depth 24, cap 30)
✅ Move history in snapshots + Move History UI panel
✅ PGN export (GET /api/state/pgn) + Copy/Download in dashboard
✅ FEN + PGN loading (PGN preserves full move stack)
✅ AI Coach with local teaching fallback + optional LLM
✅ Board support layout (history + coach below board, copy/share in sidebar)
✅ Teensy 4.0 firmware compiles (PlatformIO)
✅ Move reconciler, board sensor, safety monitor (software-tested)
⚠️  Hall sensors not wired — snapshot all zeros (expected)
⚠️  Motors / drivers / electromagnet not wired
⚠️  Physical motion not validated on bench
⚠️  Lichess / cloud modes skeleton only
⚠️  Closed-loop autonomous play not yet implemented
```

**Next milestone:** bench bring-up of Teensy motion (one axis → homing → pick-and-place → Hall baseline → reconciler closed loop). See [§25](#25-recommended-hardware-bring-up-order).
