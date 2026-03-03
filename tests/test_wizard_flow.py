"""End-to-end test of the first-run wizard flow — mocks, no sim mode.

Walks through every screen of the 6-step setup wizard, hitting
the same API endpoints the JavaScript calls, in order:

  Screen 1  Welcome      -> GET  /api/gateway/id
                          -> GET  /api/gateway/qr   (optional, needs qrcode lib)
  Screen 2  PLC Discovery-> GET  /api/plc/scan
  Screen 3  Tag Extract  -> POST /api/plc/extract
  Screen 4  Tag Select   -> (client-side only)
  Screen 5  Live Preview -> POST /api/plc/config
                          -> POST /api/plc/live
  Screen 6  WiFi / Finish-> GET  /api/wifi/scan
                          -> POST /api/wifi/connect
                          -> GET  /api/status
"""

import os
import tempfile
from unittest.mock import patch, AsyncMock

os.environ["FACTORYLM_NET_DB"] = os.path.join(tempfile.mkdtemp(), "wizard_flow_test.db")

from net.api.main import _init_db, app, poller
from net.drivers.discovery import DiscoveredPLC
from net.drivers.tag_extractor import ExtractionResult

_init_db()

from fastapi.testclient import TestClient

client = TestClient(app)


def _mock_scan():
    """Return a mock scan result."""
    return [
        DiscoveredPLC(ip="192.168.1.100", port=502, brand="Allen-Bradley",
                      model="Micro820", template="micro820", response_ms=12)
    ]


def _mock_extract_result():
    """Return a mock extraction result."""
    return ExtractionResult(
        gateway_id="flm-test",
        plc_ip="192.168.1.100",
        protocol="Modbus",
        extraction_method="modbus_brute_force",
        extracted_at="2025-01-01T00:00:00Z",
        tags=[
            {"name": "Conveyor", "plc_address": "coil:0", "type": "BOOL",
             "value": True, "address": None, "named": True, "writable": True},
            {"name": "motor_speed", "plc_address": "hr:101", "type": "INT",
             "value": 85, "address": None, "named": True, "writable": True},
            {"name": "temperature", "plc_address": "hr:103", "type": "REAL",
             "value": 48.7, "address": None, "named": True, "writable": False},
        ],
    )


# -- Screen 1: Welcome --

def test_screen1_gateway_id():
    resp = client.get("/api/gateway/id")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["id"].startswith("flm-")
    resp2 = client.get("/api/gateway/id")
    assert resp2.json()["id"] == data["id"]


def test_screen1_gateway_qr():
    resp = client.get("/api/gateway/qr")
    assert resp.status_code in [200, 503]
    if resp.status_code == 200:
        assert resp.headers["content-type"] == "image/png"
    else:
        assert "qrcode" in resp.json().get("detail", "").lower()


# -- Screen 2: PLC Discovery --

def test_screen2_plc_scan():
    with patch("net.api.main.scan_subnet", new_callable=AsyncMock, return_value=_mock_scan()):
        resp = client.get("/api/plc/scan?subnet=192.168.1.0/24")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" not in data
        assert len(data["devices"]) >= 1
        dev = data["devices"][0]
        for key in ("ip", "port", "brand", "model", "template", "status"):
            assert key in dev, f"Missing key '{key}' in device payload"


# -- Screen 3: Tag Extraction --

def test_screen3_tag_extraction():
    with patch("net.api.main.extract_tags", new_callable=AsyncMock, return_value=_mock_extract_result()):
        resp = client.post("/api/plc/extract", json={"ip": "192.168.1.100", "port": 502})
        assert resp.status_code == 200
        data = resp.json()
        assert "tags" in data
        assert len(data["tags"]) > 0


# -- Screen 4: Tag Selection --

def test_screen4_tag_selection_shape():
    with patch("net.api.main.extract_tags", new_callable=AsyncMock, return_value=_mock_extract_result()):
        resp = client.post("/api/plc/extract", json={"ip": "192.168.1.100", "port": 502})
        tags = resp.json()["tags"]
        assert isinstance(tags, list)
        assert len(tags) >= 1


# -- Screen 5: Panel Preview + Live Polling --

def test_screen5_plc_config_save():
    payload = {
        "name": "Live Dashboard",
        "device_ip": "192.168.1.100",
        "device_port": 502,
        "protocol": "modbus",
        "tags": [
            {"name": "motor_speed", "address": "HR101", "type": "register"},
            {"name": "conveyor_running", "address": "C0", "type": "coil"},
        ],
    }
    resp = client.post("/api/plc/config", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "configured"
    assert data["polling"] is True


def test_screen5_live_polling():
    poller._latest = {
        "motor_speed": 60,
        "conveyor_running": True,
        "timestamp": "2025-01-01T00:00:00Z",
    }
    try:
        resp = client.post("/api/plc/live", json={
            "ip": "192.168.1.100",
            "port": 502,
            "tags": ["motor_speed"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert isinstance(data["data"], dict)
    finally:
        poller._latest = None


# -- Screen 6: WiFi Config + Finish --

def test_screen6_wifi_scan():
    resp = client.get("/api/wifi/scan")
    assert resp.status_code in [200, 503]
    if resp.status_code == 200:
        assert "networks" in resp.json()


def test_screen6_wifi_connect():
    resp = client.post("/api/wifi/connect", json={
        "ssid": "TestNetwork",
        "password": "password123",
    })
    assert resp.status_code in [200, 503]


def test_screen6_final_status():
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "gateway_id" in data
    assert data["gateway_id"].startswith("flm-")
    assert "mode" not in data
    assert "running_on" in data


# -- Full Flow Integration --

def test_full_wizard_flow_sequential():
    r1 = client.get("/api/gateway/id")
    assert r1.status_code == 200
    gw_id = r1.json()["id"]

    with patch("net.api.main.scan_subnet", new_callable=AsyncMock, return_value=_mock_scan()):
        r2 = client.get("/api/plc/scan?subnet=192.168.1.0/24")
        assert r2.status_code == 200
        devices = r2.json()["devices"]
        assert len(devices) >= 1

    with patch("net.api.main.extract_tags", new_callable=AsyncMock, return_value=_mock_extract_result()):
        r3 = client.post("/api/plc/extract", json={"ip": "192.168.1.100", "port": 502})
        assert r3.status_code == 200
        tags = r3.json()["tags"]
        assert len(tags) > 0

    selected = tags[:3]

    r5a = client.post("/api/plc/config", json={
        "name": "Live Dashboard",
        "device_ip": "192.168.1.100",
        "device_port": 502,
        "protocol": "modbus",
        "tags": selected,
    })
    assert r5a.status_code == 200
    assert r5a.json()["status"] == "configured"

    poller._latest = {"motor_speed": 60, "timestamp": "2025-01-01T00:00:00Z"}
    try:
        r5b = client.post("/api/plc/live", json={
            "ip": "192.168.1.100",
            "port": 502,
            "tags": ["motor_speed"],
        })
        assert r5b.status_code == 200
        assert "data" in r5b.json()

        r6b = client.get("/api/status")
        assert r6b.status_code == 200
        status = r6b.json()
        assert status["gateway_id"] == gw_id
    finally:
        poller._latest = None


# -- Wizard HTML Loads --

def test_wizard_html_loads():
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "Pi Factory" in resp.text
    assert "screen-1" in resp.text or "Welcome" in resp.text
