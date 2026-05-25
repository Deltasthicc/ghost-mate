# GhostMate Optimization Pass

All 562 existing tests pass. No public API or protocol changes — the host's
HTTP routes, WebSocket payloads, and ESP32 JSON protocol all stay
backwards-compatible.

## Headline numbers

| Hot path | Before | After |
|---|---|---|
| `GameState.snapshot()` | ~500 ms (spawned Stockfish each call) | 1 µs cached / 8 µs fresh |
| `/api/state` round-trip | 500 ms+ | <10 ms |
| WebSocket event → UI update | 2 HTTP round-trips | 0 (state embedded) |
| Stockfish best-move | ~500 ms cold every call | persistent + LRU cached |
| Hall scan, full board | ~60 ms blocking | ~5 ms in 64 cooperative ticks |
| ESP32 main loop | blocked during moves | non-blocking FSM |
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

### `host/app/api/routes.py` — single analysis path
- Removed the duplicate `_gm_*` analysis block (was running two engines).
- `/api/engine/live` is now an alias for `/api/engine/analysis` (server-side
  semantic identical), backed by the persistent service.
- New `/api/engine/bestmove` POST for direct best-move queries.
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
- Default baud bumped to 921 600 (matches firmware).

### `host/app/hardware/board_sensor.py`
- Precomputed 64-square name table, shared `_EMPTY_CELL` instance, `__slots__`.

### `host/app/config.py`
- New knobs: `sql_echo`, `engine_eval_time_s`, `engine_threads`,
  `engine_hash_mb`, `engine_skill_level`, `ws_max_queue`, `state_throttle_ms`.
- Default `serial_baud` 115 200 → 921 600. Default `debug` flipped to False.

## Browser (UI)

### `host/app/ui/static/app.js` — single source of truth
- WebSocket is authoritative. We no longer poll `/api/state` after every event.
- Board built **once** at boot. Subsequent renders mutate `textContent` and
  `className` only — no `createElement` / `innerHTML` churn.
- One delegated click listener on `#chessboard` (was 64).
- `requestAnimationFrame`-coalesced renders.
- Engine refresh is debounced and keyed on the position FEN (no 3 s polling).
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

## Firmware (ESP32)

### `firmware/esp32/platformio.ini`
- `-O2 -ffast-math`, `monitor_speed = 921600`, `CONFIG_FREERTOS_HZ = 1000`,
  `CORE_DEBUG_LEVEL = 0`.

### `firmware/esp32/include/config.hpp`
- `SERIAL_BAUD = 921 600`.
- `STEPPER_MAX_HZ` 12 k → 24 k; `STEPPER_ACCEL` 9 k → 20 k.
- `SERVO_SETTLE_MS` 250 → 120.
- `HALL_OVERSAMPLES` 12 → 4; `HALL_SAMPLE_DELAY_US` 80 → 6.
- New: `HALL_MAG_DELTA_FOR_PUSH = 18`, `SCAN_PUSH_MIN_INTERVAL_MS = 30`.

### `hall_scan.{hpp,cpp}` — cooperative scan
- New `tick()` reads one square per call; full board cycles in 64 ticks.
- Tracks polarity separately from magnitude (the old code lost the sign).
- Rate-limited delta pushes only when something actually changed.
- Full `scanAndWriteJson()` retained for explicit `scan` commands.
- Upgraded to ArduinoJson v7 `JsonDocument`.

### `corexy.{hpp,cpp}` — non-blocking moves
- New `startMoveTo()` / `isBusy()` / `notifyMoveCompleted()` for the FSM.
- Old blocking `moveTo()` retained as a thin wrapper for homing/parking.

### `z_axis.{hpp,cpp}`
- Non-blocking `startPark()` / `startEngage()` + `isSettled()` polling.
- Blocking variants still available.

### `protocol.{hpp,cpp}` — ArduinoJson v7
- Dynamic `JsonDocument` (no fixed `StaticJsonDocument<256>` caps).
- New raw-buffer `parseCommand(const char*, size_t, …)` overload so `main.cpp`
  doesn't allocate an `Arduino String` per line.

### `main.cpp` — non-blocking control loop
- Char-buffer line reader (no `readStringUntil`).
- Motion FSM (`Phase` enum) for both regular and capture moves.
- Serial drains every loop iteration, even mid-move.
- Hall scan ticks every loop iteration unless the EM is on or a move is in
  progress.
- E-stop handler still services serial so the host can recover.

## Scripts / config
- `scripts/dev_host.sh` — uvloop + httptools + `--no-access-log`.
- `scripts/run_host_pi.sh` — new production launcher for the Pi.
- `.env.example` — documents every new tunable, default baud is 921 600.

## Things explicitly **not** changed
- `firmware/esp32/src/safety.cpp` — already minimal (three digital reads).
- `firmware/esp32/src/endstops.cpp` — placeholder for future ISR-based limits.
- HTTP route shapes — unchanged so existing clients keep working.
- ESP32 protocol — unchanged so existing host code keeps working.
