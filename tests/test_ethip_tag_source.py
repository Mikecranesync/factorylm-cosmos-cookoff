"""Tests for EtherNetIPTagSource — mocked pycomm3, no real PLC needed."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from net.models.tags import TagSnapshot


# ---------------------------------------------------------------------------
# Helpers — mock pycomm3.Tag result objects
# ---------------------------------------------------------------------------

def _make_tag_result(tag: str, value, error=None):
    """Create a mock pycomm3 Tag result."""
    r = MagicMock()
    r.tag = tag
    r.value = value
    r.error = error
    return r


def _make_tag_list_entry(tag_name: str):
    """Create a mock pycomm3 tag list entry (dict-like)."""
    return {"tag_name": tag_name}


# All PLC tags that the driver might try to read
ALL_PLC_TAGS = [
    "motor_running", "motor_speed", "motor_current", "temperature",
    "pressure", "conveyor_running", "conveyor_speed", "sensor_1_active",
    "sensor_2_active", "e_stop_active", "fault_alarm", "error_code",
    "Emitter", "RunCommand",
    "_IO_EM_DI_00", "_IO_EM_DI_01", "_IO_EM_DI_02", "_IO_EM_DI_03",
    "_IO_EM_DI_04", "_IO_EM_DO_00", "_IO_EM_DO_01", "_IO_EM_DO_03",
]

# Normal tag values: conveyor running, 60% speed, 3.5A, 25.1C, no fault
NORMAL_TAG_VALUES = {
    "motor_running": True,
    "motor_speed": 60,
    "motor_current": 35,       # /10 -> 3.5
    "temperature": 251,        # /10 -> 25.1
    "pressure": 100,
    "conveyor_running": True,
    "conveyor_speed": 60,
    "sensor_1_active": False,
    "sensor_2_active": False,
    "e_stop_active": False,
    "fault_alarm": False,
    "error_code": 0,
    "Emitter": False,
    "RunCommand": False,
    "_IO_EM_DI_00": False,
    "_IO_EM_DI_01": False,     # E-stop NO
    "_IO_EM_DI_02": True,      # E-stop NC (safe)
    "_IO_EM_DI_03": False,
    "_IO_EM_DI_04": False,
    "_IO_EM_DO_00": False,
    "_IO_EM_DO_01": False,
    "_IO_EM_DO_03": False,
}


def _mock_bulk_read(tag_values: dict):
    """Return a list of mock Tag results matching the given values."""
    return [_make_tag_result(t, v) for t, v in tag_values.items()]


def _make_source_with_mock_plc(tag_values: dict | None = None):
    """Create an EtherNetIPTagSource with a mocked pycomm3 LogixDriver."""
    from net.drivers.ethip_tag_source import EtherNetIPTagSource

    source = EtherNetIPTagSource("169.254.20.53")
    mock_plc = MagicMock()
    source._plc = mock_plc
    source._tag_names = list(ALL_PLC_TAGS)

    if tag_values is not None:
        mock_plc.read.return_value = _mock_bulk_read(tag_values)

    return source


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEtherNetIPTagSource:

    def test_tick_returns_tag_snapshot(self):
        source = _make_source_with_mock_plc(NORMAL_TAG_VALUES)
        snap = source.tick()

        assert isinstance(snap, TagSnapshot)
        assert snap.node_id == "plc-169.254.20.53"
        assert snap.conveyor_running is True
        assert snap.motor_running is True
        assert snap.motor_speed == 60
        assert snap.error_code == 0
        assert snap.error_message == "No error"

    def test_register_scaling(self):
        """Verify /10 scaling on motor_current and temperature."""
        source = _make_source_with_mock_plc(NORMAL_TAG_VALUES)
        snap = source.tick()

        assert snap.motor_current == 3.5   # 35 / 10
        assert snap.temperature == 25.1    # 251 / 10
        assert snap.pressure == 100        # direct

    def test_coils_array_reconstruction(self):
        """18-element coils[] should be reconstructed from individual tags."""
        source = _make_source_with_mock_plc(NORMAL_TAG_VALUES)
        snap = source.tick()

        assert len(snap.coils) == 18
        assert snap.coils[0] == 1   # conveyor_running = True
        assert snap.coils[1] == 0   # Emitter = False
        assert snap.coils[9] == 1   # _IO_EM_DI_02 = True (E-stop NC safe)

    def test_io_dict_reconstruction(self):
        """io{} dict should be built from named tags."""
        source = _make_source_with_mock_plc(NORMAL_TAG_VALUES)
        snap = source.tick()

        assert isinstance(snap.io, dict)
        assert snap.io["conveyor"] == 1
        assert snap.io["emitter"] == 0
        assert snap.io["di_estop_nc"] == 1  # safe state
        assert snap.io["sensor_start"] == 0

    def test_estop_safe_state(self):
        """Normal: DI_01=False, DI_02=True -> e_stop_ok=True, fault_alarm=False."""
        source = _make_source_with_mock_plc(NORMAL_TAG_VALUES)
        snap = source.tick()

        assert snap.e_stop_ok is True
        assert snap.fault_alarm is False
        assert snap.e_stop is False

    def test_estop_active(self):
        """E-stop: DI_01=True, DI_02=False -> e_stop_ok=False."""
        vals = dict(NORMAL_TAG_VALUES)
        vals["_IO_EM_DI_01"] = True   # NO energised
        vals["_IO_EM_DI_02"] = False  # NC de-energised
        vals["fault_alarm"] = True
        vals["e_stop_active"] = True

        source = _make_source_with_mock_plc(vals)
        snap = source.tick()

        assert snap.e_stop_ok is False
        assert snap.fault_alarm is True
        assert snap.e_stop is True

    def test_connection_failed_returns_comms_fault(self):
        """If connect() fails, tick() returns comms fault snapshot."""
        from net.drivers.ethip_tag_source import EtherNetIPTagSource

        source = EtherNetIPTagSource("169.254.20.53")
        # _plc is None, connected returns False
        with patch.object(source, "connect", return_value=False):
            snap = source.tick()

        assert snap.error_code == 5
        assert "Communication loss" in snap.error_message
        assert snap.conveyor_running is False
        assert snap.fault_alarm is True

    def test_read_exception_returns_comms_fault(self):
        """If read() raises, tick() returns comms fault and closes connection."""
        source = _make_source_with_mock_plc()
        source._plc.read.side_effect = ConnectionError("socket closed")

        snap = source.tick()

        assert snap.error_code == 5
        assert "socket closed" in snap.error_message
        assert source._plc is None  # connection should be cleaned up

    def test_missing_tags_default_to_zero(self):
        """Tags not found on PLC should default to safe zero values."""
        from net.drivers.ethip_tag_source import EtherNetIPTagSource

        source = EtherNetIPTagSource("169.254.20.53")
        source._plc = MagicMock()
        source._tag_names = ["motor_running", "motor_speed"]  # sparse tag list

        # Only return results for the two tags that exist
        source._plc.read.return_value = [
            _make_tag_result("motor_running", True),
            _make_tag_result("motor_speed", 42),
        ]

        snap = source.tick()

        assert snap.motor_running is True
        assert snap.motor_speed == 42
        assert snap.motor_current == 0.0  # missing -> default
        assert snap.temperature == 0.0    # missing -> default
        assert snap.error_code == 0       # missing -> default

    def test_to_dict_roundtrip(self):
        """TagSnapshot.to_dict() produces a dict with all expected keys."""
        source = _make_source_with_mock_plc(NORMAL_TAG_VALUES)
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

    def test_conveyor_speed_fallback(self):
        """If conveyor_speed=0 but motor_speed>0, conveyor_speed copies motor_speed."""
        vals = dict(NORMAL_TAG_VALUES)
        vals["conveyor_speed"] = 0
        vals["motor_speed"] = 45

        source = _make_source_with_mock_plc(vals)
        snap = source.tick()

        assert snap.conveyor_speed == 45

    def test_tag_read_error_skips_tag(self):
        """A tag with an error should be skipped (defaults to zero)."""
        from net.drivers.ethip_tag_source import EtherNetIPTagSource

        source = EtherNetIPTagSource("169.254.20.53")
        source._plc = MagicMock()
        source._tag_names = list(ALL_PLC_TAGS)

        results = _mock_bulk_read(NORMAL_TAG_VALUES)
        # Simulate an error on motor_current
        for r in results:
            if r.tag == "motor_current":
                r.error = "Tag not found"
                break

        source._plc.read.return_value = results
        snap = source.tick()

        # motor_current had an error -> defaults to 0.0
        assert snap.motor_current == 0.0
        # everything else still works
        assert snap.motor_speed == 60


class TestPollerEthIPFallback:
    """Test Poller._try_ethip and the ETHIP_HOST path."""

    def test_try_ethip_success(self):
        import os
        from net.services.poller import Poller

        mock_source = MagicMock()
        mock_source.connect.return_value = True

        with patch("net.drivers.ethip_tag_source.EtherNetIPTagSource", return_value=mock_source):
            result = Poller._try_ethip("169.254.20.53")

        assert result is mock_source
        mock_source.connect.assert_called_once()

    def test_try_ethip_failure(self):
        from net.services.poller import Poller

        mock_source = MagicMock()
        mock_source.connect.return_value = False

        with patch("net.drivers.ethip_tag_source.EtherNetIPTagSource", return_value=mock_source):
            result = Poller._try_ethip("169.254.20.53")

        assert result is None

    def test_ethip_host_env_var(self):
        """ETHIP_HOST env var should force EtherNet/IP directly."""
        import os
        import tempfile
        from net.services.poller import Poller

        db = os.path.join(tempfile.mkdtemp(), "p.db")
        p = Poller(db_path=db)

        mock_source = MagicMock()
        mock_source.connect.return_value = True
        mock_source.connected = True

        with patch.dict(os.environ, {"ETHIP_HOST": "169.254.20.53"}, clear=False):
            # Remove PLC_HOST to ensure ETHIP_HOST takes priority
            os.environ.pop("PLC_HOST", None)
            with patch("net.drivers.ethip_tag_source.EtherNetIPTagSource", return_value=mock_source):
                p._init_source()

        assert p._tag_source is mock_source
