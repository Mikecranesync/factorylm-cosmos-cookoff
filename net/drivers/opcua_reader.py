"""
OPC UA protocol reader for industrial device tag discovery.

Uses python-opcua library for recursive tree browsing and tag discovery.
Provides graceful fallback for missing dependencies.
"""

import asyncio
import logging
from typing import List, Optional, Any

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
        description: str = "",
    ):
        self.name = name
        self.address = None
        self.plc_address = plc_address or name
        self.type = type_name
        self.value = value
        self.named = named
        self.writable = writable
        self.description = description


class OpcUaReader:
    """
    OPC UA protocol reader for industrial automation servers.

    Discovers tags via recursive tree browsing and reads current values.
    Supports graceful fallback when opcua library is unavailable.
    """

    def __init__(self, ip_address: str, timeout: float = 0.3, port: int = 4840):
        """
        Initialize OPC UA reader.

        Args:
            ip_address: IP address of OPC UA server
            timeout: Connection timeout in seconds
            port: OPC UA server port (default 4840)
        """
        self.ip_address = ip_address
        self.timeout = timeout
        self.port = port
        self._opcua_available = self._check_opcua()
        self.url = f"opc.tcp://{ip_address}:{port}"

        logger.info(
            f"OpcUaReader initialized - {self.url}, "
            f"opcua: {self._opcua_available}"
        )

    @staticmethod
    def _check_opcua() -> bool:
        """Check if opcua library is available."""
        try:
            import opcua
            return True
        except ImportError:
            logger.debug("opcua library not available")
            return False

    async def discover_tags(self) -> List[Tag]:
        """
        Discover all tags from OPC UA server.

        Recursively browses the address space tree and extracts tag information.

        Returns:
            List of Tag objects with names, types, units, and descriptions.
        """
        if not self._opcua_available:
            logger.warning(
                "opcua library not installed, cannot perform real OPC UA discovery. "
                "Install: pip install opcua"
            )
            return []

        try:
            return await self._discover_real_tags()
        except Exception as e:
            logger.error(f"Tag discovery failed: {e}")
            return []

    async def _discover_real_tags(self) -> List[Tag]:
        """
        Perform real tag discovery using opcua.

        Returns:
            List of discovered tags with current values and metadata.
        """
        loop = asyncio.get_event_loop()

        def discover_in_thread():
            """Execute blocking opcua operations in thread pool."""
            try:
                from opcua import Client

                client = Client(self.url, timeout=self.timeout)
                tags = []

                try:
                    # Connect to server
                    client.connect()
                    logger.debug(f"Connected to OPC UA server: {self.url}")

                    # Get root node and browse recursively
                    root = client.get_root_node()
                    tags = self._browse_node(
                        client, root, "", tags, max_depth=5
                    )

                    logger.info(
                        f"Discovered {len(tags)} tags via OPC UA browse"
                    )
                    return tags

                finally:
                    try:
                        client.disconnect()
                    except Exception as e:
                        logger.debug(f"Disconnect error: {e}")

            except ImportError:
                logger.error("opcua import failed during discovery")
                return []
            except Exception as e:
                logger.error(f"Discovery thread error: {e}")
                return []

        try:
            tags = await asyncio.wait_for(
                loop.run_in_executor(None, discover_in_thread),
                timeout=self.timeout,
            )
            return tags
        except asyncio.TimeoutError:
            logger.warning(f"OPC UA discovery timeout after {self.timeout}s")
            return []

    @staticmethod
    def _browse_node(
        client: "Any",
        node: "Any",
        parent_path: str,
        tags: List[Tag],
        current_depth: int = 0,
        max_depth: int = 5,
    ) -> List[Tag]:
        """
        Recursively browse OPC UA node tree.

        Args:
            client: OPC UA client instance
            node: Current node to browse
            parent_path: Path prefix for tag naming
            tags: List to accumulate discovered tags
            current_depth: Current recursion depth
            max_depth: Maximum recursion depth

        Returns:
            Updated tags list.
        """
        if current_depth >= max_depth:
            return tags

        try:
            # Get node information
            node_class = node.get_node_class()
            node_id = node.nodeid
            browse_name = node.get_browse_name()

            # Build full path
            if browse_name and browse_name.Name:
                node_path = (
                    f"{parent_path}/{browse_name.Name}"
                    if parent_path
                    else browse_name.Name
                )
            else:
                return tags

            # Try to read value and attributes
            try:
                node_value = node.get_value()
            except Exception:
                node_value = None

            try:
                node_type = node.get_data_type_as_variant_type()
            except Exception:
                node_type = "Unknown"

            try:
                node_desc = node.get_description()
                description = (
                    node_desc.Text if node_desc else ""
                )
            except Exception:
                description = ""

            # Add variable nodes as tags
            if str(node_class) == "NodeClass.Variable":
                tag = Tag(
                    name=node_path,
                    plc_address=str(node_id),
                    type_name=str(node_type),
                    value=node_value,
                    named=True,
                    writable=True,  # OPC UA variables are typically writable
                    description=description,
                )
                tags.append(tag)

            # Browse children
            try:
                children = node.get_children()
                for child in children:
                    OpcUaReader._browse_node(
                        client,
                        child,
                        node_path,
                        tags,
                        current_depth + 1,
                        max_depth,
                    )
            except Exception as e:
                logger.debug(f"Failed to browse children of {node_path}: {e}")

        except Exception as e:
            logger.debug(f"Error browsing node: {e}")

        return tags

    async def read_tag(self, tag_address: str) -> Optional[Any]:
        """
        Read a single tag value by OPC UA address.

        Args:
            tag_address: OPC UA node ID (e.g., 'ns=2;s=Motor.Status')

        Returns:
            Current tag value, or None if read fails.
        """
        if not self._opcua_available:
            return None

        try:
            from opcua import Client

            client = Client(self.url, timeout=self.timeout)
            try:
                client.connect()
                node = client.get_node(tag_address)
                value = node.get_value()
                return value
            finally:
                try:
                    client.disconnect()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Failed to read tag {tag_address}: {e}")
            return None


async def main():
    """Example usage of OpcUaReader."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    reader = OpcUaReader("192.168.1.100", timeout=0.3)
    tags = await reader.discover_tags()
    for tag in tags:
        print(
            f"Tag: {tag.name} ({tag.type}) = {tag.value} "
            f"(address={tag.plc_address})"
        )


if __name__ == "__main__":
    asyncio.run(main())
