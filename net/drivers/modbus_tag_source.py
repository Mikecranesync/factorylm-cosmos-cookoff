"""
Canonical Modbus tag source for Micro 820 PLC.

Reads coils 0-17 and holding registers 100-105 using the canonical
address map from CLAUDE.md, and returns TagSnapshot objects.

Usage:
    source = ModbusTagSource("192.168.1.100", 502)
    if source.connect():
        snap = source.tick()
        print(snap.to_dict())
"""
from __future__ import annotations

import datetime
import logging

from net.models.tags import ERROR_CODES, TagSnapshot

logger = logging.getLogger(__name__)


class ModbusTagSource:
    """Reads canonical Micro 820 tags via Modbus TCP and returns TagSnapshot."""

    def __init__(self, host: str, port: int = 502) -> None:
        self.host = host
        self.port = port
        self._client = None

    def connect(self) -> bool:
        """Create a Modbus TCP connection. Returns True on success."""
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError:
            logger.error("pymodbus not installed — pip install pymodbus")
            return False

        self._client = ModbusTcpClient(self.host, port=self.port, timeout=3)
        if self._client.connect():
            logger.info(
                "ModbusTagSource connected to %s:%d", self.host, self.port
            )
            return True

        logger.warning(
            "ModbusTagSource connection failed to %s:%d", self.host, self.port
        )
        self._client = None
        return False

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_socket_open()

    def tick(self) -> TagSnapshot:
        """Read all canonical tags and return a TagSnapshot.

        Auto-reconnects if the socket is dead.
        Returns a comms-fault snapshot on read failure.
        """
        if not self.connected:
            if not self.connect():
                return self._error_snapshot("connection failed")

        try:
            # Read coils 0-17
            coil_result = self._client.read_coils(address=0, count=18)
            if coil_result.isError():
                self._client.close()
                self._client = None
                return self._error_snapshot("coil read error")

            coils = [bool(b) for b in coil_result.bits[:18]]

            # Read holding registers 100-105
            reg_result = self._client.read_holding_registers(
                address=100, count=6
            )
            if reg_result.isError():
                self._client.close()
                self._client = None
                return self._error_snapshot("register read error")

            regs = reg_result.registers

            # --- Map to TagSnapshot fields ---

            # Coil 0 -> conveyor_running / motor_running
            conveyor_running = coils[0]
            motor_running = coils[0]

            # Coils 2, 3 -> SensorStart, SensorEnd
            sensor_1 = coils[2]
            sensor_2 = coils[3]

            # E-stop dual-contact validation: coil[8] AND NOT coil[9]
            e_stop_no = coils[8]
            e_stop_nc = coils[9]
            fault_alarm = e_stop_no and not e_stop_nc
            e_stop = fault_alarm

            # Registers (with scaling)
            motor_speed = regs[1]           # reg 101, 1x
            motor_current = regs[2] / 10.0  # reg 102, /10
            temperature = regs[3] / 10.0    # reg 103, /10
            pressure = regs[4]              # reg 104, 1x
            error_code = regs[5]            # reg 105, 1x

            return TagSnapshot(
                timestamp=datetime.datetime.now(
                    tz=datetime.timezone.utc
                ).isoformat(),
                node_id=f"plc-{self.host}",
                motor_running=motor_running,
                motor_speed=motor_speed,
                motor_current=round(motor_current, 1),
                temperature=round(temperature, 1),
                pressure=pressure,
                conveyor_running=conveyor_running,
                conveyor_speed=motor_speed,
                sensor_1=sensor_1,
                sensor_2=sensor_2,
                fault_alarm=fault_alarm,
                e_stop=e_stop,
                error_code=error_code,
                error_message=ERROR_CODES.get(
                    error_code, f"Unknown error {error_code}"
                ),
            )

        except Exception as e:
            logger.warning("ModbusTagSource read error: %s", e)
            if self._client:
                self._client.close()
                self._client = None
            return self._error_snapshot(str(e))

    def _error_snapshot(self, reason: str) -> TagSnapshot:
        """Return a comms-fault snapshot (error_code=5)."""
        return TagSnapshot(
            timestamp=datetime.datetime.now(
                tz=datetime.timezone.utc
            ).isoformat(),
            node_id=f"plc-{self.host}",
            motor_running=False,
            motor_speed=0,
            motor_current=0.0,
            temperature=0.0,
            pressure=0,
            conveyor_running=False,
            conveyor_speed=0,
            sensor_1=False,
            sensor_2=False,
            fault_alarm=True,
            e_stop=False,
            error_code=5,
            error_message=f"Communication loss: {reason}",
        )
