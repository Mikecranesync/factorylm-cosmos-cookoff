"""
macOS platform stubs for WiFi operations.

On Pi, these would call iwlist/wpa_cli. On macOS (CHARLIE dev machine),
they return plausible mock data so the wizard flow works end-to-end.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

IS_LINUX = sys.platform == "linux"


class MockWifiScanner:
    """Mock WiFi scanner for dev/testing on non-Pi platforms."""

    def scan_networks(self) -> list[dict]:
        logger.info("WiFi scan: returning mock SSIDs (mock)")
        return [
            {"ssid": "PlantGuest", "signal": -45, "security": "open"},
            {"ssid": "PLC_WiFi_5G", "signal": -62, "security": "wpa2"},
            {"ssid": "Denny's Free WiFi", "signal": -70, "security": "open"},
        ]

    def connect_network(self, ssid: str, password: str = None) -> dict:
        logger.info("WiFi connect: mock success for '%s'", ssid)
        return {"success": True, "ssid": ssid, "ip": "10.10.10.55", "mocked": True}


# Legacy module-level functions (backwards compatibility)
def scan_wifi() -> list[dict]:
    """Scan for nearby WiFi networks."""
    if IS_LINUX:
        return _linux_wifi_scan()
    return MockWifiScanner().scan_networks()


def connect_wifi(ssid: str, password: str) -> dict:
    """Connect to a WiFi network."""
    if IS_LINUX:
        return _linux_wifi_connect(ssid, password)
    return MockWifiScanner().connect_network(ssid, password)


def _linux_wifi_scan() -> list[dict]:
    """Real WiFi scan using iwlist on Linux/Pi."""
    import subprocess

    try:
        result = subprocess.run(
            ["iwlist", "wlan0", "scan"],
            capture_output=True, text=True, timeout=10,
        )
        networks = []
        current = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Cell"):
                if current:
                    networks.append(current)
                current = {"ssid": "", "signal": 0, "security": "Open"}
            elif "ESSID:" in line:
                current["ssid"] = line.split('"')[1] if '"' in line else ""
            elif "Signal level=" in line:
                try:
                    sig = line.split("Signal level=")[1].split(" ")[0]
                    current["signal"] = int(sig)
                except (IndexError, ValueError):
                    pass
            elif "WPA" in line:
                current["security"] = "WPA2"
        if current and current.get("ssid"):
            networks.append(current)
        return networks
    except Exception as e:
        logger.error("WiFi scan failed: %s", e)
        return []


def _linux_wifi_connect(ssid: str, password: str) -> dict:
    """Real WiFi connect using wpa_cli on Linux/Pi."""
    import subprocess

    try:
        # Add network
        result = subprocess.run(
            ["wpa_cli", "-i", "wlan0", "add_network"],
            capture_output=True, text=True, timeout=5,
        )
        net_id = result.stdout.strip()

        subprocess.run(
            ["wpa_cli", "-i", "wlan0", "set_network", net_id, "ssid", f'"{ssid}"'],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["wpa_cli", "-i", "wlan0", "set_network", net_id, "psk", f'"{password}"'],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["wpa_cli", "-i", "wlan0", "enable_network", net_id],
            capture_output=True, timeout=5,
        )
        subprocess.run(
            ["wpa_cli", "-i", "wlan0", "save_config"],
            capture_output=True, timeout=5,
        )
        return {"success": True, "ssid": ssid, "ip": "obtaining..."}
    except Exception as e:
        logger.error("WiFi connect failed: %s", e)
        return {"success": False, "error": str(e)}
