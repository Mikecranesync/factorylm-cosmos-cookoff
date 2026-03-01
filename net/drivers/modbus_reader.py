"""
Template-driven Modbus TCP reader.

Refactored from sim/factoryio_bridge.py ModbusReader. Accepts tag configuration
from JSON templates instead of hardcoded dictionaries.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ModbusReader:
    """Persistent Modbus TCP connection for high-frequency polling."""

    def __init__(
        self,
        host: str,
        port: int,
        template: dict,
        custom_names: dict[str, str] | None = None,
    ):
        self.host = host
        self.port = port
        self.template = template
        self.custom_names = custom_names or {}
        self._client = None

        # Parse template into coil/register maps
        self.coil_map: dict[int, dict] = {}
        for addr_str, info in template.get("coils", {}).items():
            self.coil_map[int(addr_str)] = info

        self.register_map: dict[int, dict] = {}
        for addr_str, info in template.get("registers", {}).items():
            self.register_map[int(addr_str)] = info

    def connect(self) -> bool:
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError:
            logger.error("pymodbus not installed. Run: pip install pymodbus")
            return False

        self._client = ModbusTcpClient(self.host, port=self.port, timeout=3)
        if self._client.connect():
            logger.info("Modbus connected to %s:%d", self.host, self.port)
            return True
        logger.warning("Modbus connection failed to %s:%d", self.host, self.port)
        self._client = None
        return False

    def disconnect(self):
        if self._client:
            self._client.close()
            self._client = None

    @property
    def connected(self) -> bool:
        return self._client is not None and self._client.is_socket_open()

    def read_tags(self) -> dict[str, Any] | None:
        """Read all mapped tags from template. Returns None on error."""
        if not self.connected and not self.connect():
            return None

        try:
            tags: dict[str, Any] = {
                "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
                "node_id": f"plc-{self.host}",
            }

            # Read coils
            if self.coil_map:
                coil_addrs = sorted(self.coil_map.keys())
                coil_start = coil_addrs[0]
                coil_count = coil_addrs[-1] - coil_start + 1

                result = self._client.read_coils(address=coil_start, count=coil_count)
                if result.isError():
                    logger.warning("Coil read error")
                    self.disconnect()
                    return None

                bits = list(result.bits[:coil_count])
                for addr, info in self.coil_map.items():
                    tag_name = self.custom_names.get(info["tag"], info["tag"])
                    tags[tag_name] = bool(bits[addr - coil_start])

            # Read holding registers
            if self.register_map:
                reg_addrs = sorted(self.register_map.keys())
                reg_start = reg_addrs[0]
                reg_count = reg_addrs[-1] - reg_start + 1

                result = self._client.read_holding_registers(
                    address=reg_start, count=reg_count
                )
                if result.isError():
                    logger.warning("Register read error")
                    self.disconnect()
                    return None

                values = result.registers
                for addr, info in self.register_map.items():
                    tag_name = self.custom_names.get(info["tag"], info["tag"])
                    raw = values[addr - reg_start]
                    scale = info.get("scale", 1)
                    if scale != 1:
                        tags[tag_name] = round(raw * scale, 2)
                    else:
                        tags[tag_name] = raw

            return tags

        except Exception as e:
            logger.warning("Modbus read error: %s", e)
            self.disconnect()
            return None

    def brute_force_scan(
        self,
        coil_range: tuple[int, int] = (0, 999),
        register_range: tuple[int, int] = (0, 999),
        batch_size: int = 10,
    ) -> list[dict]:
        """Scan coils and holding registers in batches to discover active tags.

        Returns a list of dicts: [{name, type, value, address}, ...]
        """
        if not self.connected and not self.connect():
            return []

        tags: list[dict] = []

        # Scan coils
        for start in range(coil_range[0], coil_range[1] + 1, batch_size):
            count = min(batch_size, coil_range[1] + 1 - start)
            try:
                result = self._client.read_coils(address=start, count=count)
                if result.isError():
                    continue
                for i, val in enumerate(result.bits[:count]):
                    if val:  # Only report non-zero coils
                        addr = start + i
                        tags.append({
                            "name": f"coil_{addr}",
                            "type": "BOOL",
                            "value": bool(val),
                            "address": f"coil:{addr}",
                        })
            except Exception:
                continue

        # Scan holding registers
        for start in range(register_range[0], register_range[1] + 1, batch_size):
            count = min(batch_size, register_range[1] + 1 - start)
            try:
                result = self._client.read_holding_registers(address=start, count=count)
                if result.isError():
                    continue
                for i, val in enumerate(result.registers):
                    if val != 0:  # Only report non-zero registers
                        addr = start + i
                        tags.append({
                            "name": f"register_{addr}",
                            "type": "INT",
                            "value": val,
                            "address": f"hr:{addr}",
                        })
            except Exception:
                continue

        return tags


def sim_brute_force_scan() -> list[dict]:
    """Return simulated brute-force scan results for a Micro 820."""
    return [
        {"name": "Conveyor", "type": "BOOL", "value": True, "address": "coil:0"},
        {"name": "Emitter", "type": "BOOL", "value": False, "address": "coil:1"},
        {"name": "SensorStart", "type": "BOOL", "value": False, "address": "coil:2"},
        {"name": "SensorEnd", "type": "BOOL", "value": False, "address": "coil:3"},
        {"name": "item_count", "type": "INT", "value": 247, "address": "hr:100"},
        {"name": "motor_speed", "type": "INT", "value": 85, "address": "hr:101"},
        {"name": "motor_current", "type": "REAL", "value": 12.5, "address": "hr:102"},
        {"name": "temperature", "type": "REAL", "value": 48.7, "address": "hr:103"},
        {"name": "pressure", "type": "INT", "value": 60, "address": "hr:104"},
        {"name": "error_code", "type": "INT", "value": 0, "address": "hr:105"},
    ]
