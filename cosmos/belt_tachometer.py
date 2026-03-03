"""
Belt Tachometer — vision-based RPM and tracking for conveyor belts.

Uses a bright orange tape marker on the belt. The camera watches the tape
cross a virtual centerline to calculate RPM, speed percentage, and lateral
drift (mistracking). Buffers 5 seconds of video for AI diagnosis on fault.

All tuning knobs are environment variables so a tech can adjust them
without touching code.
"""
from __future__ import annotations

import enum
import os
import time
from collections import deque
from typing import Any

import cv2
import numpy as np


# ---------------------------------------------------------------------------
# Tuning knobs (environment variables)
# ---------------------------------------------------------------------------
def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, default))


ORANGE_H_LOW = _env_int("ORANGE_H_LOW", 5)
ORANGE_H_HIGH = _env_int("ORANGE_H_HIGH", 25)
ORANGE_S_LOW = _env_int("ORANGE_S_LOW", 150)
ORANGE_V_LOW = _env_int("ORANGE_V_LOW", 150)

CROSSING_DEBOUNCE_SEC = _env_float("CROSSING_DEBOUNCE_SEC", 0.1)
SLOW_THRESHOLD_PCT = _env_float("SLOW_THRESHOLD_PCT", 80.0)
MISTRACK_THRESHOLD_PX = _env_int("MISTRACK_THRESHOLD_PX", 50)
STOPPED_TIMEOUT_SEC = _env_float("STOPPED_TIMEOUT_SEC", 3.0)
CLIP_BUFFER_FRAMES = _env_int("CLIP_BUFFER_FRAMES", 150)


class BeltStatus(str, enum.Enum):
    NORMAL = "NORMAL"
    SLOW = "SLOW"
    MISTRACK = "MISTRACK"
    STOPPED = "STOPPED"
    CALIBRATING = "CALIBRATING"


class BeltTachometer:
    """Vision-based belt speed tracker using an orange tape marker."""

    def __init__(self) -> None:
        # Crossing detection state
        self._crossing_times: deque[float] = deque(maxlen=20)
        self._last_crossing_time: float = -999.0  # Allow first crossing to pass debounce
        self._tape_was_above: bool | None = None  # None = not yet calibrated

        # Frame geometry (set on first frame)
        self._center_initialized: bool = False
        self._center_x: int = 0  # Pixel X center of frame
        self._center_y: int = 0  # Pixel Y center (the virtual line)

        # Calibration
        self._calibrated: bool = False
        self._baseline_rpm: float = 0.0
        self._calibration_crossings: int = 0
        self._calibration_start: float = 0.0
        self._CALIBRATION_MIN_CROSSINGS = 5

        # Current readings
        self.rpm: float = 0.0
        self.speed_pct: float = 0.0
        self.offset_px: int = 0
        self.status: BeltStatus = BeltStatus.CALIBRATING
        self.tape_detected: bool = False
        self.tape_contour: np.ndarray | None = None
        self.tape_center: tuple[int, int] | None = None

        # Video clip buffer (ring buffer of raw frames)
        self._frame_buffer: deque[np.ndarray] = deque(maxlen=CLIP_BUFFER_FRAMES)
        self._frame_times: deque[float] = deque(maxlen=CLIP_BUFFER_FRAMES)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_frame(self, frame: np.ndarray, timestamp: float | None = None) -> dict[str, Any]:
        """Process a single video frame. Returns current belt readings.

        Args:
            frame: BGR image from OpenCV VideoCapture.
            timestamp: Wall-clock time (defaults to time.time()).

        Returns:
            Dict with keys: rpm, speed_pct, offset_px, status, tape_detected
        """
        now = timestamp if timestamp is not None else time.time()

        # Set frame center on first frame (independent of calibration)
        if not self._center_initialized:
            h, w = frame.shape[:2]
            self._center_x = w // 2
            self._center_y = h // 2
            self._center_initialized = True

        if not self._calibrated:
            if self._calibration_start == 0.0:
                self._calibration_start = now

        # Buffer frame for clip export
        self._frame_buffer.append(frame.copy())
        self._frame_times.append(now)

        # Detect orange tape
        mask = self._detect_orange(frame)
        contour, center = self._find_tape(mask)

        self.tape_detected = contour is not None
        self.tape_contour = contour
        self.tape_center = center

        if center is not None:
            tape_y = center[1]
            tape_x = center[0]

            # Track lateral offset from frame center
            self.offset_px = abs(tape_x - self._center_x)

            # Crossing detection: tape crosses the horizontal centerline
            tape_is_above = tape_y < self._center_y
            if self._tape_was_above is not None and tape_is_above != self._tape_was_above:
                # Crossed the line — apply debounce
                if (now - self._last_crossing_time) >= CROSSING_DEBOUNCE_SEC:
                    self._crossing_times.append(now)
                    self._last_crossing_time = now

                    # Calibration phase
                    if not self._calibrated:
                        self._calibration_crossings += 1
                        if self._calibration_crossings >= self._CALIBRATION_MIN_CROSSINGS:
                            self._finish_calibration()

            self._tape_was_above = tape_is_above

        # Calculate RPM from recent crossings
        self.rpm = self._calculate_rpm(now)

        # Calculate speed percentage (relative to baseline)
        if self._calibrated and self._baseline_rpm > 0:
            self.speed_pct = (self.rpm / self._baseline_rpm) * 100.0
        elif self.rpm > 0:
            self.speed_pct = 100.0  # No baseline yet, assume normal
        else:
            self.speed_pct = 0.0

        # Determine status
        self.status = self._determine_status(now)

        return {
            "rpm": round(self.rpm, 1),
            "speed_pct": round(self.speed_pct, 1),
            "offset_px": self.offset_px,
            "status": self.status.value,
            "tape_detected": self.tape_detected,
        }

    def annotate_frame(self, frame: np.ndarray) -> np.ndarray:
        """Draw tachometer overlay on a frame. Returns annotated copy."""
        out = frame.copy()
        h, w = out.shape[:2]

        # Draw centerline
        cv2.line(out, (0, self._center_y), (w, self._center_y), (0, 255, 255), 1)

        # Draw tape contour
        if self.tape_contour is not None:
            cv2.drawContours(out, [self.tape_contour], -1, (0, 165, 255), 2)

        # Draw tape center dot
        if self.tape_center is not None:
            cv2.circle(out, self.tape_center, 5, (0, 0, 255), -1)

        # Status color
        color_map = {
            BeltStatus.NORMAL: (0, 200, 0),
            BeltStatus.SLOW: (0, 200, 255),
            BeltStatus.MISTRACK: (0, 100, 255),
            BeltStatus.STOPPED: (0, 0, 255),
            BeltStatus.CALIBRATING: (200, 200, 0),
        }
        color = color_map.get(self.status, (200, 200, 200))

        # Text overlay
        label = f"Belt: {self.status.value} | RPM: {self.rpm:.1f} | Offset: {self.offset_px}px"
        cv2.putText(out, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        if self._calibrated:
            speed_label = f"Speed: {self.speed_pct:.0f}%"
            cv2.putText(out, speed_label, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        return out

    def get_clip_bytes(self, fps: float = 30.0) -> bytes | None:
        """Export the buffered frames as an MP4 video in memory.

        Returns MP4 bytes or None if buffer is empty.
        """
        if len(self._frame_buffer) < 2:
            return None

        frames = list(self._frame_buffer)
        h, w = frames[0].shape[:2]

        # Write to temp file — OpenCV VideoWriter needs a path
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp_path = tmp.name
        tmp.close()

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(tmp_path, fourcc, fps, (w, h))

        for f in frames:
            writer.write(f)
        writer.release()

        try:
            with open(tmp_path, "rb") as fh:
                data = fh.read()
            return data if len(data) > 0 else None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def set_baseline_rpm(self, rpm: float) -> None:
        """Manually set the baseline RPM for speed percentage calculation."""
        self._baseline_rpm = rpm
        self._calibrated = True

    # ------------------------------------------------------------------
    # Internal methods
    # ------------------------------------------------------------------

    def _detect_orange(self, frame: np.ndarray) -> np.ndarray:
        """Convert to HSV and threshold for orange tape."""
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        lower = np.array([ORANGE_H_LOW, ORANGE_S_LOW, ORANGE_V_LOW])
        upper = np.array([ORANGE_H_HIGH, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)

        # Clean up noise
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        return mask

    def _find_tape(self, mask: np.ndarray) -> tuple[np.ndarray | None, tuple[int, int] | None]:
        """Find the largest orange contour (the tape) and its center."""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if not contours:
            return None, None

        # Take the largest contour by area
        biggest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(biggest)

        # Minimum area threshold to filter noise (0.1% of frame)
        h, w = mask.shape[:2]
        min_area = (h * w) * 0.001
        if area < min_area:
            return None, None

        # Compute centroid
        M = cv2.moments(biggest)
        if M["m00"] == 0:
            return None, None

        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        return biggest, (cx, cy)

    def _calculate_rpm(self, now: float) -> float:
        """Calculate RPM from recent crossing timestamps.

        Each full revolution = 2 crossings (tape crosses centerline
        going down, then coming back up). We use pairs of crossings
        to compute revolution time.
        """
        # Need at least 2 crossings to compute a rate
        if len(self._crossing_times) < 2:
            return 0.0

        # Use crossings within the last 10 seconds for a rolling average
        recent = [t for t in self._crossing_times if (now - t) <= 10.0]
        if len(recent) < 2:
            return 0.0

        # Time span of the recent crossings
        span = recent[-1] - recent[0]
        if span <= 0:
            return 0.0

        # Number of half-revolutions = (number of crossings - 1)
        # Each pair of crossings = 1 full revolution
        half_revs = len(recent) - 1
        revolutions = half_revs / 2.0

        # RPM = revolutions / span_in_minutes
        rpm = (revolutions / span) * 60.0
        return rpm

    def _determine_status(self, now: float) -> BeltStatus:
        """Determine overall belt status from current readings."""
        if not self._calibrated:
            return BeltStatus.CALIBRATING

        # Check stopped first (highest priority)
        time_since_last = now - self._last_crossing_time if self._last_crossing_time > 0 else float("inf")
        if time_since_last > STOPPED_TIMEOUT_SEC and self.rpm < 1.0:
            return BeltStatus.STOPPED

        # Check mistracking
        if self.offset_px > MISTRACK_THRESHOLD_PX:
            return BeltStatus.MISTRACK

        # Check slow
        if self._baseline_rpm > 0 and self.speed_pct < SLOW_THRESHOLD_PCT:
            return BeltStatus.SLOW

        return BeltStatus.NORMAL

    def _finish_calibration(self) -> None:
        """Complete calibration using collected crossing data."""
        if len(self._crossing_times) < 2:
            return

        now = self._crossing_times[-1]
        span = now - self._crossing_times[0]
        if span <= 0:
            return

        half_revs = len(self._crossing_times) - 1
        revolutions = half_revs / 2.0
        self._baseline_rpm = (revolutions / span) * 60.0
        self._calibrated = True
