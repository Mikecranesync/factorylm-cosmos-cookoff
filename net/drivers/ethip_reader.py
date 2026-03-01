"""
EtherNet/IP protocol reader for industrial PLC tag discovery.

Uses Rockwell Automation pycomm3 library for CIP tag upload and value reading.
Provides graceful fallback for missing dependencies and simulation mode support.
"""

import asyncio
import logging
from typing import List, Optional, Any
import os

logger = logging.getLogger(__name__)


class Tag:
    """Simple tag data class."""

    def __init__(
        self,
        name: str,
        plc_address: str = "",
        type_name: str = "UNKNOWN",
        value: Any = None,
        named: bool = True,
        writable: bool = False,
    ):
        self.name = name
        self.address = None
        self.plc_address = plc_address or name
        self.type = type_name
        self.value = value
        self.named = named
        self.writable = writable


class EtherNetIPReader:
    """
    EtherNet/IP protocol reader for Allen-Bradley PLCs.

    Discovers tags via CIP tag upload and reads current values.
    Supports graceful fallback when pycomm3 library is unavailable.
    """

    def __init__(self, ip_address: str, timeout: float = 0.3):
        """
        Initialize EtherNet/IP reader.

        Args:
            ip_address: IP address of target PLC
            timeout: Connection timeout in seconds
        """
        self.ip_address = ip_address
        self.timeout = timeout
        self.sim_mode = os.getenv("FACTORYLM_NET_MODE") == "sim"
        self._driver = None
        self._pycomm3_available = self._check_pycomm3()

        logger.info(
            f"EtherNetIPReader initialized - {ip_address}, "
            f"pycomm3: {self._pycomm3_available}, sim: {self.sim_mode}"
        )

    @staticmethod
    def _check_pycomm3() -> bool:
        """Check if pycomm3 library is available."""
        try:
            import pycomm3
            return True
        except ImportError:
            logger.debug("pycomm3 library not available")
            return False

    async def discover_tags(self) -> List[Tag]:
        """
        Discover all tags from EtherNet/IP controller.

        Returns:
            List of Tag objects with names, addresses, types, and values.
        """
        if self.sim_mode:
            return self._get_simulated_tags()

        if not self._pycomm3_available:
            logger.warning(
                "pycomm3 not installed, cannot perform real EtherNet/IP discovery. "
                "Install: pip install pycomm3"
            )
            return []

        try:
            return await self._discover_real_tags()
        except Exception as e:
            logger.error(f"Tag discovery failed: {e}")
            return []

    async def _discover_real_tags(self) -> List[Tag]:
        """
        Perform real tag discovery using pycomm3.

        Returns:
            List of discovered tags with current values.
        """
        loop = asyncio.get_event_loop()

        def discover_in_thread():
            """Execute blocking pycomm3 operations in thread pool."""
            try:
                from pycomm3 import LogixDriver

                driver = LogixDriver(self.ip_address, timeout=self.timeout)
                tags = []

                try:
                    # Get tag list from controller
                    tag_list = driver.get_tag_list()

                    if not tag_list:
                        logger.debug("No tags found in tag list")
                        return tags

                    # Extract tag names and types
                    for tag_info in tag_list:
                        tag_name = tag_info.get("name", "")
                        tag_type = tag_info.get("type", "UNKNOWN")

                        if not tag_name:
                            continue

                        # Read tag value
                        try:
                            value = driver.read(tag_name)
                            if isinstance(value, tuple) and len(value) >= 2:
                                # pycomm3 returns (value, type_info)
                                tag_value = value[0]
                                tag_type = value[1] or tag_type
                            else:
                                tag_value = value
                        except Exception as e:
                            logger.debug(
                                f"Failed to read tag {tag_name}: {e}"
                            )
                            tag_value = None

                        # Determine if tag is writable
                        is_writable = not tag_info.get("read_only", False)

                        tag = Tag(
                            name=tag_name,
                            plc_address=tag_name,
                            type_name=str(tag_type),
                            value=tag_value,
                            named=True,
                            writable=is_writable,
                        )
                        tags.append(tag)

                    logger.info(f"Discovered {len(tags)} tags via CIP upload")
                    return tags

                finally:
                    driver.close()

            except ImportError:
                logger.error("pycomm3 import failed during discovery")
                return []
            except Exception as e:
                logger.error(f"Discovery thread error: {e}")
                return []

        try:
            # Run blocking operations in thread pool with timeout
            tags = await asyncio.wait_for(
                loop.run_in_executor(None, discover_in_thread),
                timeout=self.timeout,
            )
            return tags
        except asyncio.TimeoutError:
            logger.warning(
                f"EtherNet/IP discovery timeout after {self.timeout}s"
            )
            return []

    def _get_simulated_tags(self) -> List[Tag]:
        """
        Return simulated tag data for testing.

        Returns:
            List of realistic fake tags.
        """
        return [
            Tag(
                name="Motor_Run",
                plc_address="Motor_Run",
                type_name="BOOL",
                value=True,
                named=True,
                writable=False,
            ),
            Tag(
                name="Motor_Speed",
                plc_address="Motor_Speed",
                type_name="INT",
                value=1500,
                named=True,
                writable=True,
            ),
            Tag(
                name="Motor_Error",
                plc_address="Motor_Error",
                type_name="DINT",
                value=0,
                named=True,
                writable=False,
            ),
            Tag(
                name="System_Temperature",
                plc_address="System_Temperature",
                type_name="REAL",
                value=45.7,
                named=True,
                writable=False,
            ),
            Tag(
                name="Production_Count",
                plc_address="Production_Count",
                type_name="LINT",
                value=12547,
                named=True,
                writable=False,
            ),
        ]

    async def read_tag(self, tag_name: str) -> Optional[Any]:
        """
        Read a single tag value.

        Args:
            tag_name: Name of tag to read

        Returns:
            Current tag value, or None if read fails.
        """
        if self.sim_mode:
            # Return simulated value
            sim_tags = {tag.name: tag.value for tag in self._get_simulated_tags()}
            return sim_tags.get(tag_name)

        if not self._pycomm3_available:
            return None

        try:
            from pycomm3 import LogixDriver

            driver = LogixDriver(self.ip_address, timeout=self.timeout)
            try:
                result = driver.read(tag_name)
                if isinstance(result, tuple):
                    return result[0]
                return result
            finally:
                driver.close()

        except Exception as e:
            logger.error(f"Failed to read tag {tag_name}: {e}")
            return None


async def main():
    """Example usage of EtherNetIPReader."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    reader = EtherNetIPReader("192.168.1.100", timeout=0.3)
    reader.sim_mode = True  # Force simulation mode

    tags = await reader.discover_tags()
    for tag in tags:
        print(
            f"Tag: {tag.name} ({tag.type}) = {tag.value} "
            f"(writable={tag.writable})"
        )


if __name__ == "__main__":
    asyncio.run(main())
