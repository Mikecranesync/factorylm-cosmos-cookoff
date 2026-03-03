"""
Belt Video Reasoner — sends video clips + PLC context to Cosmos R2.

Handles the full pipeline: takes a video clip from BeltTachometer,
builds the prompt, calls the API (or returns demo stubs), and parses
the structured response.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import httpx

from diagnosis.prompts import build_belt_video_prompt

logger = logging.getLogger(__name__)


class BeltVideoReasoner:
    """Sends belt video clips to Cosmos R2 for AI diagnosis."""

    def __init__(self) -> None:
        self.api_key: str = os.getenv("NVIDIA_COSMOS_API_KEY", "")
        self.api_base_url: str = os.getenv(
            "NVIDIA_API_BASE_URL",
            "https://integrate.api.nvidia.com/v1",
        )
        self.model: str = os.getenv(
            "NVIDIA_COSMOS_MODEL",
            "nvidia/cosmos-reason2-8b",
        )
        # Sample rate for video frames sent to API (frames per second)
        self._sample_fps: int = 3

    def diagnose_belt_video(
        self,
        video_bytes: bytes | None,
        tachometer_data: dict[str, Any],
        tags: dict[str, Any],
        faults: list | None = None,
    ) -> dict[str, Any]:
        """Run full Cosmos R2 diagnosis on a belt video clip.

        Args:
            video_bytes: MP4 video bytes from BeltTachometer.get_clip_bytes()
            tachometer_data: Dict with rpm, speed_pct, offset_px, status
            tags: Current PLC tag values
            faults: Optional list of FaultDiagnosis objects

        Returns:
            Dict with: diagnosis, root_cause, observations,
                       recommended_actions, confidence, belt_motion_confirmed,
                       cosmos_model
        """
        # Build the text prompt
        prompt = build_belt_video_prompt(tachometer_data, tags, faults)

        # Real API call if key is available and video exists
        if self.api_key and video_bytes:
            return self._diagnose_real(video_bytes, prompt)

        # Demo mode: return realistic stubs based on belt status
        logger.info(
            "BeltVideoReasoner.diagnose_belt_video (STUB — %s)",
            "no API key" if not self.api_key else "no video",
        )
        return self._diagnose_stub(tachometer_data)

    def _diagnose_real(self, video_bytes: bytes, prompt: str) -> dict[str, Any]:
        """Make real API call to Cosmos R2 with video."""
        logger.info("BeltVideoReasoner: sending video to %s (%d bytes)", self.model, len(video_bytes))

        video_b64 = base64.b64encode(video_bytes).decode("utf-8")

        content = [
            {"type": "text", "text": prompt},
            {
                "type": "video_url",
                "video_url": {"url": f"data:video/mp4;base64,{video_b64}"},
            },
        ]

        try:
            response = httpx.post(
                f"{self.api_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": content}],
                    "max_tokens": 1024,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            result = response.json()

            raw_text = result["choices"][0]["message"]["content"]
            return self._parse_response(raw_text)

        except httpx.HTTPStatusError as e:
            logger.error("Cosmos belt API error: %s — %s", e.response.status_code, e.response.text)
            return self._error_response(f"API error: {e.response.status_code}")
        except Exception as e:
            logger.exception("Cosmos belt API error: %s", e)
            return self._error_response(str(e))

    def _parse_response(self, raw_text: str) -> dict[str, Any]:
        """Parse Cosmos R2 JSON response, handling markdown code blocks."""
        try:
            text = raw_text
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            parsed = json.loads(text.strip())

            return {
                "diagnosis": parsed.get("diagnosis", "Analysis complete"),
                "root_cause": parsed.get("root_cause", "Unknown"),
                "observations": parsed.get("observations", []),
                "recommended_actions": parsed.get("recommended_actions", []),
                "confidence": float(parsed.get("confidence", 0.5)),
                "belt_motion_confirmed": parsed.get("belt_motion_confirmed", True),
                "cosmos_model": self.model,
            }
        except (json.JSONDecodeError, IndexError):
            return {
                "diagnosis": raw_text[:300],
                "root_cause": "See full response",
                "observations": ["Raw text response — JSON parsing failed"],
                "recommended_actions": ["Review full Cosmos response"],
                "confidence": 0.3,
                "belt_motion_confirmed": True,
                "cosmos_model": self.model,
            }

    def _diagnose_stub(self, tachometer_data: dict[str, Any]) -> dict[str, Any]:
        """Return realistic stub responses based on belt status."""
        status = tachometer_data.get("status", "NORMAL")
        rpm = tachometer_data.get("rpm", 0.0)
        offset = tachometer_data.get("offset_px", 0)

        stubs = {
            "NORMAL": {
                "diagnosis": f"Belt running normally at {rpm} RPM. No anomalies detected in video.",
                "root_cause": "N/A",
                "observations": [
                    "Belt moving at consistent speed",
                    "Orange tape marker tracking on center",
                    "No vibration or irregular motion detected",
                ],
                "recommended_actions": ["Continue normal monitoring"],
                "confidence": 0.92,
                "belt_motion_confirmed": True,
            },
            "SLOW": {
                "diagnosis": f"Belt speed reduced to {rpm} RPM. Video confirms slower-than-normal belt motion.",
                "root_cause": "Possible belt slip on drive roller or VFD output reduction",
                "observations": [
                    f"Belt visibly slower than baseline — tachometer reads {rpm} RPM",
                    "Orange tape crossing frequency reduced",
                    "No visible obstruction or jam",
                    "Motor appears to be running (vibration visible on frame)",
                ],
                "recommended_actions": [
                    "Check VFD output frequency — is drive commanding full speed?",
                    "Inspect belt tension — possible slip on drive roller",
                    "Check for excessive load or drag on conveyor",
                ],
                "confidence": 0.78,
                "belt_motion_confirmed": True,
            },
            "MISTRACK": {
                "diagnosis": f"Belt mistracking detected. Lateral offset {offset}px from center.",
                "root_cause": "Belt alignment issue — uneven tension or roller misalignment",
                "observations": [
                    f"Orange tape is {offset}px off center — belt drifting laterally",
                    "Belt edge approaching guide rail",
                    "Speed appears normal but tracking is off",
                ],
                "recommended_actions": [
                    "Check roller alignment — snub rollers may need adjustment",
                    "Inspect belt tension on both sides",
                    "Look for belt edge wear or damage",
                ],
                "confidence": 0.82,
                "belt_motion_confirmed": True,
            },
            "STOPPED": {
                "diagnosis": "Belt is not moving. No motion detected in video for 3+ seconds.",
                "root_cause": "Belt stopped — motor may be off, faulted, or mechanically jammed",
                "observations": [
                    "No belt motion visible in video",
                    "Orange tape marker stationary",
                    "No vibration from motor/drive area",
                ],
                "recommended_actions": [
                    "Check motor contactor — is it pulled in?",
                    "Check VFD status for fault codes",
                    "Verify E-stop circuit is not engaged",
                    "Inspect for mechanical jam at drive or tail roller",
                ],
                "confidence": 0.90,
                "belt_motion_confirmed": True,
            },
            "CALIBRATING": {
                "diagnosis": "System is calibrating. Collecting baseline RPM data.",
                "root_cause": "N/A — calibration in progress",
                "observations": [
                    "Belt appears to be running",
                    "Collecting crossing data for baseline RPM",
                ],
                "recommended_actions": ["Wait for calibration to complete (5+ crossings needed)"],
                "confidence": 0.50,
                "belt_motion_confirmed": True,
            },
        }

        result = stubs.get(status, stubs["NORMAL"])
        result["cosmos_model"] = f"{self.model} (stub)"
        return result

    def _error_response(self, error_msg: str) -> dict[str, Any]:
        """Return a structured error response."""
        return {
            "diagnosis": f"Analysis failed: {error_msg}",
            "root_cause": "API error",
            "observations": [],
            "recommended_actions": ["Retry diagnosis", "Check API credentials"],
            "confidence": 0.0,
            "belt_motion_confirmed": False,
            "cosmos_model": self.model,
        }
