from __future__ import annotations

import asyncio
import json
from pathlib import Path

from host.app.config import get_settings
from host.app.hardware.serial_link import JsonLineSerialClient


async def main() -> None:
    settings = get_settings()
    events = []

    async def callback(payload: dict) -> None:
        events.append(payload)

    client = JsonLineSerialClient(settings.serial_port, settings.serial_baud)
    client.set_event_callback(callback)
    await client.start()
    try:
        await client.send_command("scan", full=True)
        await asyncio.sleep(1)
    finally:
        await client.stop()

    Path("data/logs").mkdir(parents=True, exist_ok=True)
    Path("data/logs/calibration_scan.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
    print("Saved data/logs/calibration_scan.json")


if __name__ == "__main__":
    asyncio.run(main())
