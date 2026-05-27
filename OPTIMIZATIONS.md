# GhostMate Optimization Pass

All 859 automated tests pass. The host's core HTTP routes, WebSocket payloads,
and Teensy JSON protocol stay compatible; the current app also adds live engine
settings, move history, PGN export, and the board-support coach/history layout.

## Headline numbers

| Hot path | Before | After |
|---|---|---|
| `GameState.snapshot()` | ~500 ms (spawned Stockfish each call) | 1 µs cached / 8 µs fresh |
| `/api/state` round-trip | 500 ms+ | <10 ms |
| WebSocket event → UI update | 2 HTTP round-trips | 0 (state embedded) |
| Stockfish best-move | ~500 ms cold every call | persistent + LRU cached |
| Hall scan, full board | ~60 ms blocking | ~5 ms in 64 cooperative ticks |
| Teensy main loop | blocked during moves | future non-blocking FSM |
| Browser board re-render | 64 × `createElement`/`addEventListener` | text/class diff only |
| Test suite | 7.9 s | 5.3 s |

## Host (Python)

### `host/app/chesscore/engine_service.py` — persistent Stockfish
- Single long-lived `chess.engine.SimpleEngine`, started once at app boot.
- All calls go through one `asyncio.Lock`, so no subprocess respawn per request.
- LRU analysis cache (5000 entries) keyed on Zobrist transposition key + multipv
  + time budget. Most board re-renders hit the cache.
- `restart-on-error` so a Stockfish crash doesn't poison the whole app.
- Returns canonical *and* legacy field aliases so old clients keep working.
- Graceful material-only fallback when the binary is missing.

### `host/app/domain/game_state.py` — engine-free snapshots
- `snapshot()` no longer spawns Stockfish. It builds purely from python-chess.
- Internal cache invalidated only on `new_game` / `push_uci` / `push_san` so
  repeated `/api/state` and `HELLO` payloads cost ~1 µs.
- Added `ply`, `halfmove_clock`, `fullmove_number` to the snapshot.

### `host/app/api/routes.py` — single analysis path + live settings
- Removed the duplicate `_gm_*` analysis block (was running two engines).
- `/api/engine/live` is now an alias for `/api/engine/analysis` (server-side
  semantic identical), backed by the persistent service.
- New `/api/engine/bestmove` POST for direct best-move queries.
- New `/api/engine/settings` GET/POST for live depth, search-time, MultiPV,
  threads, and hash-memory tuning.
- `LOCAL_MOVE_CANDIDATE` and `ROBOT_MOVE_COMPLETE` events now embed the full
  next-state snapshot, eliminating a follow-up GET round-trip from the UI.

### `host/app/api/ws.py` — fast text frames
- orjson when available (3-5× faster JSON).
- 15 s heartbeat PING.
- Drop-oldest-on-full subscriber queue (slow clients can't stall the bus).

### `host/app/main.py` — clean lifespan
- Starts `StockfishService` in the background so app boot is instant.
- Embeds fresh state in `ROBOT_MOVE_COMPLETE` events.
- Uvloop is picked by uvicorn via `--loop uvloop` (see `scripts/run_host_pi.sh`).

### `host/app/db/session.py` — SQLite WAL + sane pragmas
- WAL journal, `synchronous=NORMAL`, 20 MB cache, 128 MB mmap, busy_timeout=5s.
- `pool_pre_ping=True` to recover from dropped connections.
- `echo` controlled by a dedicated `SQL_ECHO` env (not `APP_DEBUG`).

### `host/app/domain/events.py` — lock-free publish
- Iteration over a tuple snapshot of subscribers — no lock on the hot path.
- Slow queue gets oldest event evicted, then the new one is delivered.
- Added `ENGINE_UPDATE` event type and a `publish_nowait` for sync callbacks.

### `host/app/hardware/serial_link.py`
- orjson for line parse + encode.
- Write coalescing (only `drain()` when buffer >4 KB).
- Pending futures cancelled on stop; per-message timeout cleanup.
- Default baud is 115 200 for the Teensy 4.0 USB serial path.

### `host/app/hardware/board_sensor.py`
- Precomputed 64-square name table, shared `_EMPTY_CELL` instance, `__slots__`.

### `host/app/config.py`
- New knobs: `sql_echo`, `engine_eval_time_s`, `engine_threads`,
  `engine_hash_mb`, `engine_skill_level`, `ws_max_queue`, `state_throttle_ms`.
- Default `serial_port` now targets the stable Teensy by-id path. Default `debug` is False.

## Browser (UI)

### `host/app/ui/static/app.js` — single source of truth
- WebSocket is authoritative. We no longer poll `/api/state` after every event.
- Board built **once** at boot. Subsequent renders mutate `textContent` and
  `className` only — no `createElement` / `innerHTML` churn.
- One delegated click listener on `#chessboard` (was 64).
- `requestAnimationFrame`-coalesced renders.
- Engine refresh is debounced and keyed on the position FEN (no 3 s polling).
- Engine controls now expose max depth (default 24, cap 30), per-depth search
  time, MultiPV line count, threads, and Stockfish hash memory.
- Move history and the AI coach live directly below the chessboard to use the
  previously empty board-column space.
- Sensor grid also built once, diffed on update.
- WS exponential backoff (250 ms → 8 s cap).
- ~300 lines shorter than the original despite more features.

### `host/app/ui/static/style.css` — GPU-friendly globals
- New header block prepended; original styles preserved.
- `--glass-blur: blur(10px)` (was 26 px) — `backdrop-filter` is the single
  biggest GPU cost on a Pi 4 touchscreen.
- `@media (max-width: 1024px)` disables blur and hides ambient blobs.
- `@media (prefers-reduced-motion: reduce)` disables transitions/animations.
- `.chessboard, .sensor-grid { will-change: contents; transform: translateZ(0) }`
  promotes them to their own compositor layers.
- `.square, .sensor-cell { contain: layout style paint }` so a piece change
  doesn't trigger a full panel repaint.

### `host/app/ui/templates/index.html`
- `<link rel="preload">` for app.js and style.css.
- `<script defer>` in `<head>` (was a blocking tag at end of body).

## Firmware (Teensy 4.0)

### `firmware/teensy40/platformio.ini`
- Active PlatformIO target is `teensy40`.
- `monitor_speed = 115200`.
- ArduinoJson is the only external firmware dependency.

### `firmware/teensy40/include/config.hpp`
- `SERIAL_BAUD = 115200`.
- Teensy 4.0 pin map for CoreXY steppers, endstops, e-stop, Z servo,
  electromagnet, and four CD74HC4067 Hall muxes.
- Conservative blocking step pulse timing for first hardware bring-up.

### `hall_scan.{hpp,cpp}`
- Tracks polarity separately from magnitude.
- Full `scanAndWriteJson()` retained for explicit `scan` commands.
- Uses Teensy 12-bit ADC reads through four mux signal pins.

### `corexy.{hpp,cpp}`
- Teensy-compatible blocking CoreXY step pulse generation.
- No board-specific stepper library dependency remains.

### `z_axis.{hpp,cpp}`
- Uses the Teensy/Arduino `Servo` library for PWM.

### `protocol.{hpp,cpp}`
- Preserves the host command/reply/event JSON format.

### `main.cpp`
- Boots as `controller=teensy40`.
- Handles `home`, `scan`, `move`, `capture_move`, `park`, `set_em`, and
  `calibrate` over the same newline-delimited JSON protocol.

## Scripts / config
- `scripts/dev_host.sh` — uvloop + httptools + `--no-access-log`.
- `scripts/run_host_pi.sh` — new production launcher for the Pi.
- `.env.example` — defaults to the stable Teensy by-id path and 115200 baud.

## Things explicitly **not** changed
- HTTP route shapes — unchanged so existing clients keep working.
- The controller JSON protocol — unchanged so the host transport remains simple.
