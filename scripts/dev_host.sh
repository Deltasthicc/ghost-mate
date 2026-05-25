#!/usr/bin/env bash
# GhostMate host dev launcher (Linux/macOS).
# Picks the optimized event loop (uvloop) and httptools parser when available.
set -euo pipefail

python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate

# On Linux/macOS, install the [linux] extras for uvloop too.
if [[ "$(uname -s)" == "Linux" || "$(uname -s)" == "Darwin" ]]; then
  pip install -e '.[dev,linux]'
else
  pip install -e '.[dev]'
fi

# uvicorn flags:
#   --loop uvloop          fastest event loop on Linux/Mac
#   --http httptools       fastest HTTP parser
#   --no-access-log        skip per-request log overhead
#   --reload               dev convenience (still cheap)
exec uvicorn host.app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --loop uvloop \
  --http httptools \
  --no-access-log \
  --reload
