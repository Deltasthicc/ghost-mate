# Ghost-mate pytest startup fix

## What was broken

Pytest was failing during collection because `host.app.main` imports settings at module import time, and `Settings.debug` was reading the generic environment variable `DEBUG`.

On the machine that produced the log, `DEBUG` had the value `release`. Pydantic expects a boolean for `debug`, so it crashed before tests could run:

```text
Input should be a valid boolean, unable to interpret input [type=bool_parsing, input_value='release']
```

## Fix applied

1. Renamed the app-specific environment variable from `DEBUG` to `APP_DEBUG` in `.env` and `.env.example`.
2. Updated `host/app/config.py` so `settings.debug` reads only `APP_DEBUG`, avoiding collisions with tools that set `DEBUG=release`.
3. Fixed the next test-suite failure in `host/app/api/ws.py`: WebSocket code was sending an `Event` dataclass directly through `send_json`, which is not JSON serializable. It now uses FastAPI's `jsonable_encoder` before sending.

## Verified

From the patched project root, with `DEBUG=release` still set:

```powershell
pytest host/tests/ -q
```

Historical result from that fix run:

```text
562 passed in 13.38s
```

Current full suite after the later UI, engine-settings, coach, and PGN work:

```text
859 passed
```
