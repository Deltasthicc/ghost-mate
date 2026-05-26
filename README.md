# Ghost Mate — Autonomous CoreXY Chess Robot

> Current project state: **Raspberry Pi 4 host + Teensy 4.0 controller + Stockfish/python-chess software assistant working.**  
> The site runs from the Raspberry Pi at `http://192.168.1.4:8000`, talks to the Teensy 4.0 over USB serial, and includes dynamic Stockfish analysis, White-centric evaluation, top-5 engine move suggestions, FEN loading, and PGN final-position loading.

---

## 1. What Ghost Mate Is

Ghost Mate is an autonomous chess robot project built around a split architecture:

```text
Windows laptop browser
        ↓ HTTP/WebSocket
Raspberry Pi 4 host
        ↓ Python/FastAPI/python-chess/Stockfish
Teensy 4.0 controller
        ↓ future CoreXY motors, Hall sensors, servo, electromagnet
Physical chessboard robot
```

The project is currently in the **software + controller integration phase**. The Raspberry Pi host app, chess logic, live dashboard, Stockfish engine analysis, serial connection to Teensy, and API routes are working. The physical motor/sensor/electromagnet layer has **not** been wired yet and should be brought up later in safe subsystem steps.

---

## 2. Current Working Status

### Confirmed working

- Raspberry Pi 4 boots and is reachable over SSH.
- Raspberry Pi hostname is `ghostmate`, but the reliable connection method is currently the IP address:
  - `192.168.1.4`
- SSH user:
  - `shashwat`
- Project path on the Pi:
  - `~/Ghost-mate`
- Correct Linux virtual environment now exists:
  - `~/Ghost-mate/venv`
  - Python path should be `/home/shashwat/Ghost-mate/venv/bin/python`
- FastAPI/Uvicorn server starts successfully:
  - `uvicorn host.app.main:app --host 0.0.0.0 --port 8000`
- Dashboard loads from the laptop:
  - `http://192.168.1.4:8000`
- WebSocket path works.
- API health check works:
  - `GET /api/health`
- Game state works:
  - `GET /api/state`
  - `POST /api/game/new`
  - `POST /api/move/human`
- `python-chess` is installed and validates legal moves.
- Stockfish is installed on the Pi:
  - `/usr/games/stockfish`
- Stockfish analysis works through:
  - `GET /api/engine/analysis?multipv=5`
  - `GET /api/engine/live?multipv=5`
- Dynamic Stockfish UI receives pushed `ENGINE_UPDATE` events over WebSocket
  and can still use `/api/engine/live` as a fresh HTTP fallback.
- Position evaluation is now intended to be **White-centric**:
  - `+` means White is better.
  - `-` means Black is better.
  - This does **not** flip just because it is Black’s turn.
- Top-5 Stockfish move suggestions work using MultiPV.
- FEN loading works:
  - `POST /api/position/fen`
- PGN final-position loading works:
  - `POST /api/position/pgn`
- User can play from a loaded FEN or final PGN position, puzzle-style.
- Software readiness check passes:
  - `562 passed`
  - `✅ SOFTWARE READINESS CHECK PASSED`
- Teensy 4.0 is detected by Raspberry Pi.
- Raspberry Pi can communicate with Teensy 4.0 over serial.
- `/api/hardware/scan` works against the Teensy controller and returns OK.
- `/api/board/snapshot` returns a 64-square payload.

### Expected behavior right now

The board snapshot currently returns all zeros because no Hall sensors are wired yet:

```json
"a1": {"o": 0, "p": 0, "m": 0}
```

That is expected. It does **not** mean Stockfish is broken. Stockfish uses the internal `python-chess` game state, not the physical Hall sensors yet.

---

## 3. Hardware Currently Connected

### Raspberry Pi 4 8GB

Role:

- Main host computer.
- Runs Python/FastAPI backend.
- Runs the web dashboard.
- Runs Stockfish.
- Maintains game state using `python-chess`.
- Talks to Teensy 4.0 over serial.

### Teensy 4.0

Role:

- Active real-time controller for Ghost Mate.
- Handles CoreXY step pulses, Hall scanning, Z servo, electromagnet, and safety inputs.
- Connected to Raspberry Pi by USB.
- Detected as:

```text
/dev/serial/by-id/usb-Teensyduino_USB_Serial_6634680-if00
```

This is the path the app should use.

Do **not** rely on `/dev/ttyACM0` long-term because device numbers can change when multiple boards are connected.

### Stable serial paths

Run this on the Pi:

```bash
ls -l /dev/serial/by-id/
```

Expected relevant entries:

```text
usb-Teensyduino_USB_Serial_6634680-if00 -> ../../ttyACM0
```

Use the Teensy path in `.env`.

---

## 4. Important `.env` Configuration

The current app should use the Teensy stable by-id path:

```env
HOST=0.0.0.0
PORT=8000

SERIAL_MOCK=false
SERIAL_PORT=/dev/serial/by-id/usb-Teensyduino_USB_Serial_6634680-if00
SERIAL_BAUD=115200

STOCKFISH_PATH=/usr/games/stockfish
ENGINE_MOVE_TIME_S=1.0
ENGINE_EVAL_TIME_S=0.12
ENGINE_LIVE_PUSH_ENABLED=true
ENGINE_LIVE_INTERVAL_S=1.0
ENGINE_LIVE_MULTIPV=5
ENGINE_LIVE_MAX_DEPTH=15

LLM_COACH_ENABLED=false
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_S=20.0
LLM_MAX_TOKENS=700
```

Notes:

- `HOST=0.0.0.0` is required so the Windows laptop can open the dashboard through the Pi IP.
- `SERIAL_MOCK=false` means the app talks to the real Teensy 4.0.
- For pure software checks, `scripts/software_ready_check.py` was patched to force mock mode internally so tests do not depend on real hardware.
- Use `/dev/serial/by-id/...Teensyduino...`, not `/dev/ttyACM0`, because device numbers can change.

---

## 5. How to SSH Into the Raspberry Pi

From Windows PowerShell:

```powershell
ssh shashwat@192.168.1.4
```

If the IP changes, find it with:

```powershell
arp -a
```

or scan the LAN:

```powershell
1..254 | ForEach-Object {
  $ip = "192.168.1.$_"
  if (Test-Connection $ip -Count 1 -Quiet -ErrorAction SilentlyContinue) {
    Write-Host "$ip is alive"
  }
}
```

Hostname `ghostmate.local` may work sometimes, but the IP has been more reliable.

---

## 6. Starting the App

On the Raspberry Pi:

```bash
cd ~/Ghost-mate
source venv/bin/activate
uvicorn host.app.main:app --host 0.0.0.0 --port 8000
```

Then open this from the Windows laptop:

```text
http://192.168.1.4:8000
```

If the site looks old after code changes, hard-refresh:

```text
Ctrl + Shift + R
```

---

## 7. Stopping the App

In the Pi terminal running Uvicorn:

```text
Ctrl + C
```

If a long `KeyboardInterrupt`/`CancelledError` traceback appears after pressing `Ctrl+C`, it is usually harmless. It happened because Uvicorn was interrupted during shutdown. If the server was working before `Ctrl+C`, this is not a real application error.

---

## 8. Running Software Checks

Always activate the Linux venv first:

```bash
cd ~/Ghost-mate
source venv/bin/activate
which python
```

Expected:

```text
/home/shashwat/Ghost-mate/venv/bin/python
```

Then run:

```bash
python -m compileall host scripts
python scripts/software_ready_check.py
```

Expected final output:

```text
562 passed
✅ SOFTWARE READINESS CHECK PASSED
```

The readiness checker intentionally runs in mock serial mode so tests do not fail when Hall sensors/motors are missing.

---

## 9. Backend API Guide

### Health

```powershell
curl.exe http://192.168.1.4:8000/api/health
```

Expected:

```json
{"status":"ok"}
```

### New game

```powershell
curl.exe -X POST "http://192.168.1.4:8000/api/game/new"
```

### Make a human move

PowerShell-safe JSON method:

```powershell
$body = @{ uci = "e2e4" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/move/human" -ContentType "application/json" -Body $body
```

Important: do not use raw single-quoted JSON with `curl.exe` in PowerShell unless you know exactly how quoting is being passed. This failed earlier:

```powershell
curl.exe -X POST "http://192.168.1.4:8000/api/move/human" -H "Content-Type: application/json" -d '{"uci":"e2e4"}'
```

The server received invalid JSON due to PowerShell quoting.

### Current game state

```powershell
curl.exe "http://192.168.1.4:8000/api/state"
```

### Legacy Stockfish endpoint

```powershell
curl.exe "http://192.168.1.4:8000/api/engine/analysis?multipv=5"
```

### New live Stockfish endpoint

```powershell
curl.exe "http://192.168.1.4:8000/api/engine/live?multipv=5&max_depth=15"
```

`max_depth` is capped at `15`. The live dashboard also has a max-depth input
and uses depth-driven WebSocket updates rather than fixed-time polling.

This is the preferred endpoint for the dynamic site UI.

### Hardware scan

```powershell
curl.exe -X POST "http://192.168.1.4:8000/api/hardware/scan"
```

Expected:

```json
{"ok":true,"err":null}
```

### Board snapshot

```powershell
curl.exe "http://192.168.1.4:8000/api/board/snapshot"
```

Expected current real-hardware result before Hall sensors are wired:

```json
{
  "cells": {
    "a1": {"o": 0, "p": 0, "m": 0}
  }
}
```

---

## 10. Stockfish / python-chess Integration

### Installed components

Verify:

```bash
which stockfish
```

Expected:

```text
/usr/games/stockfish
```

Verify python-chess:

```bash
python - <<'PY'
import chess
import chess.engine
print("python-chess OK")
print("Starting position legal moves:", chess.Board().legal_moves.count())
PY
```

Expected:

```text
python-chess OK
Starting position legal moves: 20
```

### Current engine behavior

The engine endpoint returns:

- Current FEN
- Turn
- Search depth
- White-centric evaluation
- Mate information
- Top 5 moves
- SAN and UCI for each suggested move
- Principal variation line for each move

Example after `e2e4`:

```json
{
  "fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
  "turn": "black",
  "score_view": "white",
  "current_display": "+0.38",
  "current_score_cp": 38,
  "best_moves": [
    {
      "rank": 1,
      "uci": "e7e5",
      "san": "e5",
      "score_display": "+0.38"
    }
  ],
  "note": "All scores are White-centric..."
}
```

Meaning:

- It is Black to move.
- `+0.38` still means White is slightly better.
- It does **not** mean Black is better just because Black is to move.

---

## 11. Dynamic Engine UI

The dashboard was patched to add dynamic Stockfish behavior.

Expected UI changes:

- The old legal move list is replaced/augmented by:
  - `Stockfish`
  - `Top 5 Move Explorer`
- The panel shows:
  - Position value
  - White POV explanation
  - Side to move
  - Mate display if available
  - Search depth against the selected max depth
  - Time spent on the current depth and total search
  - Live Stockfish updates
- The primary live path is WebSocket:

```text
/ws?engine=1
```

The browser opts into engine updates, and the server pushes `ENGINE_UPDATE`
events at depth 1, 2, 3, ... up to the selected depth cap. For this project,
the hard cap is `15`.
The fresh HTTP fallback remains:

```http
GET /api/engine/live?multipv=5&max_depth=15
```

Repeated HTTP polling is no longer required for normal dashboard use.

---

## 12. AI Coach / LLM Layer

The LLM coach is for teaching, narration, explanations, training prompts, and
natural-language interaction. It receives structured data: FEN, legal-move
count, robot status, and Stockfish lines. It is **not** a chess engine and does
not directly control motors.

Endpoint:

```http
POST /api/ai/coach
```

Example body:

```json
{"question": "Why is Stockfish recommending this move?", "style": "student"}
```

If no LLM API key is configured, the endpoint returns a local rule-based coach
response. To enable an OpenAI-compatible provider, set:

```env
LLM_COACH_ENABLED=true
LLM_API_BASE=https://api.openai.com/v1
LLM_API_KEY=...
LLM_MODEL=gpt-4o-mini
```

---

## 13. White-Centric Evaluation Policy

This is a project rule now:

```text
Positive score = White is better.
Negative score = Black is better.
```

This must remain true regardless of whose turn it is.

Good example:

```text
Black to move, current_display = +0.38
```

Meaning:

```text
White is slightly better, and Black is to move.
```

Bad behavior to avoid:

```text
Black to move, +0.38 means Black is better
```

That sign convention is not wanted in this project.

The new `/api/engine/live` endpoint follows the White-centric policy.

---

## 13. FEN Loading

The app supports loading a custom position from FEN.

Endpoint:

```http
POST /api/position/fen
```

PowerShell-safe test:

```powershell
$body = @{
  fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/position/fen" -ContentType "application/json" -Body $body

curl.exe "http://192.168.1.4:8000/api/engine/live?multipv=5"
```

Expected:

- Game state changes to the FEN.
- Legal moves update.
- Stockfish evaluates the loaded position.
- User can continue playing from that position.

---

## 14. PGN Loading

The app supports loading a PGN and jumping to the final position of its mainline.

Endpoint:

```http
POST /api/position/pgn
```

PowerShell-safe test:

```powershell
$pgn = @"
[Event "Test"]
[Site "?"]
[Date "2026.05.24"]
[Round "?"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 *
"@

$body = @{ pgn = $pgn } | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/position/pgn" -ContentType "application/json" -Body $body

curl.exe "http://192.168.1.4:8000/api/engine/live?multipv=5"
```

Expected final FEN:

```text
r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3
```

Then user can play from that position as if it were a puzzle setup.

---

## 15. Current Dashboard Usage Flow

1. Start the server on the Pi.
2. Open `http://192.168.1.4:8000`.
3. Hard refresh if old UI appears.
4. Use `New Game` to reset.
5. Watch the Stockfish panel update automatically.
6. Click a suggested Stockfish move or type a UCI move manually.
7. The board updates using `python-chess`.
8. The Stockfish panel recalculates every few seconds.
9. Paste a FEN or PGN into the Position Setup box if using puzzle-style play.
10. Load position and continue playing.

---

## 16. Known Safe/Unsafe Actions Right Now

### Safe right now

- Start server.
- Open dashboard.
- New game.
- Make software moves.
- Use Stockfish top moves.
- Load FEN.
- Load PGN.
- Call engine endpoints.
- Call hardware scan.
- View board snapshot.

### Do not use for physical motion yet

Do not use these as real hardware movement commands once motors are wired until safety checks are complete:

- Home
- Park
- Robot move
- Electromagnet commands
- Any future move command that physically moves motors

Right now no motors/drivers/electromagnet are wired, so they are not physically dangerous, but later they can become dangerous.

---

## 17. Why the Snapshot Is All Zeros

Current board snapshot from Teensy:

```json
"a1": {"o": 0, "p": 0, "m": 0}
```

Reason:

- No Hall sensors are wired.
- Teensy cannot detect pieces yet.
- Stockfish still works because it uses internal software game state.

Future sensor integration will connect:

- 64 Hall sensors
- 4× CD74HC4067 muxes
- calibrated thresholds
- per-square baseline readings

---

## 18. Why Some `/api/move/human` Calls Return 400

The server logs show some `POST /api/move/human` calls returning `400 Bad Request`.

That can happen when:

- The move is illegal in the current position.
- The same move is attempted after the turn has changed.
- The frontend click sends a stale suggested move from a previous position.
- A raw PowerShell JSON body is malformed.
- The board already advanced and the move is no longer legal.

This is not automatically a bug. It means `python-chess` rejected the move or the request was invalid.

---

## 19. Important PowerShell JSON Pattern

Use this pattern for JSON requests:

```powershell
$body = @{ uci = "e2e4" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/move/human" -ContentType "application/json" -Body $body
```

For FEN:

```powershell
$body = @{ fen = "FEN_HERE" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/position/fen" -ContentType "application/json" -Body $body
```

For PGN:

```powershell
$body = @{ pgn = $pgn } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://192.168.1.4:8000/api/position/pgn" -ContentType "application/json" -Body $body
```

---

## 20. Current Patch Files / Modified Areas

Relevant scripts/patches used during setup:

- `scripts/patch_stockfish_analysis.py`
- `scripts/patch_dynamic_stockfish_v3.py`
- `scripts/software_ready_check.py`

Important modified app files:

- `host/app/api/routes.py`
- `host/app/ui/static/app.js`
- `host/app/ui/static/style.css`

The v3 dynamic Stockfish patch was designed to be additive and safer than replacing the full app.

---

## 21. Troubleshooting

### App cannot find Stockfish

Check:

```bash
which stockfish
```

Expected:

```text
/usr/games/stockfish
```

Fix `.env`:

```env
STOCKFISH_PATH=/usr/games/stockfish
```

### Wrong serial device

Check:

```bash
ls -l /dev/serial/by-id/
```

Use:

```env
SERIAL_PORT=/dev/serial/by-id/usb-Teensyduino_USB_Serial_6634680-if00
```

Do not use:

```env
/dev/ttyACM0
```

as a long-term config value.

### The UI does not update

Hard refresh:

```text
Ctrl + Shift + R
```

Watch Uvicorn logs. You should see repeated:

```text
GET /api/engine/live?multipv=5
```

### Uvicorn shutdown traceback

If it appears only after pressing `Ctrl+C`, it is usually harmless.

### Favicon 404

Harmless.

### `.local` hostname does not work

Use:

```powershell
ssh shashwat@192.168.1.4
```

instead of:

```powershell
ssh shashwat@ghostmate.local
```

### Linux venv missing `bin/activate`

If the venv shows `Scripts`, `Lib`, and `Include`, it is a Windows venv and must be recreated on the Pi:

```bash
cd ~/Ghost-mate
deactivate 2>/dev/null || true
rm -rf venv .venv
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

---

## 22. Recommended Next Hardware Bring-Up Order

Do not wire everything at once.

Recommended sequence:

1. One endstop switch only.
2. Confirm Teensy reads switch state.
3. One TMC2209 driver + one NEMA 17 motor.
4. Test tiny step movement only.
5. Add second TMC2209 + second motor.
6. Test motors independently.
7. Attach CoreXY belts.
8. Test slow X/Y movement.
9. Add homing with endstops.
10. Add servo Z mechanism.
11. Add electromagnet MOSFET circuit.
12. Add one 4×4 Hall sensor tile.
13. Calibrate one tile.
14. Scale to full 8×8 Hall matrix.
15. Integrate physical board resync with software state.

---

## 23. Final Current Checkpoint

As of the latest verified state:

```text
✅ Raspberry Pi host works
✅ Linux venv fixed
✅ 562 tests pass
✅ Dashboard opens at http://192.168.1.4:8000
✅ Teensy 4.0 detected and used by stable serial ID
✅ Stockfish installed at /usr/games/stockfish
✅ python-chess works
✅ /api/engine/analysis works
✅ /api/engine/live works
✅ Dynamic Stockfish updates work
✅ White-centric eval works
✅ FEN loader works
✅ PGN final-position loader works
✅ User can play from loaded puzzle positions
⚠️ Hall sensors not wired yet
⚠️ Motors/drivers/electromagnet not wired yet
⚠️ Physical motion is not validated yet
```

---

## 24. Handoff Notes for Future Work

When continuing development, preserve these rules:

1. Raspberry Pi is the host brain.
2. Teensy 4.0 is the active hardware controller.
3. Keep the host-to-controller JSON protocol stable.
4. Stockfish eval must remain White-centric.
5. Dynamic UI should subscribe to `/ws?engine=1` for pushed `ENGINE_UPDATE` events.
6. Use PowerShell `Invoke-RestMethod` for JSON tests.
7. Software readiness check should stay hardware-independent.
8. Use `/dev/serial/by-id/...Teensyduino...`, not `/dev/ttyACM0`.
9. Do not wire motors until endstop and driver tests are planned carefully.
10. Do not trust all-zero board snapshots until Hall sensors are wired and calibrated.
