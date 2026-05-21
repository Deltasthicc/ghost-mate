from __future__ import annotations

from dataclasses import dataclass

from host.app.hardware.serial_link import BaseJsonLineClient, CommandReply


@dataclass
class MotionService:
    serial: BaseJsonLineClient

    async def home(self) -> CommandReply:
        return await self.serial.send_command("home")

    async def park(self) -> CommandReply:
        return await self.serial.send_command("park")

    async def scan(self, full: bool = True) -> CommandReply:
        return await self.serial.send_command("scan", full=full)

    async def set_electromagnet(self, on: bool) -> CommandReply:
        return await self.serial.send_command("set_em", on=on)

    async def move_square_to_square(self, source: str, target: str, capture: bool = False) -> CommandReply:
        return await self.serial.send_command("move", **{"from": source, "to": target, "capture": capture})

    async def capture_move(self, victim: str, source: str, target: str) -> CommandReply:
        return await self.serial.send_command(
            "capture_move", victim=victim, **{"from": source, "to": target}
        )
