"""End-to-end test of the first-run wizard flow (sim mode).

Walks through every screen of the 6-step setup wizard, hitting
the same API endpoints the JavaScript calls, in order:

  Screen 1  Welcome      → GET  /api/gateway/id
                          → GET  /api/gateway/qr   (optional, needs qrcode lib)
  Screen 2  PLC Discovery→ GET  /api/plc/scan
  Screen 3  Tag Extract  → POST /api/plc/extract
  Screen 4  Tag Select   → (client-side only — verify extract payload shape)
  Screen 5  Live Preview → POST /api/plc/config    (save selected tags)
                          → POST /api/plc/live      (poll live data)
  Screen 6  WiFi / Finish→ GET  /api/wifi/scan
                          → POST /api/wifi/connect  (may 503 — OK)
                          → GET  /api/status         (final health check)
"""

import os
import tempfile
import time

os.environ["FACTORYLM_NET_MODE"] = "sim"
os.environ["FACTORYLM_NET_DB"] = os.path.join(tempfile.mkdtemp(), "wizard_flow_test.db")

from net.api.main import _init_db, app

_init_db()

from fastapi.testclient import TestClient

client = TestClient(app)


# ── Screen 1: Welcome ────────────────────────────────────────────────

def test_screen1_gateway_id():
    """Gateway ID is generated and returned."""
    resp = client.get("/api/gateway/id")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["id"].startswith("flm-")
    # Calling again returns the same ID (idempotent)
    resp2 = client.get("/api/gateway/id")
    assert resp2.json()["id"] == data["id"]


def test_screen1_gateway_qr():
    """QR endpoint returns PNG or graceful 503 if qrcode lib missing."""
    resp = client.get("/api/gateway/qr")
    assert resp.status_code in [200, 503]
    if resp.status_code == 200:
        assert resp.headers["content-type"] == "image/png"
    else:
        assert "qrcode" in resp.json().get("detail", "").lower()


# ── Screen 2: PLC Discovery ──────────────────────────────────────────

def test_screen2_plc_scan():
    """Scan returns at least one simulated device."""
    resp = client.get("/api/plc/scan?subnet=192.168.1.0/24")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "sim"
    assert len(data["devices"]) >= 1
    dev = data["devices"][0]
    # Each device has the fields the wizard JS expects
    for key in ("ip", "port", "brand", "model", "template", "status"):
        assert key in dev, f"Missing key '{key}' in device payload"


# ── Screen 3: Tag Extraction ─────────────────────────────────────────

def test_screen3_tag_extraction():
    """Extract tags from a simulated PLC."""
    resp = client.post("/api/plc/extract", json={"ip": "192.168.1.100", "port": 502})
    assert resp.status_code == 200
    data = resp.json()
    assert "tags" in data
    assert len(data["tags"]) > 0
    # Each tag must have at least a name and address
    tag = data["tags"][0]
    assert "name" in tag or "tag" in tag or "address" in tag, (
        f"Tag object missing expected keys: {list(tag.keys())}"
    )


# ── Screen 4: Tag Selection (client-side) ─────────────────────────────
# No API call — the wizard simply builds a list from Screen 3's tags.
# We just verify that the extract response is iterable.

def test_screen4_tag_selection_shape():
    """The extract response can be iterated to build a selection list."""
    resp = client.post("/api/plc/extract", json={"ip": "192.168.1.100", "port": 502})
    tags = resp.json()["tags"]
    assert isinstance(tags, list)
    assert len(tags) >= 1


# ── Screen 5: Panel Preview + Live Polling ────────────────────────────

def test_screen5_plc_config_save():
    """Save PLC configuration with wizard-shape payload."""
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
    """After config, live endpoint returns tag data."""
    # Ensure config is saved and poller started
    client.post("/api/plc/config", json={
        "name": "Live Dashboard",
        "device_ip": "192.168.1.100",
        "device_port": 502,
        "protocol": "modbus",
        "tags": [{"name": "motor_speed", "address": "HR101", "type": "register"}],
    })
    # Give poller time to produce first snapshot
    time.sleep(1)

    resp = client.post("/api/plc/live", json={
        "ip": "192.168.1.100",
        "port": 502,
        "tags": ["motor_speed"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    # data might be empty if sim hasn't ticked yet — that's acceptable
    # but it must be a dict, not None
    assert isinstance(data["data"], dict)


# ── Screen 6: WiFi Config + Finish ───────────────────────────────────

def test_screen6_wifi_scan():
    """WiFi scan returns networks or graceful 503."""
    resp = client.get("/api/wifi/scan")
    assert resp.status_code in [200, 503]
    if resp.status_code == 200:
        assert "networks" in resp.json()


def test_screen6_wifi_connect():
    """WiFi connect returns success or graceful 503."""
    resp = client.post("/api/wifi/connect", json={
        "ssid": "TestNetwork",
        "password": "password123",
    })
    assert resp.status_code in [200, 503]


def test_screen6_final_status():
    """Final status endpoint confirms gateway is healthy after wizard."""
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "gateway_id" in data
    assert data["gateway_id"].startswith("flm-")
    assert data["mode"] == "sim"
    assert "plc" in data


# ── Full Flow Integration ─────────────────────────────────────────────

def test_full_wizard_flow_sequential():
    """Walk the entire wizard flow in order, verifying each step succeeds."""
    # Screen 1: Get gateway ID
    r1 = client.get("/api/gateway/id")
    assert r1.status_code == 200
    gw_id = r1.json()["id"]

    # Screen 2: Scan for PLCs
    r2 = client.get("/api/plc/scan?subnet=192.168.1.0/24")
    assert r2.status_code == 200
    devices = r2.json()["devices"]
    assert len(devices) >= 1
    plc_ip = devices[0]["ip"]
    plc_port = devices[0]["port"]

    # Screen 3: Extract tags from discovered PLC
    r3 = client.post("/api/plc/extract", json={"ip": plc_ip, "port": plc_port})
    assert r3.status_code == 200
    tags = r3.json()["tags"]
    assert len(tags) > 0

    # Screen 4: Select tags (client-side; pick first 5)
    selected = tags[:5]

    # Screen 5: Save config and poll
    r5a = client.post("/api/plc/config", json={
        "name": "Live Dashboard",
        "device_ip": plc_ip,
        "device_port": plc_port,
        "protocol": "modbus",
        "tags": selected,
    })
    assert r5a.status_code == 200
    assert r5a.json()["status"] == "configured"

    time.sleep(0.5)

    # Poll live data
    tag_names = [t.get("name", t.get("tag", "")) for t in selected if t.get("name") or t.get("tag")]
    r5b = client.post("/api/plc/live", json={
        "ip": plc_ip,
        "port": plc_port,
        "tags": tag_names,
    })
    assert r5b.status_code == 200
    assert "data" in r5b.json()

    # Screen 6: WiFi + status
    r6a = client.get("/api/wifi/scan")
    assert r6a.status_code in [200, 503]

    r6b = client.get("/api/status")
    assert r6b.status_code == 200
    status = r6b.json()
    assert status["gateway_id"] == gw_id
    assert status["plc"]["polling"] is True


# ── Wizard HTML Loads ─────────────────────────────────────────────────

def test_wizard_html_loads():
    """The wizard HTML page loads and contains Pi Factory branding."""
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "Pi Factory" in resp.text
    # Verify key screen elements exist
    assert "screen-1" in resp.text or "Welcome" in resp.text
