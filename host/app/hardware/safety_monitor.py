from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SafetyMonitor:
    homed: bool = False
    robot_busy: bool = False
    electromagnet_on: bool = False
    fault_code: str | None = None

    def assert_can_move(self) -> None:
        if self.fault_code:
            raise RuntimeError(f"Cannot move while fault is active: {self.fault_code}")
        if not self.homed:
            raise RuntimeError("Cannot move before homing")
        if self.robot_busy:
            raise RuntimeError("Cannot start motion while robot is busy")

    def set_fault(self, code: str) -> None:
        self.fault_code = code
        self.robot_busy = False
        self.electromagnet_on = False

    def clear_fault(self) -> None:
        self.fault_code = None
