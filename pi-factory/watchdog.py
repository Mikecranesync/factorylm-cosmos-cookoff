#!/usr/bin/env python3
"""FactoryLM Watchdog — monitors Micro820 PLC, GS10 VFD, and CHARLIE laptop."""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

import requests
from pylogix import PLC as LogixPLC
from pymodbus.client import ModbusTcpClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEVICES = [
    {"name": "Micro820 PLC", "ip": "192.168.1.100", "check": "pylogix"},
    {"name": "GS10 VFD",     "ip": "192.168.1.101", "check": "modbus"},
    {"name": "CHARLIE",      "ip": "192.168.1.12",  "check": "ping"},
]

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Device checks
# ---------------------------------------------------------------------------

def check_pylogix(ip: str) -> bool:
    """Read a tag from the Micro820 via pylogix. Online if no exception."""
    try:
        with LogixPLC(ip) as plc:
            plc.IPAddress = ip
            result = plc.Read("Conveyor")
            return result.Status == "Success"
    except Exception:
        return False


def check_modbus(ip: str) -> bool:
    """Connect to the GS10 VFD over Modbus TCP and read register 0x2103."""
    client = ModbusTcpClient(ip, port=502, timeout=3)
    try:
        if not client.connect():
            return False
        result = client.read_holding_registers(0x2103, count=1, slave=1)
        return not result.isError()
    except Exception:
        return False
    finally:
        client.close()


def check_ping(ip: str) -> bool:
    """ICMP ping. Online if return code is 0."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except Exception:
        return False


CHECK_FN = {
    "pylogix": check_pylogix,
    "modbus":  check_modbus,
    "ping":    check_ping,
}

# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def send_telegram(message: str, dry_run: bool = False) -> None:
    """Send a Telegram message. Falls back to stdout on failure."""
    print(message)
    if dry_run:
        return
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
        }, timeout=10)
    except Exception as exc:
        print(f"[telegram error] {exc}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="FactoryLM Watchdog")
    parser.add_argument("--interval", type=int, default=10,
                        help="Poll interval in seconds (default: 10)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print alerts to stdout instead of Telegram")
    args = parser.parse_args()

    # Previous state: None = unknown (first poll)
    state: dict[str, bool | None] = {d["name"]: None for d in DEVICES}

    device_names = ", ".join(d["name"] for d in DEVICES)
    send_telegram(
        f"FactoryLM Watchdog started. Monitoring: {device_names}",
        dry_run=args.dry_run,
    )

    while True:
        for device in DEVICES:
            name = device["name"]
            ip = device["ip"]
            online = CHECK_FN[device["check"]](ip)
            prev = state[name]

            if prev is None:
                # First poll — record state, no alert
                state[name] = online
                continue

            if online and not prev:
                send_telegram(
                    f"\u2705 ONLINE: {name} ({ip}) at {timestamp()}",
                    dry_run=args.dry_run,
                )
            elif not online and prev:
                send_telegram(
                    f"\u26a0\ufe0f OFFLINE: {name} ({ip}) at {timestamp()}",
                    dry_run=args.dry_run,
                )

            state[name] = online

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
