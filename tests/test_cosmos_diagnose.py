"""Test POST /api/cosmos/diagnose endpoint (sim mode)."""
import os
import tempfile
import time

os.environ["FACTORYLM_NET_MODE"] = "sim"
os.environ["FACTORYLM_NET_DB"] = os.path.join(tempfile.mkdtemp(), "factorylm_test_cosmos.db")

from net.api.main import _init_db, app, poller

_init_db()

from fastapi.testclient import TestClient

client = TestClient(app)


def test_diagnose_returns_503_without_poller_data():
    """Diagnose should return 503 when poller has no data."""
    if poller.latest is not None:
        # Poller already has data from prior test modules sharing the singleton
        return
    resp = client.post("/api/cosmos/diagnose")
    assert resp.status_code == 503


def test_diagnose_returns_valid_schema():
    """Configure poller in SIM mode, wait for data, then diagnose."""
    # Configure PLC to start the poller
    config_resp = client.post("/api/plc/config", json={
        "ip": "192.168.1.100",
        "port": 502,
        "brand": "Micro 820",
        "template": "micro820",
    })
    assert config_resp.status_code == 200

    # Wait for poller to produce data
    for _ in range(10):
        time.sleep(0.5)
        status = client.get("/api/status").json()
        if status.get("latest_tags"):
            break

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

    # Validate types
    assert isinstance(data["summary"], str)
    assert isinstance(data["root_cause"], str)
    assert isinstance(data["confidence"], (int, float))
    assert 0 <= data["confidence"] <= 1
    assert isinstance(data["suggested_checks"], list)
    assert len(data["suggested_checks"]) > 0
