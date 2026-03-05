"""
Speed Fusion Monitor — PLC commanded speed vs visual belt speed.

Provides compute_fusion() for comparing PLC motor_speed with vision-based
belt tachometer speed_pct. MockBeltStatus auto-cycles through fault
scenarios for --mock mode demos.
"""

from __future__ import annotations

import math
import time


def compute_fusion(plc_tags: dict, belt_status: dict) -> dict:
    """Compare PLC commanded speed with visual belt speed.

    Returns dict with plc_speed_pct, visual_speed_pct, mismatch_pct, status.
    Status is one of: MATCH, SLIP, JAM.
    """
    plc_speed = float(plc_tags.get("motor_speed", 0))
    visual_speed = float(belt_status.get("speed_pct", 0))

    if plc_speed > 0:
        mismatch = abs(plc_speed - visual_speed) / plc_speed * 100.0
    else:
        mismatch = 0.0 if visual_speed < 1.0 else 100.0

    if mismatch > 50 and plc_speed > 10:
        status = "JAM"
    elif mismatch > 20:
        status = "SLIP"
    else:
        status = "MATCH"

    return {
        "plc_speed_pct": round(plc_speed, 1),
        "visual_speed_pct": round(visual_speed, 1),
        "mismatch_pct": round(mismatch, 1),
        "status": status,
    }


class MockBeltStatus:
    """Auto-cycling mock that simulates MATCH -> SLIP -> JAM -> recovery.

    Cycle (60s total):
      0-20s:  MATCH  — visual ~= PLC +/- 3%
      20-40s: SLIP   — visual decays to 50%
      40-50s: JAM    — visual = 0, motor = 80%
      50-60s: Recovery back to MATCH
    """

    CYCLE_SEC = 60.0

    def get_status(self, plc_speed: float = 80.0) -> dict:
        t = time.time() % self.CYCLE_SEC
        if t < 20:
            # MATCH phase
            jitter = 3.0 * math.sin(t * 2.0)
            visual = plc_speed + jitter
        elif t < 40:
            # SLIP phase — linear decay from plc_speed to 50% of it
            progress = (t - 20) / 20.0
            visual = plc_speed * (1.0 - 0.5 * progress)
        elif t < 50:
            # JAM phase — belt stopped
            visual = 0.0
        else:
            # Recovery — ramp back up
            progress = (t - 50) / 10.0
            visual = plc_speed * progress

        return {
            "speed_pct": round(max(0.0, visual), 1),
            "rpm": round(visual * 0.3, 1),
            "status": "NORMAL" if visual > 10 else "STOPPED",
        }
