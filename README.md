# Autonomous CoreXY Chess Robot

A modular starter codebase for an autonomous CoreXY chess robot with:

- ESP32 firmware for CoreXY motion, Hall sensor scanning, Z-servo, electromagnet control, endstops, and line-delimited JSON serial protocol.
- Python/FastAPI host for chess rules, Stockfish integration, board-state reconciliation, motion commands, WebSocket UI updates, calibration storage, and provider abstraction.
- Mock hardware mode so the host app can run before the physical robot is assembled.

## Architecture

```text
Physical board + pieces + sensors + steppers
        |
        v
ESP32 firmware
  - CoreXY motion
  - Hall scan
  - Z servo
  - electromagnet
  - JSON serial protocol
        |
        v
Python host
  - FastAPI + WebSockets
  - python-chess rules
  - Stockfish UCI
  - Lichess provider skeleton
  - SQLModel DB
```

## Quick start: host app

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env
uvicorn host.app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

By default, the host runs in mock-serial mode, so it works even without the ESP32 connected.

## Quick start: firmware

Install the PlatformIO extension in VS Code. Then:

```powershell
cd firmware\esp32
pio run
pio upload
pio device monitor
```

Before connecting real motors or the electromagnet, verify and update all GPIO pin assignments in:

```text
firmware/esp32/include/config.hpp
```

## Important safety notes

- Never test the electromagnet directly from an ESP32 pin. Use a MOSFET driver and flyback diode.
- Use current-limited stepper drivers.
- Keep 24 V motor power separated from 5 V and 3.3 V logic rails.
- Calibrate Hall baselines with an empty board before relying on move detection.
- Run the host in mock mode first, then serial mode, then motor-power mode.

## Main run modes

- Local engine: human over-the-board vs Stockfish.
- Online board provider skeleton: human over-the-board vs remote moves.
- Lichess bot provider skeleton: bot account integration placeholder.
- Cloud relay provider skeleton: REST/WebSocket relay placeholder.
- Null/referee mode can be built by listening only to board scans and legal move validation.
