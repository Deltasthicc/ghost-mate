# Ghost-mate test fixes

Files included:
- host/app/domain/game_state.py: fixes flaky duplicate game IDs by adding a short UUID suffix to timestamp IDs.
- host/app/config.py: uses APP_DEBUG instead of generic DEBUG, so DEBUG=release from external tools cannot crash Pydantic settings parsing.
- host/app/api/ws.py: converts Event dataclasses/enums/datetimes to JSON-safe payloads before websocket send_json.
- .env.example: documents APP_DEBUG=true instead of DEBUG=true.

Verified commands run in the patched project at the time:
- python3 -m pytest host/tests/ -q → 562 passed
- DEBUG=release python3 -m pytest host/tests/ -q → 562 passed
- repeated targeted failing game-id tests → passed

Current full suite after the later UI, engine-settings, coach, and PGN work:
- SERIAL_MOCK=true python -m pytest host/tests -q → 859 passed
