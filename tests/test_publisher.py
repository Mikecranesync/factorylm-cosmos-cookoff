"""Tests for Publisher — aggregates data into 21 CompactCom registers."""
from __future__ import annotations

from unittest.mock import MagicMock

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
    belt = MagicMock()
    belt.rpm = rpm
    belt.speed_pct = speed_pct
    belt.offset_px = offset_px
    if status is None:
        belt.status = MagicMock()
        belt.status.value = "normal"
    else:
        belt.status = status
    return belt


def _make_vfd_mock(output_hz=30.0, output_amps=4.5, fault_code=0):
    vfd = MagicMock()
    vfd.tick.return_value = {
        "vfd_connected": True,
        "vfd_output_hz": output_hz,
        "vfd_output_amps": output_amps,
        "vfd_fault_code": fault_code,
    }
    return vfd


def _full_poller_tags():
    return {
        "motor_running": True,
        "motor_speed": 60,
        "motor_current": 3.5,
        "conveyor_running": True,
        "temperature": 25.0,
        "pressure": 100,
        "sensor_1": True,
        "sensor_2": False,
        "e_stop": False,
        "fault_alarm": False,
        "error_code": 0,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_aggregate_with_all_sources():
    """Mock poller/belt/VFD, verify 21 scaled values."""
    belt = _make_belt_mock(rpm=30.5, speed_pct=50.0, offset_px=10)
    vfd = _make_vfd_mock(output_hz=30.0, output_amps=4.5, fault_code=0)
    poller_tags = _full_poller_tags()
    poller_tags["error_code"] = 3

    pub, cc, _ = _make_publisher(poller_tags=poller_tags, belt=belt, vfd=vfd)
    values = pub._aggregate()

    assert len(values) == 21
    assert values[0] == 305       # belt_rpm: 30.5 * 10
    assert values[1] == 500       # belt_speed_pct: 50.0 * 10
    assert values[3] == 32778     # belt_offset_px: 10 + 32768
    assert values[4] == 3000      # vfd_output_hz: 30.0 * 100
    assert values[5] == 45        # vfd_output_amps: 4.5 * 10
    assert values[6] == 0         # vfd_fault_code
    assert values[7] == 1         # motor_running
    assert values[8] == 60        # motor_speed
    assert values[9] == 35        # motor_current: 3.5 * 10
    assert values[10] == 1        # conveyor_running
    assert values[11] == 250      # temperature: 25.0 * 10
    assert values[12] == 100      # pressure
    assert values[13] == 1        # sensor_1
    assert values[14] == 0        # sensor_2
    assert values[15] == 0        # e_stop
    assert values[16] == 0        # fault_alarm
    assert values[17] == 3        # error_code
    assert values[18] == 0        # ai_confidence
    assert values[19] == 1        # heartbeat (first call)
    # source_flags: plc=1, vfd=1, camera=1 -> 0b111 = 7
    assert values[20] == 7


def test_aggregate_no_belt_no_vfd():
    """Graceful zeros when optional sources unavailable."""
    pub, cc, _ = _make_publisher(poller_tags=None, belt=None, vfd=None)
    values = pub._aggregate()

    assert len(values) == 21
    assert values[0] == 0    # belt_rpm
    assert values[1] == 0    # belt_speed_pct
    assert values[2] == 0    # belt_status
    assert values[3] == 32768  # zero offset
    assert values[4] == 0    # vfd_output_hz
    assert values[5] == 0    # vfd_output_amps
    assert values[6] == 0    # vfd_fault_code
    assert values[7] == 0    # motor_running
    assert values[8] == 0    # motor_speed
    assert values[9] == 0    # motor_current
    assert values[10] == 0   # conveyor_running
    assert values[11] == 0   # temperature
    assert values[12] == 0   # pressure
    assert values[13] == 0   # sensor_1
    assert values[14] == 0   # sensor_2
    assert values[15] == 0   # e_stop
    assert values[16] == 0   # fault_alarm
    assert values[17] == 0   # error_code
    assert values[18] == 0   # ai_confidence
    assert values[19] == 1   # heartbeat
    assert values[20] == 0   # source_flags: nothing connected


def test_source_flags_plc_only():
    """With only poller data, source_flags bit0=1."""
    pub, _, _ = _make_publisher(poller_tags=_full_poller_tags(), belt=None, vfd=None)
    values = pub._aggregate()
    assert values[20] == 1  # only plc connected


def test_source_flags_vfd_only():
    """With only VFD, source_flags bit1=1."""
    vfd = _make_vfd_mock()
    pub, _, _ = _make_publisher(poller_tags=None, belt=None, vfd=vfd)
    values = pub._aggregate()
    assert values[20] == 2  # only vfd connected


def test_source_flags_camera_only():
    """With only camera, source_flags bit2=1."""
    belt = _make_belt_mock()
    pub, _, _ = _make_publisher(poller_tags=None, belt=belt, vfd=None)
    values = pub._aggregate()
    assert values[20] == 4  # only camera connected


def test_heartbeat_increments():
    """3 calls -> 1, 2, 3."""
    pub, _, _ = _make_publisher()
    v1 = pub._aggregate()
    v2 = pub._aggregate()
    v3 = pub._aggregate()
    assert v1[19] == 1
    assert v2[19] == 2
    assert v3[19] == 3


def test_heartbeat_wraps():
    """Set to 65535, next call wraps to 0."""
    pub, _, _ = _make_publisher()
    pub._heartbeat = 65535
    values = pub._aggregate()
    assert values[19] == 0


def test_clamp_overflow():
    assert _clamp(-1) == 0
    assert _clamp(0) == 0
    assert _clamp(32768) == 32768
    assert _clamp(65535) == 65535
    assert _clamp(65536) == 65535
    assert _clamp(100000) == 65535


def test_clamp_custom_bounds():
    assert _clamp(5, lo=10, hi=20) == 10
    assert _clamp(25, lo=10, hi=20) == 20
    assert _clamp(15, lo=10, hi=20) == 15


def test_commands_property():
    pub, _, _ = _make_publisher()
    cmds = pub.commands
    assert cmds == {"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0}


def test_set_belt_tachometer_hot_swap():
    pub, _, _ = _make_publisher(belt=None)
    assert pub._belt_tachometer is None

    new_belt = _make_belt_mock(rpm=45.0)
    pub.set_belt_tachometer(new_belt)
    assert pub._belt_tachometer is new_belt

    values = pub._aggregate()
    assert values[0] == 450  # 45.0 * 10


def test_set_vfd_reader_hot_swap():
    pub, _, _ = _make_publisher(vfd=None)
    assert pub._vfd_reader is None

    new_vfd = _make_vfd_mock(output_hz=60.0)
    pub.set_vfd_reader(new_vfd)
    assert pub._vfd_reader is new_vfd

    values = pub._aggregate()
    assert values[4] == 6000  # 60.0 * 100


def test_vfd_disconnected_returns_zeros():
    vfd = MagicMock()
    vfd.tick.return_value = {"vfd_connected": False}

    pub, _, _ = _make_publisher(vfd=vfd)
    values = pub._aggregate()
    assert values[4] == 0
    assert values[5] == 0
    assert values[6] == 0


def test_start_stop_lifecycle():
    pub, cc, _ = _make_publisher()
    assert pub.is_running is False
