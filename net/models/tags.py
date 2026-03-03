"""
Shared tag models for Pi Factory Net.

TagSnapshot is the canonical representation of a single point-in-time
reading of all PLC tags. Used by ModbusTagSource, Poller, and the API.
"""
from __future__ import annotations

import dataclasses
import json

# Error codes matching the Micro 820 / FactoryLM conveyor system
ERROR_CODES = {
    0: "No error",
    1: "Motor overload",
    2: "Temperature high",
    3: "Conveyor jam",
    4: "Sensor failure",
    5: "Communication loss",
}

FAULT_MAP = {
    "jam": 3,
    "overload": 1,
    "overheat": 2,
    "sensor": 4,
    "comms": 5,
}


@dataclasses.dataclass
class TagSnapshot:
    """A single point-in-time reading of all PLC tags."""

    timestamp: str
    node_id: str
    motor_running: bool
    motor_speed: int
    motor_current: float
    temperature: float
    pressure: int
    conveyor_running: bool
    conveyor_speed: int
    sensor_1: bool
    sensor_2: bool
    fault_alarm: bool
    e_stop: bool
    error_code: int
    error_message: str
    coils: list        # raw 18-element list of 0/1 ints
    io: dict           # named coils for panel display
    e_stop_ok: bool    # True when E-stop is released (safe state)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())
