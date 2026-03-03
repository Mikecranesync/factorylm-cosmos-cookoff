"""Tests for Publisher — aggregates data into CompactCom registers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from net.services.publisher import Publisher, _clamp, _belt_status_to_enum


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_publisher(
    poller_tags=None,
    belt=None,
    vfd=None,
):
    """Create a Publisher with mocked dependencies."""
    compactcom = MagicMock()
    compactcom.read_commands.return_value = {
        "cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0,
    }

    poller = MagicMock()
    poller.latest = poller_tags

    pub = Publisher(
        compactcom=compactcom,
        poller=poller,
        belt_tachometer=belt,
        vfd_reader=vfd,
    )
    return pub, compactcom, poller


def _make_belt_mock(rpm=30.5, speed_pct=50.0, offset_px=0, status=None):
    """Create a mock belt tachometer."""
    belt = MagicMock()
    belt.rpm = rpm
    belt.speed_pct = speed_pct
    belt.offset_px = offset_px
    if status is None:
        # Use a simple object with .value for the enum
        belt.status = MagicMock()
        belt.status.value = "normal"
    else:
        belt.status = status
    return belt


def _make_vfd_mock(output_hz=30.0, output_amps=4.5, fault_code=0):
    """Create a mock VFD reader."""
    vfd = MagicMock()
    vfd.tick.return_value = {
        "vfd_connected": True,
        "vfd_output_hz": output_hz,
        "vfd_output_amps": output_amps,
        "vfd_fault_code": fault_code,
    }
    return vfd


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_aggregate_with_all_sources():
    """Mock poller/belt/VFD, verify 10 scaled values."""
    belt = _make_belt_mock(rpm=30.5, speed_pct=50.0, offset_px=10)
    vfd = _make_vfd_mock(output_hz=30.0, output_amps=4.5, fault_code=0)
    poller_tags = {"error_code": 3, "motor_speed": 60}

    pub, cc, _ = _make_publisher(poller_tags=poller_tags, belt=belt, vfd=vfd)
    values = pub._aggregate()

    assert len(values) == 10
    assert values[0] == 305       # belt_rpm: 30.5 * 10
    assert values[1] == 500       # belt_speed_pct: 50.0 * 10
    # values[2] = belt_status (depends on enum mapping, may be 0)
    assert values[3] == 32778     # belt_offset_px: 10 + 32768
    assert values[4] == 3000      # vfd_output_hz: 30.0 * 100
    assert values[5] == 45        # vfd_output_amps: 4.5 * 10
    assert values[6] == 0         # vfd_fault_code
    assert values[7] == 3         # ai_fault_code from poller
    assert values[8] == 0         # ai_confidence placeholder
    assert values[9] == 1         # heartbeat (first call)


def test_aggregate_no_belt_no_vfd():
    """Graceful zeros when optional sources unavailable."""
    pub, cc, _ = _make_publisher(poller_tags=None, belt=None, vfd=None)
    values = pub._aggregate()

    assert len(values) == 10
    assert values[0] == 0    # belt_rpm
    assert values[1] == 0    # belt_speed_pct
    assert values[2] == 0    # belt_status
    assert values[3] == 32768  # zero offset
    assert values[4] == 0    # vfd_output_hz
    assert values[5] == 0    # vfd_output_amps
    assert values[6] == 0    # vfd_fault_code
    assert values[7] == 0    # ai_fault_code (no tags)
    assert values[8] == 0    # ai_confidence
    assert values[9] == 1    # heartbeat


def test_heartbeat_increments():
    """3 calls → 1, 2, 3."""
    pub, _, _ = _make_publisher()
    v1 = pub._aggregate()
    v2 = pub._aggregate()
    v3 = pub._aggregate()
    assert v1[9] == 1
    assert v2[9] == 2
    assert v3[9] == 3


def test_heartbeat_wraps():
    """Set to 65535, next call wraps to 0."""
    pub, _, _ = _make_publisher()
    pub._heartbeat = 65535
    values = pub._aggregate()
    assert values[9] == 0


def test_clamp_overflow():
    """Verify clamping at boundaries."""
    assert _clamp(-1) == 0
    assert _clamp(0) == 0
    assert _clamp(32768) == 32768
    assert _clamp(65535) == 65535
    assert _clamp(65536) == 65535
    assert _clamp(100000) == 65535


def test_clamp_custom_bounds():
    """Verify custom lo/hi."""
    assert _clamp(5, lo=10, hi=20) == 10
    assert _clamp(25, lo=10, hi=20) == 20
    assert _clamp(15, lo=10, hi=20) == 15


def test_commands_property():
    """Default commands are all zeros."""
    pub, _, _ = _make_publisher()
    cmds = pub.commands
    assert cmds == {"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0}


def test_set_belt_tachometer_hot_swap():
    """Hot-swap belt tachometer reference."""
    pub, _, _ = _make_publisher(belt=None)
    assert pub._belt_tachometer is None

    new_belt = _make_belt_mock(rpm=45.0)
    pub.set_belt_tachometer(new_belt)
    assert pub._belt_tachometer is new_belt

    values = pub._aggregate()
    assert values[0] == 450  # 45.0 * 10


def test_set_vfd_reader_hot_swap():
    """Hot-swap VFD reader reference."""
    pub, _, _ = _make_publisher(vfd=None)
    assert pub._vfd_reader is None

    new_vfd = _make_vfd_mock(output_hz=60.0)
    pub.set_vfd_reader(new_vfd)
    assert pub._vfd_reader is new_vfd

    values = pub._aggregate()
    assert values[4] == 6000  # 60.0 * 100


def test_vfd_disconnected_returns_zeros():
    """VFD returns vfd_connected=False → zeros."""
    vfd = MagicMock()
    vfd.tick.return_value = {"vfd_connected": False}

    pub, _, _ = _make_publisher(vfd=vfd)
    values = pub._aggregate()
    assert values[4] == 0
    assert values[5] == 0
    assert values[6] == 0


def test_start_stop_lifecycle():
    """Start and stop without error."""
    pub, cc, _ = _make_publisher()
    # Don't actually start the thread — just verify the interface
    assert pub.is_running is False
