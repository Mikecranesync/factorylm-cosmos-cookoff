#!/usr/bin/env python3
"""
VFD Probe — Standalone diagnostic tool for ATO GS10 VFD over Modbus TCP.

Scans for Modbus TCP devices and probes all VFD register banks with
decoded output. Use this to discover and verify VFD connectivity
before configuring Pi-Factory.

Usage:
    python3 tools/probe_vfd.py                          # probe default 192.168.1.101
    python3 tools/probe_vfd.py --host 192.168.1.101     # probe specific host
    python3 tools/probe_vfd.py --scan                   # scan subnet first
    python3 tools/probe_vfd.py --scan --range 1-30      # custom IP range
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

# ATO GS10 fault code descriptions
VFD_FAULT_CODES = {
    0: "No fault",
    1: "Overcurrent during acceleration",
    2: "Overcurrent during deceleration",
    3: "Overcurrent at constant speed",
    4: "Overvoltage during acceleration",
    5: "Overvoltage during deceleration",
    6: "Overvoltage at constant speed",
    7: "DC bus undervoltage",
    8: "Drive overtemperature",
    9: "Motor overload",
    10: "Input phase loss",
    11: "Output phase loss",
    12: "External fault",
    13: "Communication loss",
}


def scan_subnet(subnet_prefix: str = "192.168.1", start: int = 1, end: int = 30, port: int = 502) -> list:
    """Scan a range of IPs for Modbus TCP responders."""
    from pymodbus.client import ModbusTcpClient

    found = []
    print(f"Scanning {subnet_prefix}.{start}-{end} on port {port}...")
    for i in range(start, end + 1):
        ip = f"{subnet_prefix}.{i}"
        try:
            c = ModbusTcpClient(ip, port=port, timeout=0.5)
            if c.connect():
                # Try a basic register read
                r = c.read_holding_registers(0, count=1)
                if hasattr(r, "registers"):
                    status = f"MODBUS OK (reg[0]={r.registers[0]})"
                else:
                    status = "CONNECTED (no data)"
                found.append((ip, port, status))
                print(f"  FOUND: {ip}:{port} -- {status}")
                c.close()
        except Exception:
            pass

    if not found:
        print("  No Modbus TCP devices found in range.")
    return found


def probe_slave(host: str, port: int, slave: int) -> dict:
    """Probe a single slave ID on the given host, return results dict."""
    from pymodbus.client import ModbusTcpClient

    result = {"slave": slave, "connected": False, "registers": {}}

    c = ModbusTcpClient(host, port=port, timeout=2)
    if not c.connect():
        return result

    result["connected"] = True

    # Writable registers: 0x2000-0x2001
    try:
        r = c.read_holding_registers(0x2000, count=2, slave=slave)
        if hasattr(r, "registers"):
            result["registers"]["0x2000 (control_word)"] = r.registers[0]
            result["registers"]["0x2001 (setpoint_hz)"] = f"{r.registers[1]} -> {r.registers[1] / 100.0:.2f} Hz"
    except Exception as e:
        result["registers"]["0x2000-0x2001"] = f"ERROR: {e}"

    # Status registers: 0x2100-0x210B (12 registers)
    status_tags = [
        ("0x2100", "status_word", 1, ""),
        ("0x2101", "output_hz", 100, " Hz"),
        ("0x2102", "output_amps", 10, " A"),
        ("0x2103", "actual_freq", 100, " Hz"),
        ("0x2104", "actual_current", 10, " A"),
        ("0x2105", "dc_bus_volts", 10, " V"),
        ("0x2106", "motor_rpm", 1, " RPM"),
        ("0x2107", "torque_pct", 10, "%"),
        ("0x2108", "drive_temp_c", 10, " C"),
        ("0x2109", "fault_code", 1, ""),
        ("0x210A", "warning_code", 1, ""),
        ("0x210B", "run_hours", 1, " hrs"),
    ]

    try:
        r = c.read_holding_registers(0x2100, count=12, slave=slave)
        if hasattr(r, "registers"):
            for i, (addr, name, scale, unit) in enumerate(status_tags):
                raw = r.registers[i]
                if scale == 1:
                    decoded = str(raw)
                else:
                    decoded = f"{raw} -> {raw / scale:.1f}"
                # Add fault description
                if name == "fault_code":
                    desc = VFD_FAULT_CODES.get(raw, f"Unknown ({raw})")
                    decoded += f" [{desc}]"
                result["registers"][f"{addr} ({name})"] = f"{decoded}{unit}"
        else:
            result["registers"]["0x2100-0x210B"] = f"READ ERROR: {r}"
    except Exception as e:
        result["registers"]["0x2100-0x210B"] = f"ERROR: {e}"

    # Parameter block P000-P010 (address 0x0000-0x000A)
    try:
        r = c.read_holding_registers(0x0000, count=11, slave=slave)
        if hasattr(r, "registers"):
            non_zero = [(i, v) for i, v in enumerate(r.registers) if v != 0]
            if non_zero:
                for idx, val in non_zero:
                    result["registers"][f"P{idx:03d}"] = str(val)
    except Exception:
        pass  # Parameter block may not be readable

    c.close()
    return result


def print_report(host: str, port: int, results: list, output_file: str = None):
    """Print and optionally save probe results."""
    lines = []
    lines.append(f"{'=' * 60}")
    lines.append(f"VFD PROBE REPORT")
    lines.append(f"Target: {host}:{port}")
    lines.append(f"Time:   {datetime.datetime.now().isoformat()}")
    lines.append(f"{'=' * 60}")

    responding = [r for r in results if r["registers"]]
    if not responding:
        lines.append(f"\nNo responding slaves found at {host}:{port}")
        lines.append("Check:")
        lines.append("  - VFD Modbus TCP enabled (P14.00=1, P14.01=2)")
        lines.append("  - Correct IP address and subnet")
        lines.append("  - Network cable connected")
    else:
        for r in results:
            if not r["connected"]:
                continue
            if not r["registers"]:
                continue
            lines.append(f"\nSlave {r['slave']}:")
            for reg, val in r["registers"].items():
                lines.append(f"  {reg:30s}  {val}")

    lines.append(f"\n{'=' * 60}")

    report = "\n".join(lines)
    print(report)

    if output_file:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w") as f:
            f.write(report)
        print(f"\nReport saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="ATO GS10 VFD Modbus TCP Probe")
    parser.add_argument("--host", default="192.168.1.101", help="VFD IP address (default: 192.168.1.101)")
    parser.add_argument("--port", type=int, default=502, help="Modbus TCP port (default: 502)")
    parser.add_argument("--scan", action="store_true", help="Scan subnet before probing")
    parser.add_argument("--range", default="1-30", help="IP range for scan (default: 1-30)")
    parser.add_argument("--slaves", default="1-20", help="Slave ID range to probe (default: 1-20)")
    parser.add_argument("--output", default=None, help="Save report to file")
    args = parser.parse_args()

    try:
        from pymodbus.client import ModbusTcpClient
    except ImportError:
        print("ERROR: pymodbus not installed. Run: pip install pymodbus")
        sys.exit(1)

    # Subnet scan
    if args.scan:
        parts = args.host.rsplit(".", 1)
        prefix = parts[0] if len(parts) == 2 else "192.168.1"
        range_parts = args.range.split("-")
        start = int(range_parts[0])
        end = int(range_parts[1]) if len(range_parts) > 1 else start
        found = scan_subnet(prefix, start, end, args.port)
        if found:
            print(f"\nFound {len(found)} device(s). Probing each...\n")
            for ip, port, _ in found:
                args.host = ip
                # Fall through to probe below
        else:
            print("\nNo devices found. Check network connectivity.")
            sys.exit(1)

    # Probe slave IDs
    slave_parts = args.slaves.split("-")
    slave_start = int(slave_parts[0])
    slave_end = int(slave_parts[1]) if len(slave_parts) > 1 else slave_start

    print(f"\nProbing {args.host}:{args.port} slaves {slave_start}-{slave_end}...")
    results = []
    for slave_id in range(slave_start, slave_end + 1):
        r = probe_slave(args.host, args.port, slave_id)
        if r["registers"]:
            print(f"  Slave {slave_id}: RESPONDING")
        results.append(r)

    output = args.output
    if output is None:
        # Default to cluster log path if it exists
        cluster_log = "/Users/Shared/cluster/betterclaw/logs"
        if os.path.isdir(cluster_log):
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            output = os.path.join(cluster_log, f"VFD-PROBE-{date_str}.txt")

    print_report(args.host, args.port, results, output)


if __name__ == "__main__":
    main()
