#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-$PWD/venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

cd firmware/teensy40
"$PYTHON" -m platformio run
"$PYTHON" -m platformio upload
"$PYTHON" -m platformio device monitor
