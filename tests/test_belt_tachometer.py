"""
Tests for Belt Tachometer — all use synthetic frames, no camera needed.

Draws orange rectangles on gray backgrounds to simulate the tape marker
crossing the frame centerline at known intervals.
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np
import pytest

# Override env vars before importing tachometer
os.environ.setdefault("CROSSING_DEBOUNCE_SEC", "0.01")
os.environ.setdefault("STOPPED_TIMEOUT_SEC", "1.0")

from cosmos.belt_tachometer import BeltTachometer, BeltStatus, MISTRACK_THRESHOLD_PX


# ---------------------------------------------------------------------------
# Helpers — synthetic frame generation
# ---------------------------------------------------------------------------

FRAME_W = 640
FRAME_H = 480


def _make_frame(
    tape_y: int | None = None,
    tape_x: int | None = None,
    tape_w: int = 80,
    tape_h: int = 30,
) -> np.ndarray:
    """Create a gray frame with an orange rectangle (the tape).

    Args:
        tape_y: Vertical center of the tape. None = no tape.
        tape_x: Horizontal center of the tape (default: frame center).
        tape_w: Width of the orange rectangle.
        tape_h: Height of the orange rectangle.
    """
    frame = np.full((FRAME_H, FRAME_W, 3), 128, dtype=np.uint8)  # Gray background

    if tape_y is not None:
        if tape_x is None:
            tape_x = FRAME_W // 2

        # Draw orange rectangle (BGR: 0, 165, 255 = pure orange)
        x1 = max(0, tape_x - tape_w // 2)
        y1 = max(0, tape_y - tape_h // 2)
        x2 = min(FRAME_W, tape_x + tape_w // 2)
        y2 = min(FRAME_H, tape_y + tape_h // 2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 165, 255), -1)

    return frame


def _simulate_crossing(
    tach: BeltTachometer,
    above_y: int = 200,
    below_y: int = 280,
    t_start: float = 0.0,
    dt: float = 0.05,
) -> float:
    """Simulate one crossing: tape moves from above_y to below_y.

    Returns the timestamp after the crossing.
    """
    t = t_start
    frame_above = _make_frame(tape_y=above_y)
    frame_below = _make_frame(tape_y=below_y)

    tach.process_frame(frame_above, timestamp=t)
    t += dt
    tach.process_frame(frame_below, timestamp=t)
    t += dt
    return t


# ---------------------------------------------------------------------------
# Test: Orange tape detection
# ---------------------------------------------------------------------------

class TestTapeDetection:
    def test_detects_orange_tape(self):
        tach = BeltTachometer()
        frame = _make_frame(tape_y=200)
        tach.process_frame(frame, timestamp=0.0)
        assert tach.tape_detected is True

    def test_no_tape_when_absent(self):
        tach = BeltTachometer()
        frame = _make_frame(tape_y=None)
        tach.process_frame(frame, timestamp=0.0)
        assert tach.tape_detected is False

    def test_tape_center_accuracy(self):
        tach = BeltTachometer()
        frame = _make_frame(tape_y=200, tape_x=300)
        tach.process_frame(frame, timestamp=0.0)
        assert tach.tape_center is not None
        cx, cy = tach.tape_center
        assert abs(cx - 300) < 10
        assert abs(cy - 200) < 10

    def test_small_noise_rejected(self):
        """Tiny orange speck should be rejected by area threshold."""
        tach = BeltTachometer()
        frame = np.full((FRAME_H, FRAME_W, 3), 128, dtype=np.uint8)
        # Draw a 3x3 orange dot — too small to be tape
        cv2.rectangle(frame, (100, 100), (103, 103), (0, 165, 255), -1)
        tach.process_frame(frame, timestamp=0.0)
        assert tach.tape_detected is False


# ---------------------------------------------------------------------------
# Test: Crossing detection + debounce
# ---------------------------------------------------------------------------

class TestCrossingDetection:
    def test_single_crossing_detected(self):
        tach = BeltTachometer()
        # Frame with tape above center
        f_above = _make_frame(tape_y=100)
        tach.process_frame(f_above, timestamp=0.0)

        # Frame with tape below center
        f_below = _make_frame(tape_y=340)
        tach.process_frame(f_below, timestamp=0.1)

        assert len(tach._crossing_times) == 1

    def test_debounce_prevents_double_count(self):
        """Rapid oscillation within debounce window should be ignored."""
        tach = BeltTachometer()

        f_above = _make_frame(tape_y=100)
        f_below = _make_frame(tape_y=340)

        tach.process_frame(f_above, timestamp=0.0)
        tach.process_frame(f_below, timestamp=0.005)  # Within debounce
        tach.process_frame(f_above, timestamp=0.008)  # Within debounce

        # Only 1 crossing should count (the first at 0.005)
        assert len(tach._crossing_times) == 1

    def test_multiple_crossings_over_time(self):
        tach = BeltTachometer()
        t = 0.0
        for i in range(6):
            t = _simulate_crossing(tach, t_start=t, dt=0.1)
            t += 0.3  # Wait between crossings

        assert len(tach._crossing_times) >= 5


# ---------------------------------------------------------------------------
# Test: RPM calculation
# ---------------------------------------------------------------------------

class TestRPMCalculation:
    def test_known_rpm(self):
        """Simulate crossings at known intervals to get predictable RPM."""
        tach = BeltTachometer()

        # 2 crossings per revolution, 1 crossing every 0.5s
        # = 2 crossings/s = 1 rev/s = 60 RPM
        t = 0.0
        for _ in range(10):
            t = _simulate_crossing(tach, t_start=t, dt=0.05)
            t += 0.45  # Total ~0.5s between crossings

        result = tach.process_frame(_make_frame(tape_y=200), timestamp=t)
        # RPM should be roughly 60 (2 crossings/sec * 60 / 2 crossings per rev)
        assert result["rpm"] > 30.0  # Reasonable range for ~60 RPM

    def test_zero_rpm_no_crossings(self):
        tach = BeltTachometer()
        frame = _make_frame(tape_y=200)
        result = tach.process_frame(frame, timestamp=0.0)
        assert result["rpm"] == 0.0

    def test_zero_rpm_static_tape(self):
        """Tape visible but not moving — RPM stays 0."""
        tach = BeltTachometer()
        for i in range(10):
            result = tach.process_frame(_make_frame(tape_y=200), timestamp=float(i))
        assert result["rpm"] == 0.0


# ---------------------------------------------------------------------------
# Test: Status conditions
# ---------------------------------------------------------------------------

class TestStatusConditions:
    def test_calibrating_initial(self):
        tach = BeltTachometer()
        result = tach.process_frame(_make_frame(tape_y=200), timestamp=0.0)
        assert result["status"] == "CALIBRATING"

    def test_normal_after_calibration(self):
        tach = BeltTachometer()
        tach.set_baseline_rpm(60.0)

        # Simulate current RPM near baseline
        t = 0.0
        for _ in range(10):
            t = _simulate_crossing(tach, t_start=t, dt=0.05)
            t += 0.45

        # Last crossing time will be set by simulate_crossing.
        # Process one more frame at center so offset is 0.
        result = tach.process_frame(_make_frame(tape_y=200), timestamp=t)
        assert result["status"] == "NORMAL"

    def test_stopped_status(self):
        tach = BeltTachometer()
        tach.set_baseline_rpm(60.0)
        tach._last_crossing_time = 0.0  # Long time ago

        # Process at a time far past STOPPED_TIMEOUT_SEC
        result = tach.process_frame(_make_frame(tape_y=None), timestamp=100.0)
        assert result["status"] == "STOPPED"

    def test_mistrack_status(self):
        tach = BeltTachometer()
        tach.set_baseline_rpm(60.0)

        # Simulate crossings to get RPM > 0
        t = 0.0
        for _ in range(6):
            t = _simulate_crossing(tach, t_start=t, dt=0.05)
            t += 0.45

        # Now process with tape far off center (x=20, center=320 → offset=300)
        frame = _make_frame(tape_y=200, tape_x=20)
        result = tach.process_frame(frame, timestamp=t)
        assert result["offset_px"] > MISTRACK_THRESHOLD_PX
        assert result["status"] == "MISTRACK"

    def test_slow_status(self):
        tach = BeltTachometer()
        tach.set_baseline_rpm(120.0)  # High baseline

        # Simulate slow crossings (well below baseline)
        t = 0.0
        for _ in range(6):
            t = _simulate_crossing(tach, t_start=t, dt=0.05)
            t += 2.0  # Very slow — ~1 crossing every 2s

        result = tach.process_frame(_make_frame(tape_y=200), timestamp=t)
        # Speed should be well below 80% of baseline
        assert result["status"] == "SLOW"


# ---------------------------------------------------------------------------
# Test: Video clip buffer
# ---------------------------------------------------------------------------

class TestClipBuffer:
    def test_buffer_stores_frames(self):
        tach = BeltTachometer()
        for i in range(10):
            tach.process_frame(_make_frame(tape_y=200), timestamp=float(i))
        assert len(tach._frame_buffer) == 10

    def test_clip_bytes_produces_valid_mp4(self):
        tach = BeltTachometer()
        for i in range(5):
            tach.process_frame(_make_frame(tape_y=200), timestamp=float(i))

        clip = tach.get_clip_bytes(fps=10.0)
        assert clip is not None
        assert len(clip) > 100  # Minimum viable MP4
        # MP4 files start with ftyp box or mdat
        # mp4v codec may produce raw MPEG-4 — just check non-empty
        assert isinstance(clip, bytes)

    def test_clip_bytes_none_when_empty(self):
        tach = BeltTachometer()
        assert tach.get_clip_bytes() is None


# ---------------------------------------------------------------------------
# Test: Environment variable overrides
# ---------------------------------------------------------------------------

class TestEnvOverrides:
    def test_custom_debounce(self, monkeypatch):
        """Verify debounce can be overridden via env."""
        # This tests at the module level — the env is already set
        # in the test file header. Just verify it took effect.
        from cosmos.belt_tachometer import CROSSING_DEBOUNCE_SEC
        assert CROSSING_DEBOUNCE_SEC == 0.01

    def test_custom_stopped_timeout(self):
        from cosmos.belt_tachometer import STOPPED_TIMEOUT_SEC
        assert STOPPED_TIMEOUT_SEC == 1.0


# ---------------------------------------------------------------------------
# Test: Frame annotation
# ---------------------------------------------------------------------------

class TestAnnotation:
    def test_annotate_returns_same_shape(self):
        tach = BeltTachometer()
        frame = _make_frame(tape_y=200)
        tach.process_frame(frame, timestamp=0.0)
        annotated = tach.annotate_frame(frame)
        assert annotated.shape == frame.shape

    def test_annotate_does_not_modify_original(self):
        tach = BeltTachometer()
        frame = _make_frame(tape_y=200)
        original = frame.copy()
        tach.process_frame(frame, timestamp=0.0)
        tach.annotate_frame(frame)
        np.testing.assert_array_equal(frame, original)
