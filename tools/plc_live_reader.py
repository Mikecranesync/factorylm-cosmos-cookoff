#!/usr/bin/env python3
"""Live PLC tag reader using pylogix for Micro800 series.

Usage:
    python3 plc_live_reader.py [--host 192.168.1.100] [--interval 2]

Connects to Allen-Bradley Micro820/850 via EtherNet/IP,
discovers all tags, then polls them in a loop.
"""

import argparse
import sys
import time

from pylogix import PLC


def discover_tags(comm):
    """Get all tags from the PLC and print them."""
    print("=" * 60)
    print("TAG DISCOVERY")
    print("=" * 60)
    result = comm.GetTagList()
    if result.Status != "Success":
        print(f"GetTagList FAILED: {result.Status}")
        return []

    tags = result.Value
    print(f"Found {len(tags)} tags:\n")
    for t in tags:
        print(f"  {t.TagName:<30} Type={t.DataType}")
    print()
    return [t.TagName for t in tags]


def read_all_tags(comm, tag_names):
    """Read every tag and print name, value, status."""
    print("-" * 60)
    print(f"LIVE READ  {time.strftime('%H:%M:%S')}")
    print("-" * 60)
    for name in tag_names:
        ret = comm.Read(name)
        val = ret.Value
        status = ret.Status
        if status == "Success":
            print(f"  {name:<30} = {val}")
        else:
            print(f"  {name:<30} = ERROR ({status})")
    print()


def main():
    parser = argparse.ArgumentParser(description="Live Micro800 tag reader")
    parser.add_argument("--host", default="192.168.1.100", help="PLC IP")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll seconds")
    args = parser.parse_args()

    print(f"Connecting to Micro800 at {args.host} ...")
    comm = PLC()
    comm.IPAddress = args.host
    comm.Micro800 = True

    # Discover tags once
    tag_names = discover_tags(comm)
    if not tag_names:
        print("No tags found. Is the PLC in Run mode with a program loaded?")
        comm.Close()
        sys.exit(1)

    # Poll loop
    print(f"Polling every {args.interval}s — Ctrl+C to stop\n")
    try:
        while True:
            read_all_tags(comm, tag_names)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        comm.Close()


if __name__ == "__main__":
    main()
