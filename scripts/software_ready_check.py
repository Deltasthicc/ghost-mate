from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(name: str, command: list[str], cwd: Path | None = None) -> None:
    print(f"\n=== {name} ===")
    print(" ".join(command))

    result = subprocess.run(command, cwd=cwd or ROOT)

    if result.returncode != 0:
        raise SystemExit(f"❌ {name} failed with exit code {result.returncode}")

    print(f"✅ {name} passed")


def main() -> None:
    # Readiness checks must be hardware-independent.
    # Force mock serial so pytest/smoke tests do not talk to a real Teensy.
    os.environ["SERIAL_MOCK"] = "true"
    os.environ.setdefault("SERIAL_PORT", "MOCK")
    os.environ.setdefault("SERIAL_BAUD", "115200")

    parser = argparse.ArgumentParser(description="Run full software readiness checks.")
    parser.add_argument("--firmware", action="store_true", help="Also compile Teensy 4.0 firmware with PlatformIO.")
    args = parser.parse_args()

    run("Python compile check", [sys.executable, "-m", "compileall", "host", "scripts"])
    run("Pytest suite", [sys.executable, "-m", "pytest", "-q", "--maxfail=1", "--timeout=180"])
    run("HTTP/API smoke check", [sys.executable, "scripts/smoke_check.py"])

    if args.firmware:
        firmware_dir = ROOT / "firmware" / "teensy40"
        if not firmware_dir.exists():
            raise SystemExit("❌ firmware/teensy40 folder not found")

        run("Teensy 4.0 firmware build", [sys.executable, "-m", "platformio", "run"], cwd=firmware_dir)

    print("\n✅ SOFTWARE READINESS CHECK PASSED")
    print("The host app, API, rules engine, mock serial layer, WebSocket path, UI assets,")
    print("sensor-delta reconciliation, PGN replay, and edge-case chess logic are working.")
    print("Remaining validation requires real hardware: GPIO pins, motors, endstops, Hall sensors,")
    print("electromagnet driver, power rails, and mechanical calibration.")


if __name__ == "__main__":
    main()
