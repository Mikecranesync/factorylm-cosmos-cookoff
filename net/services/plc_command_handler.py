"""
PLC Command Handler — watches CompactCom command registers for PLC writes.

The Micro820 PLC writes commands to Pi registers 100-103 via MSG instruction.
This handler polls those registers at 5Hz, detects state changes (rising edges),
logs command events, and caches a command history for the API.

Registers watched:
  100: cmd_run        (0=stop, 1=run)
  101: cmd_speed_pct  (x10, so 600 = 60.0%)
  102: cmd_mode       (0=manual, 1=auto, 2=maintenance)
  103: cmd_reset_fault (1=reset, auto-clears after ack)
"""
from __future__ import annotations

import collections
import datetime
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MODE_NAMES = {0: "manual", 1: "auto", 2: "maintenance"}
_MAX_HISTORY = 50  # Keep last N command events


class PLCCommandHandler:
    """Watches PiCompactCom command registers for PLC writes and dispatches actions."""

    def __init__(self, compactcom, publisher) -> None:
        self._compactcom = compactcom
        self._publisher = publisher
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._prev_commands: Dict[str, int] = {
            "cmd_run": 0,
            "cmd_speed_pct": 0,
            "cmd_mode": 0,
            "cmd_reset_fault": 0,
        }
        self._history: collections.deque = collections.deque(maxlen=_MAX_HISTORY)
        self._last_command: Optional[Dict[str, Any]] = None

    def start(self) -> None:
        """Start the command watcher thread."""
        if self.is_running:
            logger.warning("PLCCommandHandler already running")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info("PLCCommandHandler started")

    def stop(self) -> None:
        """Stop the command watcher thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("PLCCommandHandler stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def last_command(self) -> Optional[Dict[str, Any]]:
        """Last command received, with timestamp."""
        with self._lock:
            return self._last_command

    @property
    def history(self) -> List[Dict[str, Any]]:
        """Recent command history (newest first)."""
        with self._lock:
            return list(self._history)

    @property
    def current_state(self) -> Dict[str, Any]:
        """Current decoded command state."""
        with self._lock:
            raw = dict(self._prev_commands)
        return {
            "cmd_run": raw["cmd_run"],
            "cmd_speed_pct": round(raw["cmd_speed_pct"] / 10.0, 1),
            "cmd_mode": _MODE_NAMES.get(raw["cmd_mode"], f"unknown({raw['cmd_mode']})"),
            "cmd_reset_fault": raw["cmd_reset_fault"],
        }

    def _watch_loop(self) -> None:
        """Main loop: read commands at 5Hz, detect changes, dispatch events."""
        poll_interval = 0.2
        consecutive_errors = 0

        while not self._stop.is_set():
            try:
                cmds = self._compactcom.read_commands()
                self._detect_changes(cmds)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.error("PLCCommandHandler error (#%d): %s", consecutive_errors, e)
                if consecutive_errors >= 10:
                    self._stop.wait(10.0)
                    consecutive_errors = 0

            self._stop.wait(poll_interval)

    def _detect_changes(self, cmds: Dict[str, int]) -> None:
        """Compare current commands with previous state and fire events."""
        with self._lock:
            prev = self._prev_commands

            # cmd_run change
            if cmds["cmd_run"] != prev["cmd_run"]:
                self._on_run_change(cmds["cmd_run"])

            # cmd_speed_pct change
            if cmds["cmd_speed_pct"] != prev["cmd_speed_pct"]:
                self._record_event(
                    "cmd_speed_pct",
                    cmds["cmd_speed_pct"],
                    f"{cmds['cmd_speed_pct'] / 10.0:.1f}%",
                )

            # cmd_mode change
            if cmds["cmd_mode"] != prev["cmd_mode"]:
                self._on_mode_change(cmds["cmd_mode"])

            # cmd_reset_fault rising edge only (0 -> 1)
            if cmds["cmd_reset_fault"] == 1 and prev["cmd_reset_fault"] == 0:
                self._on_fault_reset()

            self._prev_commands = dict(cmds)

    def _on_run_change(self, new_val: int) -> None:
        decoded = "RUN" if new_val == 1 else "STOP"
        logger.info("PLC commanded: %s", decoded)
        self._record_event("cmd_run", new_val, decoded)

    def _on_fault_reset(self) -> None:
        logger.info("PLC commanded fault reset")
        self._record_event("cmd_reset_fault", 1, "RESET")

    def _on_mode_change(self, new_mode: int) -> None:
        name = _MODE_NAMES.get(new_mode, f"unknown({new_mode})")
        logger.info("PLC mode change: %s", name)
        self._record_event("cmd_mode", new_mode, name)

    def _record_event(self, cmd_type: str, value: int, decoded: str) -> None:
        """Record a command event (must be called under self._lock)."""
        event = {
            "timestamp": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            "type": cmd_type,
            "value": value,
            "decoded": decoded,
        }
        self._history.appendleft(event)
        self._last_command = event
