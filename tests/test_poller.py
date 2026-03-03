"""Tests for the background Poller service — mocks, no sim mode."""

import os
import tempfile
import time
from unittest.mock import patch, MagicMock

from net.services.poller import Poller


def _make_poller():
    db = os.path.join(tempfile.mkdtemp(), "p.db")
    p = Poller(db_path=db)
    return p


def test_poller_init_creates_tables():
    p = _make_poller()
    assert p.latest is None
    assert p.is_running is False
    assert p.plc_connected is False


def test_poller_with_mocked_tag_source():
    """Mock ModbusTagSource so poller produces data without hardware."""
    p = _make_poller()

    mock_snap = MagicMock()
    mock_snap.to_dict.return_value = {
        "timestamp": "2025-01-01T00:00:00Z",
        "node_id": "plc-mock",
        "motor_running": True,
        "motor_speed": 60,
        "motor_current": 3.0,
        "temperature": 25.0,
        "pressure": 100,
        "conveyor_running": True,
        "conveyor_speed": 60,
        "sensor_1": False,
        "sensor_2": False,
        "fault_alarm": False,
        "e_stop": False,
        "error_code": 0,
        "error_message": "No error",
        "coils": [1] + [0] * 17,
        "io": {
            "conveyor": 1, "emitter": 0, "sensor_start": 0,
            "sensor_end": 0, "run_command": 0, "di_center": 0,
            "di_estop_no": 0, "di_estop_nc": 0, "di_right": 0,
            "di_green_btn": 0, "do_fwd": 0, "do_rev": 0, "do_aux": 0,
        },
        "e_stop_ok": False,
    }

    mock_source = MagicMock()
    mock_source.connected = True
    mock_source.connect.return_value = True
    mock_source.tick.return_value = mock_snap

    with patch.dict(os.environ, {"PLC_HOST": "192.168.1.100", "PLC_PORT": "502"}):
        with patch("net.drivers.modbus_tag_source.ModbusTagSource", return_value=mock_source):
            p.start()
            time.sleep(1)
            assert p.is_running
            assert p.latest is not None
            assert p.latest["motor_speed"] == 60
            p.stop()
            assert not p.is_running


def test_poller_no_plc_host_returns_none():
    """Without PLC_HOST, poller should idle — latest stays None."""
    p = _make_poller()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PLC_HOST", None)
        p.start()
        time.sleep(0.5)
        assert p.latest is None
        p.stop()


def test_poller_writes_history():
    import sqlite3
    p = _make_poller()
    # Manually inject data
    p._latest = {"timestamp": "2025-01-01T00:00:00Z", "motor_speed": 60}
    p._write_history(p._latest)
    conn = sqlite3.connect(p.db_path)
    rows = conn.execute("SELECT COUNT(*) FROM tag_history").fetchone()[0]
    conn.close()
    assert rows >= 1


def test_poller_save_plc_config():
    import sqlite3, json
    p = _make_poller()
    p.save_plc_config(
        plc_id="plc-test",
        ip="10.0.0.1",
        port=502,
        brand="TestBrand",
        template_name="micro820",
        tags_json=json.dumps({"coils": {}, "registers": {}}),
    )
    conn = sqlite3.connect(p.db_path)
    row = conn.execute("SELECT ip, brand FROM plc_configs WHERE plc_id = 'plc-test'").fetchone()
    conn.close()
    assert row[0] == "10.0.0.1"
    assert row[1] == "TestBrand"


def test_poller_gateway_config():
    p = _make_poller()
    p.save_gateway_config("gateway_id", "flm-test123")
    assert p.get_gateway_id() == "flm-test123"


def test_poller_tag_names():
    p = _make_poller()
    p.save_tag_name("plc-x", "HR100", "Motor Speed")
    names = p.get_tag_names("plc-x")
    assert names == {"HR100": "Motor Speed"}


def test_poller_double_start_is_safe():
    p = _make_poller()
    p.start()
    p.start()  # Should warn but not crash
    assert p.is_running
    p.stop()


def test_poller_stop_without_start():
    p = _make_poller()
    p.stop()  # Should not raise
