"""Tests for ModbusTagSource — mocked, no real PLC needed."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from net.models.tags import TagSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_coil_response(bits: list[bool]):
    """Create a mock coil read response."""
    resp = MagicMock()
    resp.isError.return_value = False
    resp.bits = bits
    return resp


def _mock_register_response(registers: list[int]):
    """Create a mock register read response."""
    resp = MagicMock()
    resp.isError.return_value = False
    resp.registers = registers
    return resp


def _mock_error_response():
    """Create a mock error response."""
    resp = MagicMock()
    resp.isError.return_value = True
    return resp


# Normal coils: conveyor ON, sensors OFF, e-stop safe (coil8=False)
NORMAL_COILS = [True] + [False] * 17  # 18 coils, only coil 0 is True

# Normal registers: item_count=42, speed=60, current=35(/10=3.5),
#                   temp=251(/10=25.1), pressure=100, error=0
NORMAL_REGS = [42, 60, 35, 251, 100, 0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestModbusTagSource:
    """Tests for ModbusTagSource with mocked pymodbus."""

    @patch("net.drivers.modbus_tag_source.ModbusTagSource.connect", return_value=True)
    def test_tick_returns_tag_snapshot(self, mock_connect):
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        source._client = MagicMock()
        source._client.is_socket_open.return_value = True
        source._client.read_coils.return_value = _mock_coil_response(NORMAL_COILS)
        source._client.read_holding_registers.return_value = _mock_register_response(NORMAL_REGS)

        snap = source.tick()

        assert isinstance(snap, TagSnapshot)
        assert snap.node_id == "plc-192.168.1.100"
        assert snap.conveyor_running is True
        assert snap.motor_running is True
        assert snap.motor_speed == 60
        assert snap.error_code == 0
        assert snap.error_message == "No error"
        # New I/O fields
        assert len(snap.coils) == 18
        assert snap.coils[0] == 1  # conveyor ON
        assert snap.coils[1] == 0
        assert isinstance(snap.io, dict)
        assert snap.io["conveyor"] == 1
        assert snap.io["sensor_start"] == 0
        assert snap.e_stop_ok is False  # coils[8]=False, coils[9]=False

    @patch("net.drivers.modbus_tag_source.ModbusTagSource.connect", return_value=True)
    def test_register_scaling(self, mock_connect):
        """Verify /10 scaling on motor_current and temperature."""
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        source._client = MagicMock()
        source._client.is_socket_open.return_value = True
        source._client.read_coils.return_value = _mock_coil_response(NORMAL_COILS)
        # current=35 -> 3.5A, temp=251 -> 25.1C
        source._client.read_holding_registers.return_value = _mock_register_response(NORMAL_REGS)

        snap = source.tick()

        assert snap.motor_current == 3.5
        assert snap.temperature == 25.1
        assert snap.pressure == 100

    @patch("net.drivers.modbus_tag_source.ModbusTagSource.connect", return_value=True)
    def test_estop_dual_contact_validation(self, mock_connect):
        """E-stop: coil[8]=True AND coil[9]=False -> fault_alarm=True."""
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        source._client = MagicMock()
        source._client.is_socket_open.return_value = True

        # Set coil 8 (NO) = True, coil 9 (NC) = False -> E-stop active
        coils = [False] * 18
        coils[8] = True   # NO contact energised
        coils[9] = False   # NC contact de-energised

        source._client.read_coils.return_value = _mock_coil_response(coils)
        source._client.read_holding_registers.return_value = _mock_register_response(NORMAL_REGS)

        snap = source.tick()

        assert snap.fault_alarm is True
        assert snap.e_stop is True
        assert snap.e_stop_ok is False

    @patch("net.drivers.modbus_tag_source.ModbusTagSource.connect", return_value=True)
    def test_estop_safe_state(self, mock_connect):
        """Normal state: coil[8]=False, coil[9]=True -> no fault."""
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        source._client = MagicMock()
        source._client.is_socket_open.return_value = True

        coils = [True] + [False] * 17
        coils[8] = False   # NO not energised
        coils[9] = True    # NC energised (normal)

        source._client.read_coils.return_value = _mock_coil_response(coils)
        source._client.read_holding_registers.return_value = _mock_register_response(NORMAL_REGS)

        snap = source.tick()

        assert snap.fault_alarm is False
        assert snap.e_stop is False
        assert snap.e_stop_ok is True

    @patch("net.drivers.modbus_tag_source.ModbusTagSource.connect", return_value=True)
    def test_coil_read_error_returns_comms_fault(self, mock_connect):
        """Coil read error -> error_code=5 comms fault snapshot."""
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        source._client = MagicMock()
        source._client.is_socket_open.return_value = True
        source._client.read_coils.return_value = _mock_error_response()

        snap = source.tick()

        assert snap.error_code == 5
        assert "Communication loss" in snap.error_message
        assert snap.fault_alarm is True

    @patch("net.drivers.modbus_tag_source.ModbusTagSource.connect", return_value=True)
    def test_register_read_error_returns_comms_fault(self, mock_connect):
        """Register read error -> error_code=5 comms fault snapshot."""
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        source._client = MagicMock()
        source._client.is_socket_open.return_value = True
        source._client.read_coils.return_value = _mock_coil_response(NORMAL_COILS)
        source._client.read_holding_registers.return_value = _mock_error_response()

        snap = source.tick()

        assert snap.error_code == 5
        assert "Communication loss" in snap.error_message

    def test_connection_failed_returns_comms_fault(self):
        """If connect() fails, tick() returns comms fault snapshot."""
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        # _client is None, connected returns False
        # Patch connect to return False
        with patch.object(source, "connect", return_value=False):
            snap = source.tick()

        assert snap.error_code == 5
        assert snap.conveyor_running is False

    @patch("net.drivers.modbus_tag_source.ModbusTagSource.connect", return_value=True)
    def test_sensor_mapping(self, mock_connect):
        """Coils 2,3 map to sensor_1 (SensorStart) and sensor_2 (SensorEnd)."""
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        source._client = MagicMock()
        source._client.is_socket_open.return_value = True

        coils = [True] + [False] * 17
        coils[2] = True   # SensorStart active
        coils[3] = True   # SensorEnd active

        source._client.read_coils.return_value = _mock_coil_response(coils)
        source._client.read_holding_registers.return_value = _mock_register_response(NORMAL_REGS)

        snap = source.tick()

        assert snap.sensor_1 is True
        assert snap.sensor_2 is True

    @patch("net.drivers.modbus_tag_source.ModbusTagSource.connect", return_value=True)
    def test_to_dict_roundtrip(self, mock_connect):
        """TagSnapshot.to_dict() produces a dict suitable for API responses."""
        from net.drivers.modbus_tag_source import ModbusTagSource

        source = ModbusTagSource("192.168.1.100", 502)
        source._client = MagicMock()
        source._client.is_socket_open.return_value = True
        source._client.read_coils.return_value = _mock_coil_response(NORMAL_COILS)
        source._client.read_holding_registers.return_value = _mock_register_response(NORMAL_REGS)

        snap = source.tick()
        d = snap.to_dict()

        assert isinstance(d, dict)
        assert d["node_id"].startswith("plc-")
        assert "motor_speed" in d
        assert "timestamp" in d
        assert "coils" in d
        assert len(d["coils"]) == 18
        assert "io" in d
        assert "conveyor" in d["io"]
        assert "e_stop_ok" in d
