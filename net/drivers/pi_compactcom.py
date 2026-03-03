"""
Pi CompactCom — Modbus TCP Server exposing processed data to the PLC.

The Pi acts as a Modbus TCP server so the Micro 820 PLC can read
belt RPM, AI diagnosis, VFD status, and a watchdog heartbeat using
a standard MSG instruction — identical to reading an HMS CompactCom.

Register map (holding registers):
  Published 0-9   (Pi → PLC, PLC reads)
  Commands 100-103 (PLC → Pi, PLC writes)

Usage:
    cc = PiCompactCom(port=5020)
    cc.start()
    cc.update_published([305, 500, 1, 32768, 0, 0, 0, 0, 0, 42])
    cmds = cc.read_commands()
    cc.stop()
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class PiCompactCom:
    """Wraps a pymodbus ModbusTcpServer in a daemon thread."""

    def __init__(self, port: int = 5020, host: str = "0.0.0.0") -> None:
        self.port = port
        self.host = host
        self._lock = threading.Lock()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._context = None

    def start(self) -> None:
        """Spawn the Modbus TCP server in a daemon thread.

        Blocks until the server is listening (up to 5s).
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("PiCompactCom already running")
            return

        self._started.clear()
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

        if not self._started.wait(timeout=5.0):
            logger.error("PiCompactCom failed to start within 5s")

    def stop(self) -> None:
        """Shutdown the Modbus TCP server."""
        try:
            from pymodbus.server import ServerStop
            ServerStop()
        except Exception:
            pass
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._context = None
        logger.info("PiCompactCom stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def update_published(self, values: list) -> None:
        """Write 10 integers to holding registers 0-9 (thread-safe).

        Raises ValueError if not exactly 10 values.
        """
        if len(values) != 10:
            raise ValueError(f"Expected 10 values, got {len(values)}")
        with self._lock:
            if self._context is not None:
                self._context[0].setValues(3, 0, values)

    def read_commands(self) -> dict:
        """Read PLC command registers 100-103 as a named dict (thread-safe)."""
        with self._lock:
            if self._context is None:
                return {"cmd_run": 0, "cmd_speed_pct": 0, "cmd_mode": 0, "cmd_reset_fault": 0}
            raw = self._context[0].getValues(3, 100, count=4)
        return {
            "cmd_run": raw[0],
            "cmd_speed_pct": raw[1],
            "cmd_mode": raw[2],
            "cmd_reset_fault": raw[3],
        }

    def read_published(self) -> list:
        """Read holding registers 0-9 for API/debug (thread-safe)."""
        with self._lock:
            if self._context is None:
                return [0] * 10
            return list(self._context[0].getValues(3, 0, count=10))

    def _run_server(self) -> None:
        """Entry point for the server daemon thread.

        Uses pymodbus 3.x StartTcpServer which calls asyncio.run()
        internally — this must be the only event loop in this thread.
        """
        from pymodbus.datastore import (
            ModbusSequentialDataBlock,
            ModbusServerContext,
            ModbusSlaveContext,
        )
        from pymodbus.server import StartTcpServer

        # 200 holding registers (0-199), initialized to zero
        store = ModbusSlaveContext(
            hr=ModbusSequentialDataBlock(0, [0] * 200),
        )
        context = ModbusServerContext(slaves=store, single=True)

        with self._lock:
            self._context = context

        logger.info("PiCompactCom starting on %s:%d", self.host, self.port)

        try:
            # StartTcpServer is blocking — it calls asyncio.run() internally.
            # Signal _started just before entering the blocking call; the server
            # binds synchronously inside asyncio.run() so it will be listening
            # by the time any client connects (they retry on connection refused).
            self._started.set()
            StartTcpServer(
                context=context,
                address=(self.host, self.port),
            )
        except Exception as e:
            logger.error("PiCompactCom server error: %s", e)
