"""
EtherNet/IP tag source for Micro 820 PLC (CIP native).

Uses pycomm3 LogixDriver with micro800=True to read named tags directly
via CIP instead of Modbus TCP. Returns TagSnapshot objects identical
to ModbusTagSource.

This is *better* than Modbus for Micro 800-series because:
- Named tags instead of raw register offsets
- Auto-discovered tag list
- Works even when Modbus TCP server is disabled on the PLC

Discovered on CHARLIE (2026-03-03): PLC at 169.254.20.53 has
EtherNet/IP on port 44818 but no Modbus TCP on 502.
Product: 2080-LC20-20QBB, fw 14.11, serial d096d30c.

Usage:
    source = EtherNetIPTagSource("169.254.20.53")
    if source.connect():
        snap = source.tick()
        print(snap.to_dict())
"""
from __future__ import annotations

import datetime
import logging

from net.models.tags import ERROR_CODES, TagSnapshot

logger = logging.getLogger(__name__)

# PLC tag name -> (TagSnapshot field, type, scale)
# scale: None = direct, 10 = divide by 10
_TAG_MAP = {
    "motor_running":    ("motor_running",    bool,  None),
    "motor_speed":      ("motor_speed",      int,   None),
    "motor_current":    ("motor_current",    float, 10),
    "temperature":      ("temperature",      float, 10),
    "pressure":         ("pressure",         int,   None),
    "conveyor_running": ("conveyor_running", bool,  None),
    "conveyor_speed":   ("conveyor_speed",   int,   None),
    "sensor_1_active":  ("sensor_1",         bool,  None),
    "sensor_2_active":  ("sensor_2",         bool,  None),
    "e_stop_active":    ("e_stop",           bool,  None),
    "fault_alarm":      ("fault_alarm",      bool,  None),
    "error_code":       ("error_code",       int,   None),
}

# Coil index -> PLC tag name (for reconstructing 18-element coils[])
# Maps coil addresses 0-17 to the PLC tags that correspond to them.
# Gaps (5, 6, 12, 13, 14) have no mapped tag and default to 0.
_COIL_TAG_MAP = {
    0:  "conveyor_running",
    1:  "Emitter",
    2:  "sensor_1_active",
    3:  "sensor_2_active",
    4:  "RunCommand",
    7:  "_IO_EM_DI_00",
    8:  "_IO_EM_DI_01",
    9:  "_IO_EM_DI_02",
    10: "_IO_EM_DI_03",
    11: "_IO_EM_DI_04",
    15: "_IO_EM_DO_00",
    16: "_IO_EM_DO_01",
    17: "_IO_EM_DO_03",
}

# io{} dict keys -> PLC tag name
_IO_TAG_MAP = {
    "conveyor":     "conveyor_running",
    "emitter":      "Emitter",
    "sensor_start": "sensor_1_active",
    "sensor_end":   "sensor_2_active",
    "run_command":  "RunCommand",
    "di_center":    "_IO_EM_DI_00",
    "di_estop_no":  "_IO_EM_DI_01",
    "di_estop_nc":  "_IO_EM_DI_02",
    "di_right":     "_IO_EM_DI_03",
    "di_green_btn": "_IO_EM_DI_04",
    "do_fwd":       "_IO_EM_DO_00",
    "do_rev":       "_IO_EM_DO_01",
    "do_aux":       "_IO_EM_DO_03",
}


class EtherNetIPTagSource:
    """Reads Micro 820 tags via EtherNet/IP (CIP) and returns TagSnapshot."""

    def __init__(self, host: str, port: int = 44818, micro800: bool = True) -> None:
        self.host = host
        self.port = port
        self.micro800 = micro800
        self._plc = None
        self._tag_names: list[str] | None = None

    def connect(self) -> bool:
        """Open a CIP connection and discover tags. Returns True on success."""
        try:
            from pycomm3 import LogixDriver
        except ImportError:
            logger.error("pycomm3 not installed -- pip install pycomm3")
            return False

        try:
            plc = LogixDriver(self.host, micro800=self.micro800)
            plc.open()
            tag_list = plc.get_tag_list()
            self._tag_names = [t["tag_name"] for t in tag_list] if tag_list else []
            self._plc = plc
            logger.info(
                "EtherNetIPTagSource connected to %s (EtherNet/IP), %d tags discovered",
                self.host, len(self._tag_names),
            )
            return True
        except Exception as e:
            logger.warning("EtherNetIPTagSource connection failed to %s: %s", self.host, e)
            self._plc = None
            return False

    @property
    def connected(self) -> bool:
        return self._plc is not None

    def tick(self) -> TagSnapshot:
        """Read all tags and return a TagSnapshot.

        Auto-reconnects if the connection is dead.
        Returns a comms-fault snapshot on read failure.
        """
        if not self.connected:
            if not self.connect():
                return self._error_snapshot("connection failed")

        try:
            # Build the list of tags to read: all mapped tags + coil/IO tags
            tags_to_read = set()
            for plc_tag in _TAG_MAP:
                tags_to_read.add(plc_tag)
            for plc_tag in _COIL_TAG_MAP.values():
                tags_to_read.add(plc_tag)
            for plc_tag in _IO_TAG_MAP.values():
                tags_to_read.add(plc_tag)

            # Filter to only tags that exist on this PLC
            if self._tag_names is not None:
                existing = set(self._tag_names)
                tags_to_read = tags_to_read & existing

            # Bulk read
            results = self._plc.read(*sorted(tags_to_read))

            # pycomm3 returns a single Tag object for single reads,
            # or a list of Tag objects for multiple reads.
            if not isinstance(results, list):
                results = [results]

            # Build tag_name -> value lookup
            tag_values: dict = {}
            for r in results:
                if r.error is None:
                    tag_values[r.tag] = r.value
                else:
                    logger.debug("Tag read error: %s -> %s", r.tag, r.error)

            # Map to TagSnapshot fields
            fields = {}
            for plc_tag, (snap_field, typ, scale) in _TAG_MAP.items():
                raw = tag_values.get(plc_tag)
                if raw is None:
                    fields[snap_field] = typ() if typ != float else 0.0
                elif scale:
                    fields[snap_field] = round(raw / scale, 1)
                elif typ == bool:
                    fields[snap_field] = bool(raw)
                else:
                    fields[snap_field] = typ(raw)

            # Reconstruct 18-element coils[] from individual tags
            coils_int = [0] * 18
            for idx, plc_tag in _COIL_TAG_MAP.items():
                val = tag_values.get(plc_tag)
                coils_int[idx] = int(bool(val)) if val is not None else 0

            # Reconstruct io{} dict
            io = {}
            for io_key, plc_tag in _IO_TAG_MAP.items():
                val = tag_values.get(plc_tag)
                io[io_key] = int(bool(val)) if val is not None else 0

            # E-stop dual-contact validation from raw coil tags
            estop_no = bool(tag_values.get("_IO_EM_DI_01", False))
            estop_nc = bool(tag_values.get("_IO_EM_DI_02", False))
            e_stop_ok = not estop_no and estop_nc

            # Use motor_speed for conveyor_speed if not separately available
            if fields.get("conveyor_speed", 0) == 0 and fields.get("motor_speed", 0) > 0:
                fields["conveyor_speed"] = fields["motor_speed"]

            error_code = fields.get("error_code", 0)

            return TagSnapshot(
                timestamp=datetime.datetime.now(
                    tz=datetime.timezone.utc
                ).isoformat(),
                node_id=f"plc-{self.host}",
                motor_running=fields.get("motor_running", False),
                motor_speed=fields.get("motor_speed", 0),
                motor_current=fields.get("motor_current", 0.0),
                temperature=fields.get("temperature", 0.0),
                pressure=fields.get("pressure", 0),
                conveyor_running=fields.get("conveyor_running", False),
                conveyor_speed=fields.get("conveyor_speed", 0),
                sensor_1=fields.get("sensor_1", False),
                sensor_2=fields.get("sensor_2", False),
                fault_alarm=fields.get("fault_alarm", False),
                e_stop=fields.get("e_stop", False),
                error_code=error_code,
                error_message=ERROR_CODES.get(
                    error_code, f"Unknown error {error_code}"
                ),
                coils=coils_int,
                io=io,
                e_stop_ok=e_stop_ok,
            )

        except Exception as e:
            logger.warning("EtherNetIPTagSource read error: %s", e)
            self._close()
            return self._error_snapshot(str(e))

    def _close(self):
        """Safely close the CIP connection."""
        if self._plc:
            try:
                self._plc.close()
            except Exception:
                pass
            self._plc = None

    def _error_snapshot(self, reason: str) -> TagSnapshot:
        """Return a comms-fault snapshot (error_code=5)."""
        return TagSnapshot(
            timestamp=datetime.datetime.now(
                tz=datetime.timezone.utc
            ).isoformat(),
            node_id=f"plc-{self.host}",
            motor_running=False,
            motor_speed=0,
            motor_current=0.0,
            temperature=0.0,
            pressure=0,
            conveyor_running=False,
            conveyor_speed=0,
            sensor_1=False,
            sensor_2=False,
            fault_alarm=True,
            e_stop=False,
            error_code=5,
            error_message=f"Communication loss: {reason}",
            coils=[0] * 18,
            io={
                "conveyor": 0, "emitter": 0, "sensor_start": 0,
                "sensor_end": 0, "run_command": 0, "di_center": 0,
                "di_estop_no": 0, "di_estop_nc": 0, "di_right": 0,
                "di_green_btn": 0, "do_fwd": 0, "do_rev": 0, "do_aux": 0,
            },
            e_stop_ok=False,
        )
