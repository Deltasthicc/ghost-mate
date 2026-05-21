#!/usr/bin/env bash
set -euo pipefail
python3 -m venv venv
source venv/bin/activate
pip install -e '.[dev]'
uvicorn host.app.main:app --reload
