"""
Background poller — reads PLC tags at 5Hz, writes history at 1Hz.

Respects FACTORYLM_NET_MODE env var:
  - "real" (default): uses ModbusReader against live PLC
  - "sim": uses PLCSimulator for demo/testing without hardware
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class Poller:
    """Background tag poller with SQLite history."""

    def __init__(self, db_path: str = "net.db"):
        self.db_path = db_path
        self.mode = os.environ.get("FACTORYLM_NET_MODE", "real")
        self._reader = None
        self._sim = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest: dict | None = None
        self._lock = threading.Lock()
        self._plc_ip: str | None = None
        self._plc_port: int = 502
        self._template: dict | None = None
        self._custom_names: dict | None = None
        self._init_db()

    @property
    def latest(self) -> dict | None:
        with self._lock:
            return self._latest

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def plc_connected(self) -> bool:
        if self.mode == "sim":
            return self._sim is not None
        return self._reader is not None and self._reader.connected

    def configure(
        self,
        ip: str,
        port: int = 502,
        template: dict | None = None,
        custom_names: dict | None = None,
    ):
        """Set PLC connection parameters. Call before start()."""
        self._plc_ip = ip
        self._plc_port = port
        self._template = template
        self._custom_names = custom_names

    def start(self):
        """Start the polling thread."""
        if self.is_running:
            logger.warning("Poller already running")
            return

        self._init_db()
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Poller started (mode=%s)", self.mode)

    def stop(self):
        """Stop the polling thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        if self._reader:
            self._reader.disconnect()
        logger.info("Poller stopped")

    def _init_db(self):
        """Create all required tables if not exists."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tag_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tags_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plc_configs (
                plc_id TEXT PRIMARY KEY,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL DEFAULT 502,
                brand TEXT,
                template_name TEXT,
                tags_json TEXT,
                custom_names_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gateway_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tag_names (
                plc_id TEXT NOT NULL,
                raw_name TEXT NOT NULL,
                human_name TEXT NOT NULL,
                PRIMARY KEY (plc_id, raw_name)
            )
        """)
        conn.commit()
        conn.close()

    def get_gateway_id(self) -> str:
        """Get gateway_id from gateway_config table."""
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT value FROM gateway_config WHERE key = 'gateway_id'"
        ).fetchone()
        conn.close()
        return row[0] if row else ""

    def save_gateway_config(self, key: str, value: str):
        """Save a key-value pair to gateway_config."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO gateway_config (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()
        conn.close()

    def save_tag_name(self, plc_id: str, raw_name: str, human_name: str):
        """Save a human-readable name mapping for a tag."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO tag_names (plc_id, raw_name, human_name) VALUES (?, ?, ?)",
            (plc_id, raw_name, human_name),
        )
        conn.commit()
        conn.close()

    def get_tag_names(self, plc_id: str) -> dict[str, str]:
        """Get all human name mappings for a PLC."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT raw_name, human_name FROM tag_names WHERE plc_id = ?",
            (plc_id,),
        ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}

    def _init_source(self):
        """Initialize Modbus reader or simulator based on mode."""
        if self.mode == "sim":
            from net.sim.plc_simulator import PLCSimulator
            self._sim = PLCSimulator(
                node_id="sim-net",
                db_path=None,
            )
            # Override _store_snapshot to no-op (we handle history ourselves)
            self._sim._store_snapshot = lambda snap: None
            logger.info("Poller using PLCSimulator (sim mode)")
        else:
            if not self._plc_ip:
                logger.warning("No PLC IP configured — poller idle")
                return
            if not self._template:
                # Default to micro820 template
                from net.drivers.discovery import load_template
                self._template = load_template("micro820")

            from net.drivers.modbus_reader import ModbusReader
            self._reader = ModbusReader(
                host=self._plc_ip,
                port=self._plc_port,
                template=self._template,
                custom_names=self._custom_names,
            )
            logger.info("Poller using ModbusReader → %s:%d", self._plc_ip, self._plc_port)

    def _poll_loop(self):
        """Main loop: 5Hz read, 1Hz history write."""
        self._init_source()

        poll_interval = 0.2  # 5Hz
        history_interval = 1.0  # 1Hz
        last_history_write = 0.0

        while not self._stop.is_set():
            tags = self._read_once()
            if tags:
                with self._lock:
                    self._latest = tags

                # Write to history at 1Hz
                now = time.monotonic()
                if now - last_history_write >= history_interval:
                    self._write_history(tags)
                    last_history_write = now

            self._stop.wait(poll_interval)

    def _read_once(self) -> dict | None:
        """Single read from appropriate source."""
        if self.mode == "sim" and self._sim:
            snap = self._sim.tick()
            return snap.to_dict()
        elif self._reader:
            return self._reader.read_tags()
        return None

    def _write_history(self, tags: dict):
        """Append a snapshot to tag_history."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                "INSERT INTO tag_history (timestamp, tags_json) VALUES (?, ?)",
                (
                    tags.get("timestamp", datetime.datetime.now(
                        tz=datetime.timezone.utc
                    ).isoformat()),
                    json.dumps(tags),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("History write failed: %s", e)

    def save_plc_config(
        self,
        plc_id: str,
        ip: str,
        port: int,
        brand: str,
        template_name: str,
        tags_json: str,
        custom_names_json: str | None = None,
    ):
        """Save PLC configuration to SQLite."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """INSERT OR REPLACE INTO plc_configs
               (plc_id, ip, port, brand, template_name, tags_json, custom_names_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                plc_id, ip, port, brand, template_name, tags_json,
                custom_names_json,
                datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        conn.close()
        logger.info("PLC config saved: %s (%s:%d)", plc_id, ip, port)
