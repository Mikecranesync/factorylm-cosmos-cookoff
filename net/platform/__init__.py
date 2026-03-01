"""
Platform Abstraction Module

Provides a unified interface for platform-specific networking operations.
Automatically selects the appropriate implementation based on the operating system.
"""

import platform


def get_wifi_scanner():
    """
    Get the appropriate WiFi scanner for the current platform.

    Returns:
        LinuxWifiScanner on Linux with real WiFi hardware
        MockWifiScanner on other platforms or in sim mode
    """
    import os
    mode = os.environ.get("FACTORYLM_NET_MODE", "real")

    if mode == "sim":
        from .mock import MockWifiScanner
        return MockWifiScanner()

    if platform.system() == "Linux":
        try:
            from .linux import LinuxWifiScanner
            return LinuxWifiScanner()
        except Exception:
            from .mock import MockWifiScanner
            return MockWifiScanner()
    else:
        from .mock import MockWifiScanner
        return MockWifiScanner()


__all__ = ['get_wifi_scanner']
