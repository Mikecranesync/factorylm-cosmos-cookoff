"""
macOS WiFi scanner using CoreWLAN framework.

Used when running on macOS (e.g. CHARLIE dev/test node).
Requires: pip install pyobjc-framework-CoreWLAN
"""
from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


class MacOSWifiScanner:
    """Real WiFi scanning on macOS via CoreWLAN."""

    def __init__(self):
        try:
            import CoreWLAN
            self._client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
            self._iface = self._client.interface()
            self._available = True
        except Exception as e:
            logger.warning("CoreWLAN not available: %s", e)
            self._available = False

    def scan_networks(self) -> list[dict]:
        if not self._available:
            return []

        import CoreWLAN
        networks, err = self._iface.scanForNetworksWithName_error_(None, None)
        if not networks:
            logger.warning("WiFi scan failed: %s", err)
            return []

        # Deduplicate by SSID, keep strongest signal
        seen: dict[str, dict] = {}
        for net in networks:
            ssid = net.ssid()
            if not ssid:
                continue
            rssi = net.rssiValue()
            security = self._get_security(net)
            if ssid not in seen or rssi > seen[ssid]["signal"]:
                seen[ssid] = {
                    "ssid": ssid,
                    "signal": rssi,
                    "security": security,
                }

        return sorted(seen.values(), key=lambda n: n["signal"], reverse=True)

    def connect_network(self, ssid: str, password: str) -> dict:
        """Connect to a WiFi network using networksetup."""
        try:
            result = subprocess.run(
                ["networksetup", "-setairportnetwork", "en0", ssid, password],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return {"success": True, "ssid": ssid}
            return {"success": False, "error": result.stderr.strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def _get_security(network) -> str:
        """Detect security via supportsSecurity_() probing."""
        try:
            # CWSecurity enum: 0=None, 2=WEP, 4=WPAPersonal,
            # 8=WPA2Personal, 16=WPA3Personal
            if network.supportsSecurity_(16):
                return "wpa3"
            if network.supportsSecurity_(8) or network.supportsSecurity_(4):
                return "wpa2"
            if network.supportsSecurity_(2):
                return "wep"
            if network.supportsSecurity_(0):
                return "open"
            return "unknown"
        except Exception:
            return "unknown"
