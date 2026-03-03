"""Test FastAPI endpoints — mocks, no sim mode."""
import os
import tempfile
from unittest.mock import patch, AsyncMock

os.environ["FACTORYLM_NET_DB"] = os.path.join(tempfile.mkdtemp(), "factorylm_test_api.db")

from net.api.main import _init_db, app, poller
_init_db()

from fastapi.testclient import TestClient
client = TestClient(app)


def test_scan_endpoint():
    with patch("net.api.main.scan_subnet", new_callable=AsyncMock) as mock_scan:
        from net.drivers.discovery import DiscoveredPLC
        mock_scan.return_value = [
            DiscoveredPLC(ip="192.168.1.100", port=502, brand="Allen-Bradley",
                          model="Micro820", template="micro820", response_ms=12)
        ]
        resp = client.get("/api/plc/scan?subnet=192.168.1.0/24")
        assert resp.status_code == 200
        assert "devices" in resp.json()
        assert len(resp.json()["devices"]) >= 1


def test_live_endpoint_returns_values():
    poller._latest = {"motor_speed": 60, "timestamp": "2025-01-01T00:00:00Z"}
    resp = client.get("/api/plc/live")
    assert resp.status_code == 200
    poller._latest = None


def test_wizard_serves_html():
    resp = client.get("/setup")
    assert resp.status_code == 200
    assert "Pi Factory" in resp.text


def test_status_endpoint():
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" not in data
    assert "running_on" in data
    assert "version" in data
    assert data["version"] == "3.0.0"
    assert "gateway_id" in data


def test_wifi_scan():
    resp = client.get("/api/wifi/scan")
    assert resp.status_code in [200, 503]
    data = resp.json()
    if resp.status_code == 200:
        assert "networks" in data
    else:
        assert "error" in data
        assert data["error"] == "wifi_unavailable"


def test_root_serves_panel_or_redirects():
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in [200, 301, 302, 307]


def test_panel_route():
    resp = client.get("/panel")
    assert resp.status_code == 200
    assert "FactoryLM" in resp.text


def test_vfd_status_not_configured():
    resp = client.get("/api/vfd/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["vfd_connected"] is False


def test_conflicts_empty_when_no_vfd():
    resp = client.get("/api/conflicts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["conflicts"] == []
    assert data["vfd_connected"] is False
