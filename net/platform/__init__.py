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
        LinuxWifiScanner on Linux (Pi)
        MacOSWifiScanner on macOS (CHARLIE, ALPHA)
        MockWifiScanner as fallback
    """
    system = platform.system()

    if system == "Linux":
        try:
            from .linux import LinuxWifiScanner
            return LinuxWifiScanner()
        except Exception:
            pass

    if system == "Darwin":
        try:
            from .macos import MacOSWifiScanner
            scanner = MacOSWifiScanner()
            if scanner._available:
                return scanner
        except Exception:
            pass

    from .mock import MockWifiScanner
    return MockWifiScanner()


__all__ = ['get_wifi_scanner']
