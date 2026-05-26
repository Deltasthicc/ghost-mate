# Serial Protocol

Every host-to-Teensy message is one JSON object followed by `\n`.

## Host commands

```json
{"id": 1, "cmd": "home"}
{"id": 2, "cmd": "scan", "full": true}
{"id": 3, "cmd": "move", "from": "e2", "to": "e4", "capture": false}
{"id": 4, "cmd": "capture_move", "victim": "d5", "from": "e4", "to": "d5"}
{"id": 5, "cmd": "park"}
{"id": 6, "cmd": "set_em", "on": true}
```

## Teensy replies

```json
{"id": 1, "ok": true}
{"id": 3, "ok": false, "err": "not_homed"}
```

## Teensy async events

```json
{"type": "scan", "ts_ms": 482310, "cells": {"e2": {"o": 1, "p": 1, "m": 812}}}
{"type": "motion_done", "id": 3}
{"type": "fault", "code": "pickup_lost", "square": "e2"}
```

Compact scan keys:

- `o`: occupancy, 0 or 1
- `p`: polarity, -1, 0, +1
- `m`: absolute magnetic magnitude after baseline subtraction
