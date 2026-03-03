"""Contract enforcement — sim mode is permanently removed.

These tests verify that:
1. The net.sim module does not exist
2. /api/status has no "mode" field
3. No PLC_HOST -> poller.latest is None (not fake data)
4. No VFD_HOST -> vfd_connected: false
5. source_flags register 20 = 0 when nothing connected
6. source_flags register 20 = 1 when only PLC connected
"""
import os
import tempfile

os.environ.pop("PLC_HOST", None)
os.environ.pop("VFD_HOST", None)
os.environ["FACTORYLM_NET_DB"] = os.path.join(tempfile.mkdtemp(), "nosim_test.db")

from unittest.mock import MagicMock

from net.api.main import _init_db, app
_init_db()

from fastapi.testclient import TestClient
client = TestClient(app)


def test_sim_module_does_not_exist():
    """import net.sim should raise ImportError."""
    import importlib
    try:
        importlib.import_module("net.sim")
        assert False, "net.sim should not exist"
    except ImportError:
        pass


def test_api_status_has_no_mode_field():
    """GET /api/status has no 'mode' key."""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" not in data


def test_plc_offline_returns_null_not_fake_values():
    """No PLC_HOST -> poller.latest is None."""
    from net.services.poller import Poller
    p = Poller(db_path=os.path.join(tempfile.mkdtemp(), "nosim_poller.db"))
    # Don't configure, don't set PLC_HOST
    assert p.latest is None


def test_vfd_offline_returns_false():
    """No VFD_HOST -> vfd_connected: false in status."""
    resp = client.get("/api/status")
    data = resp.json()
    assert data["vfd_connected"] is False


def test_source_flags_register_20_all_offline():
    """source_flags = 0 when nothing connected."""
    from net.services.publisher import Publisher
    poller = MagicMock()
    poller.latest = None
    compactcom = MagicMock()
    compactcom.read_commands.return_value = {
        "cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0,
    }
    pub = Publisher(compactcom=compactcom, poller=poller)
    values = pub._aggregate()
    assert values[20] == 0


def test_source_flags_register_20_plc_only():
    """source_flags = 1 when only PLC connected (bit0)."""
    from net.services.publisher import Publisher
    poller = MagicMock()
    poller.latest = {
        "motor_running": True,
        "motor_speed": 60,
        "motor_current": 3.0,
        "conveyor_running": True,
        "temperature": 25.0,
        "pressure": 100,
        "sensor_1": False,
        "sensor_2": False,
        "e_stop": False,
        "fault_alarm": False,
        "error_code": 0,
    }
    compactcom = MagicMock()
    compactcom.read_commands.return_value = {
        "cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0,
    }
    pub = Publisher(compactcom=compactcom, poller=poller)
    values = pub._aggregate()
    assert values[20] == 1
