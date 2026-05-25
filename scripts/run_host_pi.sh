#!/usr/bin/env bash
# GhostMate production launcher for Raspberry Pi 4.
# Designed to be invoked from a systemd unit. No --reload, single worker
# (we hold global state in app.state), uvloop + httptools.
set -euo pipefail

cd "$(dirname "$0")/.."
source venv/bin/activate

exec uvicorn host.app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --loop uvloop \
  --http httptools \
  --no-access-log \
  --workers 1 \
  --proxy-headers
