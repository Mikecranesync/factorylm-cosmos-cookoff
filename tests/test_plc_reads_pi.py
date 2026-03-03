"""Integration tests — verify PLC can read/write Pi CompactCom via Modbus TCP.

These tests start a real PiCompactCom server on a high test port and use
a pymodbus ModbusTcpClient to simulate the Micro820 PLC MSG instruction.
No actual PLC hardware needed. Updated for 21-register map.
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
    time.sleep(1.0)
    yield cc
    cc.stop()


@pytest.fixture()
def plc_client(compactcom):
    """Create a Modbus TCP client simulating the PLC, with retry."""
    client = ModbusTcpClient("127.0.0.1", port=TEST_PORT, timeout=3)
    for attempt in range(5):
        if client.connect():
            break
        time.sleep(0.5)
    else:
        pytest.fail("Test client failed to connect to PiCompactCom after retries")
    yield client
    client.close()


def _make_21_values(overrides=None):
    """Build 21-element list with zeros, optionally overriding specific indices."""
    values = [0] * 21
    values[3] = 32768  # zero offset default
    if overrides:
        for idx, val in overrides.items():
            values[idx] = val
    return values


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

def test_pi_server_accepts_plc_connection(compactcom):
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
    """FC3 (Read Holding Registers) returns 21 registers."""
    values = [100, 200, 2, 32768, 5000, 45, 0, 1, 60, 30, 1, 250, 100, 1, 0, 0, 0, 0, 85, 42, 7]
    compactcom.update_published(values)
    time.sleep(0.05)

    result = plc_client.read_holding_registers(0, count=21)
    assert not result.isError(), f"FC3 read failed: {result}"
    assert len(result.registers) == 21
    assert result.registers[0] == 100
    assert result.registers[19] == 42   # heartbeat
    assert result.registers[20] == 7    # source_flags


def test_pi_serves_function_code_16(plc_client, compactcom):
    """FC16 (Write Multiple Registers) stores values."""
    result = plc_client.write_registers(100, [1, 600, 1, 0])
    assert not result.isError(), f"FC16 write failed: {result}"

    cmds = compactcom.read_commands()
    assert cmds["cmd_run"] == 1
    assert cmds["cmd_speed_pct"] == 600
    assert cmds["cmd_mode"] == 1

    plc_client.write_registers(100, [0, 0, 0, 0])


def test_plc_read_belt_rpm_scaling(plc_client, compactcom):
    """belt_rpm=47.5 -> register 0 = 475 (x10 scaling)."""
    values = _make_21_values({0: 475})
    compactcom.update_published(values)
    time.sleep(0.05)

    result = plc_client.read_holding_registers(0, count=1)
    assert not result.isError()
    raw = result.registers[0]
    assert raw == 475
    assert raw / 10.0 == 47.5


def test_plc_read_belt_status_enum(plc_client, compactcom):
    """Verify belt status enum values in register 2."""
    for enum_val in range(5):
        values = _make_21_values({2: enum_val})
        compactcom.update_published(values)
        time.sleep(0.05)
        result = plc_client.read_holding_registers(2, count=1)
        assert not result.isError()
        assert result.registers[0] == enum_val


def test_plc_read_heartbeat_liveness(plc_client, compactcom):
    """Read register 19 three times — value must increment each time."""
    readings = []
    for i in range(3):
        values = _make_21_values({19: i + 1})
        compactcom.update_published(values)
        time.sleep(0.05)
        result = plc_client.read_holding_registers(19, count=1)
        assert not result.isError()
        readings.append(result.registers[0])

    assert readings[0] < readings[1] < readings[2], f"Heartbeat not incrementing: {readings}"


def test_plc_write_cmd_run(plc_client, compactcom):
    plc_client.write_registers(100, [1, 0, 0, 0])
    time.sleep(0.05)
    cmds = compactcom.read_commands()
    assert cmds["cmd_run"] == 1
    plc_client.write_registers(100, [0, 0, 0, 0])


def test_plc_write_cmd_speed(plc_client, compactcom):
    plc_client.write_registers(100, [0, 600, 0, 0])
    time.sleep(0.05)
    cmds = compactcom.read_commands()
    assert cmds["cmd_speed_pct"] == 600
    plc_client.write_registers(100, [0, 0, 0, 0])


def test_plc_write_cmd_reset_fault(plc_client, compactcom):
    plc_client.write_registers(100, [0, 0, 0, 1])
    time.sleep(0.05)
    cmds = compactcom.read_commands()
    assert cmds["cmd_reset_fault"] == 1
    plc_client.write_registers(100, [0, 0, 0, 0])
    time.sleep(0.05)
    cmds = compactcom.read_commands()
    assert cmds["cmd_reset_fault"] == 0


def test_signed_offset_encoding(plc_client, compactcom):
    """belt_offset_px = -50 -> register 3 = 32718."""
    offset = -50
    encoded = offset + 32768
    values = _make_21_values({3: encoded})
    compactcom.update_published(values)
    time.sleep(0.05)

    result = plc_client.read_holding_registers(3, count=1)
    assert not result.isError()
    raw = result.registers[0]
    assert raw == 32718
    assert raw - 32768 == -50

    values2 = _make_21_values({3: 120 + 32768})
    compactcom.update_published(values2)
    time.sleep(0.05)
    result = plc_client.read_holding_registers(3, count=1)
    assert result.registers[0] - 32768 == 120


def test_plc_reads_source_flags(plc_client, compactcom):
    """Register 20 = source_flags bitmask."""
    values = _make_21_values({20: 5})  # plc + camera
    compactcom.update_published(values)
    time.sleep(0.05)

    result = plc_client.read_holding_registers(20, count=1)
    assert not result.isError()
    flags = result.registers[0]
    assert flags & 0x01  # plc
    assert not (flags & 0x02)  # no vfd
    assert flags & 0x04  # camera
