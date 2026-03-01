"""
Master auto-extraction engine for industrial protocol tag discovery.

Implements priority waterfall scanning across multiple industrial protocols:
- EtherNet/IP (port 44818)
- OPC UA (port 4840)
- Siemens S7 (port 102)
- Modbus (port 502)

Provides standardized tag extraction with asyncio-based concurrent scanning.
"""

import asyncio
import logging
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
import os
from enum import Enum

logger = logging.getLogger(__name__)


class Protocol(Enum):
    """Supported industrial protocols."""
    ETHIP = "EtherNetIP"
    OPCUA = "OpcUa"
    S7 = "Siemens_S7"
    MODBUS = "Modbus"


@dataclass
class Tag:
    """Represents a single industrial tag."""
    name: str
    address: Optional[str] = None
    plc_address: str = ""
    type: str = "UNKNOWN"
    value: Any = None
    named: bool = True
    writable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert tag to dictionary, handling special types."""
        d = asdict(self)
        # Ensure value is JSON-serializable
        if d['value'] is not None:
            try:
                json.dumps(d['value'])
            except (TypeError, ValueError):
                d['value'] = str(d['value'])
        return d


@dataclass
class ExtractionResult:
    """Standardized extraction result format."""
    gateway_id: str
    plc_ip: str
    protocol: str
    extraction_method: str
    extracted_at: str
    tags: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class TagExtractor:
    """
    Master auto-extraction engine coordinating protocol-specific readers.

    Implements priority waterfall scanning with asyncio-based concurrency.
    Supports simulation mode for testing without actual hardware.
    """

    # Priority order for protocol scanning
    PROTOCOL_PRIORITY = [
        (Protocol.ETHIP, 44818),
        (Protocol.OPCUA, 4840),
        (Protocol.S7, 102),
        (Protocol.MODBUS, 502),
    ]

    def __init__(
        self,
        gateway_id: str,
        plc_ip: str,
        semaphore_count: int = 50,
        timeout_seconds: float = 0.3,
        sim_mode: Optional[bool] = None,
    ):
        """
        Initialize tag extractor.

        Args:
            gateway_id: Unique gateway identifier
            plc_ip: IP address of target PLC
            semaphore_count: Maximum concurrent connections (default 50)
            timeout_seconds: Connection timeout in seconds (default 0.3)
            sim_mode: Override SIM mode detection (uses env var if None)
        """
        self.gateway_id = gateway_id
        self.plc_ip = plc_ip
        self.semaphore = asyncio.Semaphore(semaphore_count)
        self.timeout = timeout_seconds
        self.sim_mode = (
            sim_mode
            if sim_mode is not None
            else os.getenv("FACTORYLM_NET_MODE") == "sim"
        )

        logger.info(
            f"TagExtractor initialized - Gateway: {gateway_id}, "
            f"PLC: {plc_ip}, SIM mode: {self.sim_mode}"
        )

    async def extract(self) -> Optional[ExtractionResult]:
        """
        Execute priority waterfall extraction across protocols.

        Attempts each protocol in priority order, returning first successful result.

        Returns:
            ExtractionResult with extracted tags, or None if all protocols fail.
        """
        logger.info(
            f"Starting tag extraction for {self.plc_ip} via waterfall scan"
        )

        for protocol, port in self.PROTOCOL_PRIORITY:
            try:
                logger.debug(f"Attempting {protocol.value} on port {port}")
                result = await self._extract_protocol(protocol, port)

                if result and result.tags:
                    logger.info(
                        f"Successfully extracted {len(result.tags)} tags "
                        f"via {protocol.value}"
                    )
                    return result
                else:
                    logger.debug(f"{protocol.value} returned no tags")

            except asyncio.TimeoutError:
                logger.debug(f"{protocol.value} timeout after {self.timeout}s")
            except Exception as e:
                logger.debug(f"{protocol.value} extraction failed: {e}")

        logger.warning(
            f"All extraction methods failed for {self.plc_ip}"
        )
        return None

    async def _extract_protocol(
        self, protocol: Protocol, port: int
    ) -> Optional[ExtractionResult]:
        """
        Extract tags from a specific protocol with timeout and semaphore.

        Args:
            protocol: Protocol to attempt
            port: Port number for protocol

        Returns:
            ExtractionResult with tags, or None if extraction fails.
        """
        async with self.semaphore:
            try:
                result = await asyncio.wait_for(
                    self._do_extract(protocol, port),
                    timeout=self.timeout,
                )
                return result
            except asyncio.TimeoutError:
                raise
            except Exception as e:
                logger.debug(f"Protocol extraction error: {e}")
                return None

    async def _do_extract(
        self, protocol: Protocol, port: int
    ) -> Optional[ExtractionResult]:
        """
        Perform actual protocol-specific extraction.

        Args:
            protocol: Protocol enum
            port: Port number

        Returns:
            ExtractionResult with tags, or None.
        """
        if self.sim_mode:
            return self._get_simulated_result(protocol)

        # Import readers dynamically to gracefully handle missing dependencies
        if protocol == Protocol.ETHIP:
            from .ethip_reader import EtherNetIPReader
            reader = EtherNetIPReader(self.plc_ip, self.timeout)
            tags = await reader.discover_tags()
            extraction_method = "cip_tag_upload"

        elif protocol == Protocol.OPCUA:
            from .opcua_reader import OpcUaReader
            reader = OpcUaReader(self.plc_ip, self.timeout)
            tags = await reader.discover_tags()
            extraction_method = "browse_tree"

        elif protocol == Protocol.S7:
            logger.debug("S7 protocol not yet implemented")
            return None

        elif protocol == Protocol.MODBUS:
            from .modbus_reader import ModbusReader, sim_brute_force_scan
            loop = asyncio.get_event_loop()

            def _scan():
                reader = ModbusReader(
                    host=self.plc_ip, port=port, template={"coils": {}, "registers": {}}
                )
                found = reader.brute_force_scan(
                    coil_range=(0, 99), register_range=(0, 199), batch_size=10
                )
                reader.disconnect()
                return found

            tag_dicts = await loop.run_in_executor(None, _scan)
            if not tag_dicts:
                return None
            return ExtractionResult(
                gateway_id=self.gateway_id,
                plc_ip=self.plc_ip,
                protocol=protocol.value,
                extraction_method="modbus_brute_force",
                extracted_at=self._get_iso_timestamp(),
                tags=tag_dicts,
            )

        else:
            return None

        if not tags:
            return None

        return ExtractionResult(
            gateway_id=self.gateway_id,
            plc_ip=self.plc_ip,
            protocol=protocol.value,
            extraction_method=extraction_method,
            extracted_at=self._get_iso_timestamp(),
            tags=[tag.to_dict() for tag in tags],
        )

    def _get_simulated_result(self, protocol: Protocol) -> ExtractionResult:
        """
        Generate realistic simulated tag extraction result.

        Args:
            protocol: Protocol being simulated

        Returns:
            ExtractionResult with fake but realistic data.
        """
        sim_data = {
            Protocol.ETHIP: {
                "method": "cip_tag_upload",
                "tags": [
                    Tag(
                        name="Motor_Run",
                        plc_address="Motor_Run",
                        type="BOOL",
                        value=True,
                        named=True,
                        writable=False,
                    ),
                    Tag(
                        name="Motor_Speed",
                        plc_address="Motor_Speed",
                        type="INT",
                        value=1500,
                        named=True,
                        writable=True,
                    ),
                    Tag(
                        name="System_Temperature",
                        plc_address="System_Temperature",
                        type="REAL",
                        value=45.7,
                        named=True,
                        writable=False,
                    ),
                ],
            },
            Protocol.OPCUA: {
                "method": "browse_tree",
                "tags": [
                    Tag(
                        name="Devices/PLC/Motor/Status",
                        plc_address="ns=2;s=Motor.Status",
                        type="Boolean",
                        value=True,
                        named=True,
                        writable=False,
                    ),
                    Tag(
                        name="Devices/PLC/Motor/Speed",
                        plc_address="ns=2;s=Motor.Speed",
                        type="Int16",
                        value=1500,
                        named=True,
                        writable=True,
                    ),
                ],
            },
            Protocol.S7: {
                "method": "snap7_read",
                "tags": [],
            },
            Protocol.MODBUS: {
                "method": "modbus_brute_force",
                "tags": [
                    Tag(name="Conveyor", plc_address="coil:0", type="BOOL", value=True, writable=True),
                    Tag(name="Emitter", plc_address="coil:1", type="BOOL", value=False, writable=True),
                    Tag(name="SensorStart", plc_address="coil:2", type="BOOL", value=False),
                    Tag(name="SensorEnd", plc_address="coil:3", type="BOOL", value=False),
                    Tag(name="item_count", plc_address="hr:100", type="INT", value=247),
                    Tag(name="motor_speed", plc_address="hr:101", type="INT", value=85, writable=True),
                    Tag(name="motor_current", plc_address="hr:102", type="REAL", value=12.5),
                    Tag(name="temperature", plc_address="hr:103", type="REAL", value=48.7),
                    Tag(name="pressure", plc_address="hr:104", type="INT", value=60),
                    Tag(name="error_code", plc_address="hr:105", type="INT", value=0),
                ],
            },
        }

        data = sim_data.get(protocol, {"method": "unknown", "tags": []})

        return ExtractionResult(
            gateway_id=self.gateway_id,
            plc_ip=self.plc_ip,
            protocol=protocol.value,
            extraction_method=data["method"],
            extracted_at=self._get_iso_timestamp(),
            tags=[tag.to_dict() for tag in data["tags"]],
        )

    @staticmethod
    def _get_iso_timestamp() -> str:
        """Get current UTC timestamp in ISO 8601 format."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def extract_tags(
    gateway_id: str,
    plc_ip: str,
    sim_mode: Optional[bool] = None,
) -> Optional[ExtractionResult]:
    """
    Convenience function to extract tags from a PLC.

    Args:
        gateway_id: Gateway identifier
        plc_ip: Target PLC IP address
        sim_mode: Override simulation mode

    Returns:
        ExtractionResult with tags, or None if all protocols fail.
    """
    extractor = TagExtractor(gateway_id, plc_ip, sim_mode=sim_mode)
    return await extractor.extract()


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    async def main():
        result = await extract_tags(
            gateway_id="flm-demo123",
            plc_ip="192.168.1.100",
            sim_mode=True,
        )
        if result:
            print(result.to_json())
        else:
            print("Extraction failed")

    asyncio.run(main())
