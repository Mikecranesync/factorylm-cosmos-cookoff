"""
VFD Reader — Async Modbus TCP reader for ATO GS10 VFD.

Reads 14 VFD registers through Modbus TCP (direct or PLC bridge).
Follows the same connect/tick/reconnect pattern as ModbusTagSource.

Usage:
    reader = VfdReader("192.168.1.101", port=502, slave=1)
    if reader.connect():
        data = reader.tick()
        print(data)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ATO GS10 fault code descriptions
VFD_FAULT_CODES = {
    0: "No fault",
    1: "Overcurrent during acceleration",
    2: "Overcurrent during deceleration",
    3: "Overcurrent at constant speed",
    4: "Overvoltage during acceleration",
    5: "Overvoltage during deceleration",
    6: "Overvoltage at constant speed",
    7: "DC bus undervoltage",
    8: "Drive overtemperature",
    9: "Motor overload",
    10: "Input phase loss",
    11: "Output phase loss",
    12: "External fault",
    13: "Communication loss",
}

# Register map: (address, tag_name, scale_divisor)
# Writable registers
_WRITE_REGS = [
    (0x2000, "vfd_control_word", 1),
    (0x2001, "vfd_setpoint_hz", 100),
]

# Read-only status registers (contiguous block 0x2100-0x210B)
_STATUS_REGS = [
    (0x2100, "vfd_status_word", 1),
    (0x2101, "vfd_output_hz", 100),
    (0x2102, "vfd_output_amps", 10),
    (0x2103, "vfd_actual_freq", 100),
    (0x2104, "vfd_actual_current", 10),
    (0x2105, "vfd_dc_bus_volts", 10),
    (0x2106, "vfd_motor_rpm", 1),
    (0x2107, "vfd_torque_pct", 10),
    (0x2108, "vfd_drive_temp_c", 10),
    (0x2109, "vfd_fault_code", 1),
    (0x210A, "vfd_warning_code", 1),
    (0x210B, "vfd_run_hours", 1),
]


class VfdReader:
    """Reads ATO GS10 VFD registers via Modbus TCP."""

    def __init__(self, host: str, port: int = 502, slave: int = 1) -> None:
        self.host = host
        self.port = port
        self.slave = slave
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
                "VfdReader connected to %s:%d slave=%d",
                self.host, self.port, self.slave,
            )
            return True

        logger.warning(
            "VfdReader connection failed to %s:%d", self.host, self.port
        )
        self._client = None
        return False

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_socket_open()

    def tick(self) -> dict:
        """Read all VFD registers and return a flat dict.

        Auto-reconnects if the socket is dead.
        Returns error dict on failure.
        """
        if not self.connected:
            if not self.connect():
                return self._error("connection failed")

        try:
            data = {"vfd_connected": True}

            # Batch 1: writable registers (0x2000-0x2001)
            result = self._client.read_holding_registers(
                address=0x2000, count=2, slave=self.slave,
            )
            if result.isError():
                self._close()
                return self._error("writable register read error")

            for i, (addr, tag, scale) in enumerate(_WRITE_REGS):
                raw = result.registers[i]
                data[tag] = raw if scale == 1 else round(raw / scale, 2)

            # Batch 2: status registers (0x2100-0x210B)
            result = self._client.read_holding_registers(
                address=0x2100, count=12, slave=self.slave,
            )
            if result.isError():
                self._close()
                return self._error("status register read error")

            for i, (addr, tag, scale) in enumerate(_STATUS_REGS):
                raw = result.registers[i]
                data[tag] = raw if scale == 1 else round(raw / scale, 2)

            # Map fault code to description
            fault_code = data.get("vfd_fault_code", 0)
            data["vfd_fault_description"] = VFD_FAULT_CODES.get(
                fault_code, f"Unknown fault {fault_code}"
            )

            return data

        except Exception as e:
            logger.warning("VfdReader read error: %s", e)
            self._close()
            return self._error(str(e))

    def _close(self):
        if self._client:
            self._client.close()
            self._client = None

    def _error(self, reason: str) -> dict:
        return {
            "vfd_connected": False,
            "vfd_fault_description": f"Communication loss: {reason}",
        }
