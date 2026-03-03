"""Test POST /api/cosmos/diagnose endpoint — mock poller data."""
import os
import tempfile

os.environ["FACTORYLM_NET_DB"] = os.path.join(tempfile.mkdtemp(), "factorylm_test_cosmos.db")

from net.api.main import _init_db, app, poller

_init_db()

from fastapi.testclient import TestClient

client = TestClient(app)


def test_diagnose_returns_503_without_poller_data():
    """Diagnose should return 503 when poller has no data."""
    old = poller._latest
    poller._latest = None
    try:
        resp = client.post("/api/cosmos/diagnose")
        assert resp.status_code == 503
    finally:
        poller._latest = old


def test_diagnose_returns_valid_schema():
    """Inject poller data directly, then diagnose."""
    poller._latest = {
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
    }

    try:
        resp = client.post("/api/cosmos/diagnose")
        assert resp.status_code == 200

        data = resp.json()
        assert "incident_id" in data
        assert "summary" in data
        assert "root_cause" in data
        assert "confidence" in data
        assert "reasoning" in data
        assert "suggested_checks" in data
        assert "cosmos_model" in data
        assert "timestamp" in data

        assert isinstance(data["summary"], str)
        assert isinstance(data["root_cause"], str)
        assert isinstance(data["confidence"], (int, float))
        assert 0 <= data["confidence"] <= 1
        assert isinstance(data["suggested_checks"], list)
        assert len(data["suggested_checks"]) > 0
    finally:
        poller._latest = None
