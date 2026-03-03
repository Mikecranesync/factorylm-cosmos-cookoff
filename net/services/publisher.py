"""
Publisher — aggregates sensor data at 5Hz and pushes to PiCompactCom registers.

Reads from the Poller (PLC tags), optional BeltTachometer, and optional VfdReader,
scales values to unsigned 16-bit integers, and writes them to the CompactCom
holding registers so the PLC can read them via MSG instruction.

Also reads PLC command registers (100-103) and caches them for the API.

Register map (published 0-20):
   0  belt_rpm         x10
   1  belt_speed_pct   x10
   2  belt_status      enum 0-4
   3  belt_offset_px   value + 32768 (signed → unsigned)
   4  vfd_output_hz    x100
   5  vfd_output_amps  x10
   6  vfd_fault_code   direct
   7  motor_running    0/1
   8  motor_speed      0-100
   9  motor_current    x10
  10  conveyor_running 0/1
  11  temperature      x10
  12  pressure         direct
  13  sensor_1         0/1
  14  sensor_2         0/1
  15  e_stop           0/1
  16  fault_alarm      0/1
  17  error_code       direct
  18  ai_confidence    0-100
  19  pi_heartbeat     0-65535 wrapping
  20  source_flags     bitmask: bit0=plc, bit1=vfd, bit2=camera
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


def _clamp(value: int, lo: int = 0, hi: int = 65535) -> int:
    """Clamp an integer to [lo, hi]."""
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _belt_status_to_enum(status) -> int:
    """Convert BeltStatus enum to integer 0-4.

    Lazy import to avoid cv2 dependency at module level.
    Returns 0 if status is not a recognized BeltStatus value.
    """
    try:
        from cosmos.belt_tachometer import BeltStatus
        _MAP = {
            BeltStatus.CALIBRATING: 0,
            BeltStatus.STOPPED: 1,
            BeltStatus.NORMAL: 2,
            BeltStatus.SLOW: 3,
            BeltStatus.MISTRACK: 4,
        }
        return _MAP.get(status, 0)
    except Exception:
        return 0


class Publisher:
    """Background daemon thread aggregating data at 5Hz into CompactCom registers."""

    def __init__(
        self,
        compactcom,
        poller,
        belt_tachometer=None,
        vfd_reader=None,
    ) -> None:
        self._compactcom = compactcom
        self._poller = poller
        self._belt_tachometer = belt_tachometer
        self._vfd_reader = vfd_reader
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._commands_lock = threading.Lock()
        self._commands: dict = {
            "cmd_run": 0,
            "cmd_speed_pct": 0,
            "cmd_mode": 0,
            "cmd_reset_fault": 0,
        }
        self._heartbeat: int = 0

    def start(self) -> None:
        """Spawn the publisher daemon thread."""
        if self.is_running:
            logger.warning("Publisher already running")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._publish_loop, daemon=True)
        self._thread.start()
        logger.info("Publisher started")

    def stop(self) -> None:
        """Stop the publisher thread."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Publisher stopped")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def commands(self) -> dict:
        """Latest PLC command registers (thread-safe copy)."""
        with self._commands_lock:
            return dict(self._commands)

    def set_belt_tachometer(self, tach) -> None:
        """Hot-swap belt tachometer reference (for late camera init)."""
        self._belt_tachometer = tach

    def set_vfd_reader(self, reader) -> None:
        """Hot-swap VFD reader reference."""
        self._vfd_reader = reader

    def _publish_loop(self) -> None:
        """Main loop: aggregate at 5Hz, write to CompactCom, read commands."""
        publish_interval = 0.2  # 5Hz
        consecutive_errors = 0

        while not self._stop.is_set():
            try:
                values = self._aggregate()
                self._compactcom.update_published(values)

                # Read PLC commands
                cmds = self._compactcom.read_commands()
                with self._commands_lock:
                    self._commands = cmds

                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                logger.error("Publisher error (#%d): %s", consecutive_errors, e)
                if consecutive_errors >= 10:
                    logger.critical("Publisher exceeded 10 consecutive errors, backing off 10s")
                    self._stop.wait(10.0)
                    consecutive_errors = 0

            self._stop.wait(publish_interval)

    def _aggregate(self) -> list[int]:
        """Read all sources, scale to uint16, return 21-element list."""
        # Belt tachometer
        belt_rpm = 0
        belt_speed_pct = 0
        belt_status = 0
        belt_offset_px = 32768  # zero offset encoded as midpoint
        camera_connected = False

        tach = self._belt_tachometer
        if tach is not None:
            camera_connected = True
            try:
                belt_rpm = _clamp(int(round(tach.rpm * 10)))
                belt_speed_pct = _clamp(int(round(tach.speed_pct * 10)))
                belt_status = _belt_status_to_enum(tach.status)
                belt_offset_px = _clamp(int(round(tach.offset_px)) + 32768)
            except Exception as e:
                logger.debug("Belt tachometer read error: %s", e)

        # VFD reader
        vfd_output_hz = 0
        vfd_output_amps = 0
        vfd_fault_code = 0
        vfd_connected = False

        reader = self._vfd_reader
        if reader is not None:
            try:
                vfd_data = reader.tick()
                if vfd_data.get("vfd_connected", False):
                    vfd_connected = True
                    raw_hz = vfd_data.get("vfd_output_hz", 0)
                    vfd_output_hz = _clamp(int(round(raw_hz * 100)))
                    raw_amps = vfd_data.get("vfd_output_amps", 0)
                    vfd_output_amps = _clamp(int(round(raw_amps * 10)))
                    vfd_fault_code = _clamp(int(vfd_data.get("vfd_fault_code", 0)))
            except Exception as e:
                logger.debug("VFD reader error: %s", e)

        # PLC tags from poller
        motor_running = 0
        motor_speed = 0
        motor_current = 0
        conveyor_running = 0
        temperature = 0
        pressure = 0
        sensor_1 = 0
        sensor_2 = 0
        e_stop = 0
        fault_alarm = 0
        error_code = 0
        ai_confidence = 0
        plc_connected = False

        tags = self._poller.latest
        if tags is not None:
            plc_connected = True
            motor_running = _clamp(int(bool(tags.get("motor_running", False))))
            motor_speed = _clamp(int(tags.get("motor_speed", 0)), 0, 100)
            motor_current = _clamp(int(round(float(tags.get("motor_current", 0)) * 10)))
            conveyor_running = _clamp(int(bool(tags.get("conveyor_running", False))))
            temperature = _clamp(int(round(float(tags.get("temperature", 0)) * 10)))
            pressure = _clamp(int(tags.get("pressure", 0)))
            sensor_1 = _clamp(int(bool(tags.get("sensor_1", False))))
            sensor_2 = _clamp(int(bool(tags.get("sensor_2", False))))
            e_stop = _clamp(int(bool(tags.get("e_stop", False))))
            fault_alarm = _clamp(int(bool(tags.get("fault_alarm", False))))
            error_code = _clamp(int(tags.get("error_code", 0)))

        # Source flags bitmask
        source_flags = (
            (int(plc_connected) << 0)
            | (int(vfd_connected) << 1)
            | (int(camera_connected) << 2)
        )

        # Heartbeat
        self._heartbeat = (self._heartbeat + 1) % 65536

        return [
            belt_rpm,           # reg 0
            belt_speed_pct,     # reg 1
            belt_status,        # reg 2
            belt_offset_px,     # reg 3
            vfd_output_hz,      # reg 4
            vfd_output_amps,    # reg 5
            vfd_fault_code,     # reg 6
            motor_running,      # reg 7
            motor_speed,        # reg 8
            motor_current,      # reg 9
            conveyor_running,   # reg 10
            temperature,        # reg 11
            pressure,           # reg 12
            sensor_1,           # reg 13
            sensor_2,           # reg 14
            e_stop,             # reg 15
            fault_alarm,        # reg 16
            error_code,         # reg 17
            ai_confidence,      # reg 18
            self._heartbeat,    # reg 19
            source_flags,       # reg 20
        ]
