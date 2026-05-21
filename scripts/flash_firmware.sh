#!/usr/bin/env bash
set -euo pipefail
cd firmware/esp32
pio run
pio upload
pio device monitor
