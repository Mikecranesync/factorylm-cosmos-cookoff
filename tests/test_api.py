"""Test FastAPI endpoints (sim mode)."""
import os
import tempfile

os.environ["FACTORYLM_NET_MODE"] = "sim"
os.environ["FACTORYLM_NET_DB"] = os.path.join(tempfile.mkdtemp(), "factorylm_test_api.db")

from net.api.main import _init_db, app
_init_db()

from fastapi.testclient import TestClient
client = TestClient(app)

def test_scan_endpoint():
    resp = client.get("/api/plc/scan?subnet=192.168.1.0/24")
    assert resp.status_code == 200
    assert "devices" in resp.json()

def test_extract_endpoint():
    resp = client.post("/api/plc/extract", json={"ip": "192.168.1.100", "port": 502})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tags"]) > 0

def test_live_endpoint_returns_values():
    client.post("/api/plc/config", json={
        "ip": "192.168.1.100",
        "port": 502,
        "brand": "Micro 820",
        "template": "micro820"
    })
    import time
    time.sleep(1)
    resp = client.get("/api/plc/live")
    assert resp.status_code == 200

def test_wizard_serves_html():
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "FactoryLM" in resp.text

def test_status_endpoint():
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data

def test_wifi_scan():
    resp = client.get("/api/wifi/scan")
    # 200 on real Pi with WiFi, 503 when WiFi hardware unavailable
    assert resp.status_code in [200, 503]
    data = resp.json()
    if resp.status_code == 200:
        assert "networks" in data
    else:
        assert "error" in data
        assert data["error"] == "wifi_unavailable"

def test_root_redirects():
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in [301, 302, 307]
