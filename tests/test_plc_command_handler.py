"""Tests for PLCCommandHandler — detects PLC command changes."""
from __future__ import annotations

from unittest.mock import MagicMock

from net.services.plc_command_handler import PLCCommandHandler


def _make_handler(initial_cmds=None):
    """Create a PLCCommandHandler with mocked dependencies."""
    compactcom = MagicMock()
    publisher = MagicMock()

    if initial_cmds is None:
        initial_cmds = {"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0}
    compactcom.read_commands.return_value = initial_cmds

    handler = PLCCommandHandler(compactcom=compactcom, publisher=publisher)
    return handler, compactcom


def test_run_command_detected():
    """Detect cmd_run change from 0 to 1."""
    handler, cc = _make_handler()

    # Simulate PLC writing cmd_run=1
    cmds = {"cmd_run": 1, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0}
    handler._detect_changes(cmds)

    assert handler.last_command is not None
    assert handler.last_command["type"] == "cmd_run"
    assert handler.last_command["value"] == 1
    assert handler.last_command["decoded"] == "RUN"


def test_stop_command_detected():
    """Detect cmd_run change from 1 to 0."""
    handler, cc = _make_handler()

    # First set to RUN
    handler._detect_changes({"cmd_run": 1, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0})
    # Then STOP
    handler._detect_changes({"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0})

    assert handler.last_command["type"] == "cmd_run"
    assert handler.last_command["decoded"] == "STOP"


def test_fault_reset_rising_edge_only():
    """Fault reset fires once on 0->1, not on steady 1."""
    handler, cc = _make_handler()

    # Rising edge: 0 -> 1
    handler._detect_changes({"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 1})
    assert len(handler.history) == 1
    assert handler.history[0]["type"] == "cmd_reset_fault"

    # Steady 1 -> 1 (no new event)
    handler._detect_changes({"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 1})
    # Still just 1 fault reset event
    fault_events = [e for e in handler.history if e["type"] == "cmd_reset_fault"]
    assert len(fault_events) == 1


def test_mode_change_logged():
    """Detect mode change and decode name."""
    handler, cc = _make_handler()

    handler._detect_changes({"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 1, "cmd_reset_fault": 0})
    assert handler.last_command["type"] == "cmd_mode"
    assert handler.last_command["decoded"] == "auto"

    handler._detect_changes({"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 2, "cmd_reset_fault": 0})
    assert handler.last_command["decoded"] == "maintenance"


def test_last_command_has_timestamp():
    """Verify last_command includes an ISO timestamp."""
    handler, cc = _make_handler()
    handler._detect_changes({"cmd_run": 1, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0})

    assert "timestamp" in handler.last_command
    assert "T" in handler.last_command["timestamp"]  # ISO format has T separator


def test_no_action_when_no_change():
    """No events recorded when commands don't change."""
    handler, cc = _make_handler()

    # Same as initial state — no change
    handler._detect_changes({"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0})
    assert handler.last_command is None
    assert len(handler.history) == 0


def test_speed_change_recorded():
    """Speed change is recorded with decoded percentage."""
    handler, cc = _make_handler()
    handler._detect_changes({"cmd_run": 0, "cmd_speed_pct": 600, "cmd_mode": 0, "cmd_reset_fault": 0})

    assert handler.last_command["type"] == "cmd_speed_pct"
    assert handler.last_command["value"] == 600
    assert "60.0%" in handler.last_command["decoded"]


def test_current_state_decoded():
    """current_state returns decoded values."""
    handler, cc = _make_handler()
    handler._detect_changes({"cmd_run": 1, "cmd_speed_pct": 450, "cmd_mode": 2, "cmd_reset_fault": 0})

    state = handler.current_state
    assert state["cmd_run"] == 1
    assert state["cmd_speed_pct"] == 45.0
    assert state["cmd_mode"] == "maintenance"


def test_history_order_newest_first():
    """History is ordered newest first."""
    handler, cc = _make_handler()
    handler._detect_changes({"cmd_run": 1, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0})
    handler._detect_changes({"cmd_run": 1, "cmd_speed_pct": 0, "cmd_mode": 1, "cmd_reset_fault": 0})

    hist = handler.history
    assert len(hist) == 2
    assert hist[0]["type"] == "cmd_mode"  # newest
    assert hist[1]["type"] == "cmd_run"   # oldest
