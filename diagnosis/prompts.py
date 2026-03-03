"""
LLM Prompt Templates for Fault Diagnosis
========================================
Structured prompts that produce technician-friendly explanations.
"""

from typing import Dict, Any, List, Optional
from .conveyor_faults import FaultDiagnosis, FaultSeverity


def build_diagnosis_prompt(
    question: str,
    tags: Dict[str, Any],
    faults: List[FaultDiagnosis],
    include_history: bool = False
) -> str:
    """
    Build a structured prompt for the LLM to answer a technician's question.

    Args:
        question: The technician's question (e.g., "Why is the conveyor stopped?")
        tags: Current PLC tag values
        faults: List of detected faults from rule-based analysis
        include_history: Whether to include tag history (future feature)

    Returns:
        Formatted prompt string for the LLM
    """

    # Format current tag state
    tag_lines = []
    for key, value in sorted(tags.items()):
        if key.startswith("_") or key in ("id", "timestamp", "node_id"):
            continue
        if isinstance(value, bool) or value in (0, 1):
            display = "ON" if value else "OFF"
        elif isinstance(value, float):
            display = f"{value:.2f}"
        else:
            display = str(value)
        tag_lines.append(f"  {key}: {display}")

    tag_state = "\n".join(tag_lines)

    # Format detected faults
    if faults:
        fault_lines = []
        for f in faults:
            if f.severity == FaultSeverity.INFO:
                continue  # Skip info-level in prompt
            fault_lines.append(f"  [{f.severity.value.upper()}] {f.fault_code}: {f.title}")
            fault_lines.append(f"    {f.description}")
            if f.likely_causes:
                fault_lines.append(f"    Causes: {', '.join(f.likely_causes[:3])}")
        fault_state = "\n".join(fault_lines) if fault_lines else "  No active faults detected"
    else:
        fault_state = "  No active faults detected"

    prompt = f"""You are an expert industrial maintenance technician assistant for a conveyor system controlled by an Allen-Bradley Micro820 PLC.

CURRENT EQUIPMENT STATE:
{tag_state}

DETECTED FAULTS:
{fault_state}

TECHNICIAN'S QUESTION:
{question}

INSTRUCTIONS:
1. Answer the technician's question directly and concisely
2. Reference specific tag values when relevant
3. Provide 2-4 actionable troubleshooting steps
4. Use plain language - avoid jargon
5. If safety is a concern, mention it first
6. Keep response under 200 words

RESPONSE:"""

    return prompt


def build_why_stopped_prompt(tags: Dict[str, Any], faults: List[FaultDiagnosis]) -> str:
    """Specialized prompt for 'Why is this stopped?' queries."""
    return build_diagnosis_prompt(
        question="Why is this equipment stopped? What should I check first?",
        tags=tags,
        faults=faults
    )


def build_status_summary_prompt(tags: Dict[str, Any], faults: List[FaultDiagnosis]) -> str:
    """Prompt for generating a quick status summary."""
    return build_diagnosis_prompt(
        question="Give me a one-sentence status summary of this equipment.",
        tags=tags,
        faults=faults
    )


def build_belt_video_prompt(
    tachometer_data: Dict[str, Any],
    tags: Dict[str, Any],
    faults: Optional[List[FaultDiagnosis]] = None,
) -> str:
    """Build a prompt for Cosmos R2 to analyze a belt video clip.

    Args:
        tachometer_data: Dict with rpm, speed_pct, offset_px, status from BeltTachometer.
        tags: Current PLC tag values.
        faults: Optional list of detected faults.

    Returns:
        Formatted prompt string for Cosmos R2 video analysis.
    """
    status = tachometer_data.get("status", "UNKNOWN")
    rpm = tachometer_data.get("rpm", 0.0)
    speed_pct = tachometer_data.get("speed_pct", 0.0)
    offset_px = tachometer_data.get("offset_px", 0)

    tag_lines = []
    for key, value in sorted(tags.items()):
        if key.startswith("_") or key in ("id", "timestamp", "node_id"):
            continue
        if isinstance(value, bool) or value in (0, 1):
            display = "ON" if value else "OFF"
        elif isinstance(value, float):
            display = f"{value:.2f}"
        else:
            display = str(value)
        tag_lines.append(f"  {key}: {display}")
    tag_state = "\n".join(tag_lines) if tag_lines else "  No tags available"

    fault_state = "  No active faults detected"
    if faults:
        fault_lines = []
        for f in faults:
            if f.severity == FaultSeverity.INFO:
                continue
            fault_lines.append(f"  [{f.severity.value.upper()}] {f.fault_code}: {f.title}")
        if fault_lines:
            fault_state = "\n".join(fault_lines)

    return f"""You are an expert industrial maintenance AI analyzing a 5-second video clip of a conveyor belt with an orange tape marker.

TACHOMETER READINGS (from vision system):
  Status: {status}
  RPM: {rpm}
  Speed: {speed_pct:.0f}% of baseline
  Lateral offset: {offset_px}px from center

PLC TAG VALUES (live from Micro820):
{tag_state}

DETECTED FAULTS:
{fault_state}

INSTRUCTIONS — analyze this video clip and provide:

1. MOTION ANALYSIS: Watch the belt motion. Does it confirm or contradict the tachometer reading of {rpm} RPM? Look for:
   - Belt slip (motor running but belt not moving at expected speed)
   - Irregular motion (jerking, surging, hesitation)
   - Complete stoppage

2. ALIGNMENT CHECK: Is the belt tracking straight or drifting? The tachometer reads {offset_px}px offset. Look for:
   - Belt drifting left or right
   - Uneven belt tension
   - Edge wear or fraying

3. ANOMALY DETECTION: Look for anything unusual:
   - Material jam or debris on the belt
   - Loose or damaged orange tape marker
   - Excessive vibration
   - Foreign objects

4. PLC CROSS-REFERENCE: Compare what you see with the PLC data. Flag any discrepancies like:
   - Motor register says ON but belt appears stopped
   - Speed register says 100% but belt is visibly slow
   - No fault code but visible problem

Respond in JSON format with these keys:
- diagnosis: One-sentence summary of what you see
- root_cause: Most likely cause of any problem (or "N/A" if normal)
- observations: List of 2-4 specific things you observed in the video
- recommended_actions: List of 1-3 actions the technician should take
- confidence: Float 0-1 for your diagnosis confidence
- belt_motion_confirmed: Boolean — does video confirm the tachometer reading?"""


SYSTEM_PROMPT = """You are FactoryLM, an AI assistant for industrial maintenance technicians.

Your role:
- Help diagnose equipment faults quickly
- Provide clear, actionable guidance
- Prioritize safety
- Reference real data from PLC tags
- Keep explanations concise

Equipment context:
- Allen-Bradley Micro820 PLC
- Conveyor system with motor, sensors, and pneumatics
- Standard industrial safety interlocks

Communication style:
- Direct and professional
- Use bullet points for steps
- Bold safety warnings
- Reference specific tag names and values"""
