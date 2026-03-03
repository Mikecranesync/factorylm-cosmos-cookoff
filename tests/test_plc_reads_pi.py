"""Integration tests — verify PLC can read/write Pi CompactCom via Modbus TCP.

These tests start a real PiCompactCom server on a high test port and use
a pymodbus ModbusTcpClient to simulate the Micro820 PLC MSG instruction.
No actual PLC hardware needed.
"""
from __future__ import annotations

import time

import pytest
from pymodbus.client import ModbusTcpClient

from net.drivers.pi_compactcom import PiCompactCom

TEST_PORT = 15030  # high port to avoid conflicts


@pytest.fixture(scope="module")
def compactcom():
    """Start a real PiCompactCom server for the test module."""
    cc = PiCompactCom(port=TEST_PORT, host="127.0.0.1")
    cc.start()
    # Give the async server time to bind
    time.sleep(1.0)
    yield cc
    cc.stop()


@pytest.fixture()
def plc_client(compactcom):
    """Create a Modbus TCP client simulating the PLC, with retry."""
    client = ModbusTcpClient("127.0.0.1", port=TEST_PORT, timeout=3)
    # Retry connection a few times (server may still be binding)
    for attempt in range(5):
        if client.connect():
            break
        time.sleep(0.5)
    else:
        pytest.fail("Test client failed to connect to PiCompactCom after retries")
    yield client
    client.close()


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_pi_server_accepts_plc_connection(compactcom):
    """Start PiCompactCom, connect with ModbusTcpClient, verify success."""
    assert compactcom.is_running
    client = ModbusTcpClient("127.0.0.1", port=TEST_PORT, timeout=3)
    for attempt in range(5):
        if client.connect():
            break
        time.sleep(0.5)
    else:
        pytest.fail("PLC client could not connect to Pi CompactCom server")
    client.close()


def test_pi_serves_function_code_3(plc_client, compactcom):
    """FC3 (Read Holding Registers) returns 10 registers — what Micro820 MSG uses."""
    compactcom.update_published([100, 200, 2, 32768, 5000, 45, 0, 3, 80, 42])
    time.sleep(0.05)

    result = plc_client.read_holding_registers(0, count=10)
    assert not result.isError(), f"FC3 read failed: {result}"
    assert len(result.registers) == 10
    assert result.registers[0] == 100
    assert result.registers[9] == 42


def test_pi_serves_function_code_16(plc_client, compactcom):
    """FC16 (Write Multiple Registers) stores values — Micro820 MSG write."""
    result = plc_client.write_registers(100, [1, 600, 1, 0])
    assert not result.isError(), f"FC16 write failed: {result}"

    cmds = compactcom.read_commands()
    assert cmds["cmd_run"] == 1
    assert cmds["cmd_speed_pct"] == 600
    assert cmds["cmd_mode"] == 1

    # Clean up
    plc_client.write_registers(100, [0, 0, 0, 0])


def test_plc_read_belt_rpm_scaling(plc_client, compactcom):
    """belt_rpm=47.5 -> register 0 = 475 (x10 scaling). Roundtrip decode."""
    compactcom.update_published([475, 0, 0, 32768, 0, 0, 0, 0, 0, 0])
    time.sleep(0.05)

    result = plc_client.read_holding_registers(0, count=1)
    assert not result.isError()
    raw = result.registers[0]
    assert raw == 475
    assert raw / 10.0 == 47.5


def test_plc_read_belt_status_enum(plc_client, compactcom):
    """Verify belt status enum values in register 2."""
    # CALIBRATING=0, STOPPED=1, NORMAL=2, SLOW=3, MISTRACK=4
    for enum_val in range(5):
        compactcom.update_published([0, 0, enum_val, 32768, 0, 0, 0, 0, 0, 0])
        time.sleep(0.05)
        result = plc_client.read_holding_registers(2, count=1)
        assert not result.isError()
        assert result.registers[0] == enum_val


def test_plc_read_heartbeat_liveness(plc_client, compactcom):
    """Read register 9 three times — value must increment each time."""
    values = []
    for i in range(3):
        compactcom.update_published([0, 0, 0, 32768, 0, 0, 0, 0, 0, i + 1])
        time.sleep(0.05)
        result = plc_client.read_holding_registers(9, count=1)
        assert not result.isError()
        values.append(result.registers[0])

    assert values[0] < values[1] < values[2], f"Heartbeat not incrementing: {values}"


def test_plc_write_cmd_run(plc_client, compactcom):
    """Write 1 to register 100 (cmd_run), read back via read_commands()."""
    plc_client.write_registers(100, [1, 0, 0, 0])
    time.sleep(0.05)
    cmds = compactcom.read_commands()
    assert cmds["cmd_run"] == 1

    plc_client.write_registers(100, [0, 0, 0, 0])


def test_plc_write_cmd_speed(plc_client, compactcom):
    """Write 600 to register 101 (cmd_speed_pct x10 = 60.0%)."""
    plc_client.write_registers(100, [0, 600, 0, 0])
    time.sleep(0.05)
    cmds = compactcom.read_commands()
    assert cmds["cmd_speed_pct"] == 600
    assert cmds["cmd_speed_pct"] / 10.0 == 60.0

    plc_client.write_registers(100, [0, 0, 0, 0])


def test_plc_write_cmd_reset_fault(plc_client, compactcom):
    """Write 1 to register 103, verify latch, write 0, verify clear."""
    plc_client.write_registers(100, [0, 0, 0, 1])
    time.sleep(0.05)
    cmds = compactcom.read_commands()
    assert cmds["cmd_reset_fault"] == 1

    plc_client.write_registers(100, [0, 0, 0, 0])
    time.sleep(0.05)
    cmds = compactcom.read_commands()
    assert cmds["cmd_reset_fault"] == 0


def test_signed_offset_encoding(plc_client, compactcom):
    """belt_offset_px = -50 -> register 3 = 32718. Roundtrip decode."""
    offset = -50
    encoded = offset + 32768  # 32718
    compactcom.update_published([0, 0, 0, encoded, 0, 0, 0, 0, 0, 0])
    time.sleep(0.05)

    result = plc_client.read_holding_registers(3, count=1)
    assert not result.isError()
    raw = result.registers[0]
    assert raw == 32718
    assert raw - 32768 == -50

    # Positive offset
    compactcom.update_published([0, 0, 0, 120 + 32768, 0, 0, 0, 0, 0, 0])
    time.sleep(0.05)
    result = plc_client.read_holding_registers(3, count=1)
    assert result.registers[0] - 32768 == 120
