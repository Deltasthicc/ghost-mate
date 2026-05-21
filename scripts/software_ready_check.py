from __future__ import annotations

import argparse
import shutil
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
    parser = argparse.ArgumentParser(description="Run full software readiness checks.")
    parser.add_argument("--firmware", action="store_true", help="Also compile ESP32 firmware with PlatformIO.")
    args = parser.parse_args()

    run("Python compile check", [sys.executable, "-m", "compileall", "host", "scripts"])
    run("Pytest suite", [sys.executable, "-m", "pytest", "-q"])
    run("HTTP/API smoke check", [sys.executable, "scripts/smoke_check.py"])

    if args.firmware:
        firmware_dir = ROOT / "firmware" / "esp32"
        if not firmware_dir.exists():
            raise SystemExit("❌ firmware/esp32 folder not found")

        run("ESP32 firmware build", [sys.executable, "-m", "platformio", "run"], cwd=firmware_dir)

    print("\n✅ SOFTWARE READINESS CHECK PASSED")
    print("The host app, API, rules engine, mock serial layer, WebSocket path, UI assets,")
    print("sensor-delta reconciliation, PGN replay, and edge-case chess logic are working.")
    print("Remaining validation requires real hardware: GPIO pins, motors, endstops, Hall sensors,")
    print("electromagnet driver, power rails, and mechanical calibration.")


if __name__ == "__main__":
    main()
