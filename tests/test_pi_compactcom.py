"""Tests for PiCompactCom — Modbus TCP server driver."""
from __future__ import annotations

import pytest

from net.drivers.pi_compactcom import PiCompactCom


def test_update_published_stores_values():
    """Write 10 values, read them back via read_published()."""
    cc = PiCompactCom(port=15024)
    # Manually init the context without starting the server
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusServerContext,
        ModbusSlaveContext,
    )
    store = ModbusSlaveContext(
        hr=ModbusSequentialDataBlock(0, [0] * 200),
    )
    cc._context = ModbusServerContext(slaves=store, single=True)

    values = [305, 500, 2, 32768, 3000, 45, 0, 1, 85, 42]
    cc.update_published(values)
    result = cc.read_published()
    assert result == values


def test_update_published_wrong_length_raises():
    """ValueError on wrong count."""
    cc = PiCompactCom(port=15024)
    with pytest.raises(ValueError, match="Expected 10"):
        cc.update_published([1, 2, 3])


def test_read_commands_default_zero():
    """All zeros before any PLC write."""
    cc = PiCompactCom(port=15024)
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusServerContext,
        ModbusSlaveContext,
    )
    store = ModbusSlaveContext(
        hr=ModbusSequentialDataBlock(0, [0] * 200),
    )
    cc._context = ModbusServerContext(slaves=store, single=True)

    cmds = cc.read_commands()
    assert cmds == {"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0}


def test_read_commands_after_plc_write():
    """Simulate PLC write to registers 100-103, verify dict."""
    cc = PiCompactCom(port=15024)
    from pymodbus.datastore import (
        ModbusSequentialDataBlock,
        ModbusServerContext,
        ModbusSlaveContext,
    )
    store = ModbusSlaveContext(
        hr=ModbusSequentialDataBlock(0, [0] * 200),
    )
    cc._context = ModbusServerContext(slaves=store, single=True)

    # Simulate PLC writing to command registers
    cc._context[0].setValues(3, 100, [1, 500, 2, 1])

    cmds = cc.read_commands()
    assert cmds["cmd_run"] == 1
    assert cmds["cmd_speed_pct"] == 500
    assert cmds["cmd_mode"] == 2
    assert cmds["cmd_reset_fault"] == 1


def test_is_running_false_before_start():
    """is_running is False when server hasn't been started."""
    cc = PiCompactCom(port=15024)
    assert cc.is_running is False


def test_read_published_no_context():
    """read_published returns zeros when context not initialized."""
    cc = PiCompactCom(port=15024)
    assert cc.read_published() == [0] * 10


def test_read_commands_no_context():
    """read_commands returns zero dict when context not initialized."""
    cc = PiCompactCom(port=15024)
    cmds = cc.read_commands()
    assert cmds == {"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0}
