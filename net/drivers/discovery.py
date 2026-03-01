"""
Async Modbus device discovery — scans a subnet for port 502 responders.

Validates each host with a Modbus read_coils(0,1) probe. Fingerprints
Allen-Bradley Micro 820 by checking register patterns.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import time
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


PROTOCOL_PORTS = {
    44818: "EtherNet/IP",
    4840: "OPC UA",
    102: "Siemens S7",
    502: "Modbus TCP",
}


@dataclass
class DiscoveredPLC:
    ip: str
    port: int
    brand: str
    model: str
    template: str | None
    response_ms: float
    protocol: str = "Modbus TCP"
    protocols: dict | None = None  # {port: protocol_name} for all open ports


async def _probe_host(
    ip: str,
    port: int = 502,
    timeout: float = 0.3,
) -> DiscoveredPLC | None:
    """TCP connect + Modbus validation for a single host."""
    t0 = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout,
        )
    except (asyncio.TimeoutError, OSError):
        return None

    # Build a Modbus TCP request: read_coils(0, 1)
    # Transaction ID=0x0001, Protocol=0x0000, Length=6, Unit=1
    # Function code 0x01, Start=0x0000, Count=0x0001
    request = bytes([
        0x00, 0x01,  # transaction id
        0x00, 0x00,  # protocol id
        0x00, 0x06,  # length
        0x01,        # unit id
        0x01,        # function code: read coils
        0x00, 0x00,  # start address
        0x00, 0x01,  # quantity
    ])

    try:
        writer.write(request)
        await writer.drain()
        response = await asyncio.wait_for(reader.read(256), timeout=timeout)
        writer.close()
        await writer.wait_closed()
    except (asyncio.TimeoutError, OSError):
        try:
            writer.close()
        except Exception:
            pass
        return None

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    # Validate: minimum Modbus TCP response is 9 bytes
    # Header (7) + function code (1) + byte count (1) + data (1)
    if len(response) < 9:
        return None

    # Check protocol ID bytes are 0x0000
    if response[2:4] != b'\x00\x00':
        return None

    # Function code should be 0x01 (not error 0x81)
    if response[7] == 0x81:
        return None

    # Valid Modbus device found — attempt fingerprint
    brand, model, template = _fingerprint(ip, port, response)

    # Detect additional protocol ports
    protocols = await _detect_protocols(ip, timeout)
    if not protocols:
        protocols = {port: "Modbus TCP"}

    # Primary protocol = the port we connected on
    primary_protocol = PROTOCOL_PORTS.get(port, "Modbus TCP")

    return DiscoveredPLC(
        ip=ip,
        port=port,
        brand=brand,
        model=model,
        template=template,
        response_ms=elapsed_ms,
        protocol=primary_protocol,
        protocols=protocols,
    )


def _fingerprint(
    ip: str, port: int, initial_response: bytes
) -> tuple[str, str, str | None]:
    """Attempt to identify PLC brand from response patterns."""
    # Micro 820 typically responds from unit ID 1 with specific patterns.
    # For now, we fingerprint by checking if registers 100-105 are readable
    # via a synchronous probe (called after initial async validation).
    # Default to generic if we can't determine.
    try:
        from pymodbus.client import ModbusTcpClient

        client = ModbusTcpClient(ip, port=port, timeout=1)
        if not client.connect():
            return "Generic Modbus", "Unknown", "generic_modbus"

        # Try reading holding registers 100-105 (Micro 820 canonical map)
        result = client.read_holding_registers(address=100, count=6)
        client.close()

        if not result.isError():
            # Registers 100-105 readable → likely Micro 820 or compatible
            return "Allen-Bradley", "Micro 820", "micro820"
    except Exception:
        pass

    return "Generic Modbus", "Unknown", "generic_modbus"


async def _probe_port(ip: str, port: int, timeout: float = 0.3) -> bool:
    """Check if a TCP port is open on the given host."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, OSError):
        return False


async def _detect_protocols(ip: str, timeout: float = 0.3) -> dict:
    """Probe all known industrial protocol ports on a host.

    Returns dict of {port: protocol_name} for open ports.
    """
    results = {}
    tasks = {
        port: _probe_port(ip, port, timeout)
        for port in PROTOCOL_PORTS
    }
    for port, coro in tasks.items():
        if await coro:
            results[port] = PROTOCOL_PORTS[port]
    return results


async def scan_subnet(
    subnet: str = "192.168.1.0/24",
    port: int = 502,
    timeout: float = 0.3,
    max_concurrent: int = 50,
) -> list[DiscoveredPLC]:
    """Scan an entire subnet for Modbus TCP devices."""
    logger.info("Scanning %s for Modbus devices on port %d", subnet, port)
    t0 = time.monotonic()

    try:
        network = ipaddress.ip_network(subnet, strict=False)
    except ValueError:
        logger.error("Invalid subnet: %s", subnet)
        return []

    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_probe(ip_str: str) -> DiscoveredPLC | None:
        async with semaphore:
            return await _probe_host(ip_str, port, timeout)

    tasks = [bounded_probe(str(ip)) for ip in network.hosts()]
    results = await asyncio.gather(*tasks)

    devices = [d for d in results if d is not None]
    elapsed = round(time.monotonic() - t0, 2)
    logger.info("Scan complete: %d devices found in %ss", len(devices), elapsed)

    return devices


def fake_scan_result() -> list[DiscoveredPLC]:
    """Return a fake PLC for sim mode testing."""
    return [
        DiscoveredPLC(
            ip="192.168.1.100",
            port=502,
            brand="Allen-Bradley",
            model="Micro 820 (simulated)",
            template="micro820",
            response_ms=2.1,
            protocol="Modbus TCP",
            protocols={502: "Modbus TCP"},
        )
    ]


def load_template(name: str) -> dict | None:
    """Load a PLC template JSON by name."""
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
