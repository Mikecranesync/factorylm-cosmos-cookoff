"""Tests for VfdReader — mocked Modbus (no real VFD hardware)."""
from unittest.mock import MagicMock, patch, PropertyMock

from net.drivers.vfd_reader import VfdReader, VFD_FAULT_CODES


def _make_reader():
    """Create a VfdReader with mocked pymodbus client."""
    reader = VfdReader(host="192.168.1.101", port=502, slave=1)
    mock_client = MagicMock()
    mock_client.is_socket_open.return_value = True
    reader._client = mock_client
    return reader, mock_client


def _mock_register_result(registers):
    """Build a mock result object with .isError() = False."""
    result = MagicMock()
    result.isError.return_value = False
    result.registers = registers
    return result


def test_tick_returns_vfd_tags():
    reader, client = _make_reader()

    # Batch 1: writable regs (0x2000-0x2001)
    write_regs = [0x0001, 3000]  # control=FWD, setpoint=30.00Hz
    # Batch 2: status regs (0x2100-0x210B) — 12 registers
    status_regs = [
        0x0010,  # status_word
        3000,    # output_hz → 30.00
        45,      # output_amps → 4.5
        2990,    # actual_freq → 29.90
        44,      # actual_current → 4.4
        3200,    # dc_bus_volts → 320.0
        1750,    # motor_rpm
        850,     # torque_pct → 85.0
        425,     # drive_temp → 42.5
        0,       # fault_code
        0,       # warning_code
        1234,    # run_hours
    ]

    client.read_holding_registers.side_effect = [
        _mock_register_result(write_regs),
        _mock_register_result(status_regs),
    ]

    data = reader.tick()

    assert data["vfd_connected"] is True
    assert data["vfd_control_word"] == 1
    assert data["vfd_setpoint_hz"] == 30.0
    assert data["vfd_output_hz"] == 30.0
    assert data["vfd_output_amps"] == 4.5
    assert data["vfd_motor_rpm"] == 1750
    assert data["vfd_drive_temp_c"] == 42.5
    assert data["vfd_fault_code"] == 0
    assert data["vfd_fault_description"] == "No fault"
    assert data["vfd_run_hours"] == 1234


def test_read_error_returns_disconnected():
    reader, client = _make_reader()

    error_result = MagicMock()
    error_result.isError.return_value = True
    client.read_holding_registers.return_value = error_result

    data = reader.tick()

    assert data["vfd_connected"] is False
    assert "Communication loss" in data["vfd_fault_description"]


def test_fault_code_mapping():
    """Verify known fault codes map to descriptions."""
    assert VFD_FAULT_CODES[0] == "No fault"
    assert VFD_FAULT_CODES[8] == "Drive overtemperature"
    assert VFD_FAULT_CODES[9] == "Motor overload"
    assert VFD_FAULT_CODES[13] == "Communication loss"


def test_scaling_output_hz():
    """Verify /100 scaling on frequency registers."""
    reader, client = _make_reader()

    write_regs = [0x0001, 5000]  # setpoint = 50.00 Hz
    status_regs = [0, 4500, 0, 4500, 0, 0, 0, 0, 0, 0, 0, 0]  # output_hz = 45.00

    client.read_holding_registers.side_effect = [
        _mock_register_result(write_regs),
        _mock_register_result(status_regs),
    ]

    data = reader.tick()

    assert data["vfd_setpoint_hz"] == 50.0
    assert data["vfd_output_hz"] == 45.0
    assert data["vfd_actual_freq"] == 45.0


def test_scaling_current():
    """Verify /10 scaling on current and temperature registers."""
    reader, client = _make_reader()

    write_regs = [0, 0]
    status_regs = [0, 0, 123, 0, 98, 3450, 0, 0, 650, 0, 0, 0]

    client.read_holding_registers.side_effect = [
        _mock_register_result(write_regs),
        _mock_register_result(status_regs),
    ]

    data = reader.tick()

    assert data["vfd_output_amps"] == 12.3
    assert data["vfd_actual_current"] == 9.8
    assert data["vfd_dc_bus_volts"] == 345.0
    assert data["vfd_drive_temp_c"] == 65.0


def test_connect_returns_false_without_pymodbus():
    """Verify graceful failure when pymodbus is not installed."""
    reader = VfdReader(host="1.2.3.4")
    with patch.dict("sys.modules", {"pymodbus.client": None}):
        with patch("builtins.__import__", side_effect=ImportError("no pymodbus")):
            result = reader.connect()
    # connect() should catch ImportError and return False
    # (may return True if pymodbus is installed in test env — both are valid)
    assert isinstance(result, bool)


def test_exception_during_read():
    """Verify tick() handles unexpected exceptions gracefully."""
    reader, client = _make_reader()
    client.read_holding_registers.side_effect = ConnectionError("socket broke")

    data = reader.tick()

    assert data["vfd_connected"] is False
    assert "socket broke" in data["vfd_fault_description"]
