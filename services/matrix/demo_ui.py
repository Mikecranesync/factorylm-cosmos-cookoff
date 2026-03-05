"""
Pi Factory Demo UI — Fault Diagnosis Dashboard
==============================================
FastAPI app with live IO display and "Why stopped?" diagnosis.

Run: uvicorn services.matrix.demo_ui:app --host 0.0.0.0 --port 8080
"""

import os
import sys
import time
import httpx
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from diagnosis.conveyor_faults import detect_faults, format_diagnosis_for_technician
from diagnosis.prompts import build_diagnosis_prompt, SYSTEM_PROMPT
from cosmos.client import CosmosClient
from demo.speed_fusion import compute_fusion, MockBeltStatus

# Configuration
MATRIX_API = os.getenv("MATRIX_API", "http://localhost:8000")
BELT_API = os.getenv("BELT_API", "http://localhost:8081/api/belt/status")
NVIDIA_API_KEY = os.getenv("NVIDIA_COSMOS_API_KEY", "")

_mock_belt = MockBeltStatus()

# Fault injection state for demo
_injected_fault: str | None = None

app = FastAPI(title="FactoryLM — Overhead Crane AI", version="1.0.0")


# ============================================================================
# Models
# ============================================================================

class DiagnoseRequest(BaseModel):
    question: str = "Why is this equipment stopped?"


class DiagnoseResponse(BaseModel):
    question: str
    answer: str
    faults_detected: list
    model: str
    latency_ms: int
    timestamp: str


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/api/tags")
async def get_live_tags():
    """Fetch latest tags from Matrix API."""
    try:
        resp = httpx.get(f"{MATRIX_API}/api/tags?limit=1", timeout=5)
        resp.raise_for_status()
        tags_list = resp.json()
        if tags_list:
            return tags_list[0]
        return {"error": "No tags available"}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/faults")
async def get_faults():
    """Detect faults from current tags."""
    try:
        tags = await get_live_tags()
        if "error" in tags:
            return tags

        faults = detect_faults(tags)
        return {
            "faults": [
                {
                    "code": f.fault_code,
                    "severity": f.severity.value,
                    "title": f.title,
                    "description": f.description,
                    "causes": f.likely_causes,
                    "checks": f.suggested_checks
                }
                for f in faults
            ],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error("Fault detection failed: %s", e)
        return {"error": "fault_detection_failed", "detail": str(e)}


@app.get("/api/speed-fusion")
async def get_speed_fusion():
    """Compare PLC commanded speed vs visual belt speed."""
    tags = await get_live_tags()
    plc_speed = float(tags.get("motor_speed", 80)) if "error" not in tags else 80.0

    # If fault injected, override belt status
    if _injected_fault == "jam":
        belt = {"speed_pct": 0.0, "rpm": 0.0, "status": "STOPPED"}
    elif _injected_fault == "slip":
        belt = {"speed_pct": plc_speed * 0.4, "rpm": plc_speed * 0.12, "status": "SLOW"}
    elif _injected_fault == "estop":
        belt = {"speed_pct": 0.0, "rpm": 0.0, "status": "STOPPED"}
        plc_speed = 0.0
    else:
        # Try live belt tachometer API, fall back to mock
        try:
            resp = httpx.get(BELT_API, timeout=2)
            resp.raise_for_status()
            belt = resp.json()
        except Exception:
            belt = _mock_belt.get_status(plc_speed)

    plc_tags = {"motor_speed": plc_speed}
    return compute_fusion(plc_tags, belt)


@app.get("/webcam")
async def webcam():
    """MJPEG stream from local webcam for Cosmos R2 vision input."""
    import cv2

    def stream():
        cap = cv2.VideoCapture(0)
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                cv2.putText(frame, "Cosmos R2 Vision Input", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 136), 2)
                _, jpeg = cv2.imencode('.jpg', frame,
                                       [cv2.IMWRITE_JPEG_QUALITY, 70])
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
                       + jpeg.tobytes() + b'\r\n')
        finally:
            cap.release()

    return StreamingResponse(stream(),
                             media_type="multipart/x-mixed-replace;boundary=frame")


@app.post("/api/inject-fault/{fault_type}")
async def inject_fault(fault_type: str):
    """Inject a fault scenario for demo purposes."""
    global _injected_fault
    if fault_type == "clear":
        _injected_fault = None
    elif fault_type in ("jam", "slip", "estop"):
        _injected_fault = fault_type
    else:
        return {"error": f"Unknown fault type: {fault_type}"}
    return {"injected": _injected_fault}


@app.get("/api/injected-fault")
async def get_injected_fault():
    """Get current injected fault state."""
    return {"injected": _injected_fault}


@app.post("/api/diagnose", response_model=DiagnoseResponse)
async def diagnose(request: DiagnoseRequest):
    """
    AI-powered fault diagnosis.

    Measures latency from request to LLM response.
    """
    start_time = time.time()

    # Get current tags
    tags = await get_live_tags()
    if "error" in tags:
        return DiagnoseResponse(
            question=request.question,
            answer=f"Cannot fetch PLC data: {tags['error']}",
            faults_detected=[],
            model="error",
            latency_ms=int((time.time() - start_time) * 1000),
            timestamp=datetime.now().isoformat()
        )

    # Detect faults
    faults = detect_faults(tags)

    # Build prompt
    prompt = build_diagnosis_prompt(
        question=request.question,
        tags=tags,
        faults=faults
    )

    # Call LLM
    try:
        client = CosmosClient()

        # Use analyze_incident which already handles Cosmos/Llama fallback
        result = client.analyze_incident(
            incident_id=f"DEMO-{int(time.time())}",
            node_id=tags.get("node_id", "factory-io"),
            tags=tags,
            context=f"Technician question: {request.question}"
        )

        answer = f"{result.summary}\n\nRoot Cause: {result.root_cause}\n\n"
        if result.suggested_checks:
            answer += "Suggested Checks:\n"
            for check in result.suggested_checks[:5]:
                answer += f"  - {check}\n"

        model_used = result.cosmos_model

    except Exception as e:
        # Fallback to rule-based diagnosis
        answer = "AI analysis unavailable. Rule-based diagnosis:\n\n"
        for fault in faults:
            answer += format_diagnosis_for_technician(fault) + "\n\n"
        model_used = "rule-based"

    latency_ms = int((time.time() - start_time) * 1000)

    return DiagnoseResponse(
        question=request.question,
        answer=answer,
        faults_detected=[f.fault_code for f in faults if f.severity.value != "info"],
        model=model_used,
        latency_ms=latency_ms,
        timestamp=datetime.now().isoformat()
    )


@app.get("/", response_class=HTMLResponse)
async def demo_dashboard():
    """Demo dashboard with live IO and diagnosis."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FactoryLM — Overhead Crane AI</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .nvidia-strip {
            background: linear-gradient(90deg, #76b900, #1a1a1a);
            height: 3px; width: 100%;
        }
        .nvidia-bar {
            background: #0a0a0a; padding: 4px 16px;
            font-size: 0.7em; color: #555;
            border-bottom: 1px solid #1a1a1a;
        }
        .nvidia-bar .nv { color: #76b900; font-weight: 700; }
        .header {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            padding: 20px;
            border-bottom: 2px solid #0f3460;
            display: flex; justify-content: space-between; align-items: center;
        }
        .header h1 { font-size: 24px; color: #00ff88; }
        .header p { color: #888; margin-top: 5px; }
        .conn-badge {
            display: inline-flex; align-items: center; gap: 8px;
            padding: 4px 12px; border-radius: 20px;
            background: #0a2a1a; border: 1px solid #00ff88;
            font-size: 0.75em; color: #00ff88;
        }
        .conn-dot {
            width: 8px; height: 8px; border-radius: 50%;
            background: #00ff88; animation: pulse 1.5s infinite;
        }
        #mismatch-banner {
            display: none; background: #ff4444; color: #fff;
            text-align: center; padding: 10px;
            font-weight: 700; letter-spacing: 2px; font-size: 1em;
            animation: flashbg 0.8s infinite;
            position: sticky; top: 0; z-index: 999;
        }
        .container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px; padding: 20px;
            max-width: 1400px; margin: 0 auto;
        }
        @media (max-width: 900px) {
            .container { grid-template-columns: 1fr; }
        }
        .panel {
            background: #12121a;
            border: 1px solid #2a2a3a;
            border-radius: 12px;
            overflow: hidden;
        }
        .panel-header {
            background: #1a1a2e;
            padding: 15px 20px;
            border-bottom: 1px solid #2a2a3a;
            display: flex; justify-content: space-between; align-items: center;
        }
        .panel-header h2 { font-size: 16px; color: #fff; }
        .panel-body { padding: 20px; }
        .tag-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
        }
        .tag-item {
            background: #1a1a2e;
            padding: 12px 15px; border-radius: 8px;
            display: flex; justify-content: space-between; align-items: center;
        }
        .tag-name { color: #888; font-size: 13px; }
        .tag-value { font-weight: 600; font-size: 15px; }
        .tag-value.on { color: #00ff88; }
        .tag-value.off { color: #666; }
        .tag-value.warning { color: #ffaa00; }
        .tag-value.critical { color: #ff4444; }
        .status-badge {
            display: inline-block; padding: 4px 12px;
            border-radius: 20px; font-size: 12px; font-weight: 600;
        }
        .status-ok { background: #00ff8820; color: #00ff88; }
        .status-warning { background: #ffaa0020; color: #ffaa00; }
        .status-critical { background: #ff444420; color: #ff4444; }
        .status-emergency { background: #ff000040; color: #ff0000; }
        .fault-list { margin-top: 15px; }
        .fault-item {
            background: #1a1a2e; padding: 15px; border-radius: 8px;
            margin-bottom: 10px; border-left: 4px solid #666;
        }
        .fault-item.warning { border-color: #ffaa00; }
        .fault-item.critical { border-color: #ff4444; }
        .fault-item.emergency { border-color: #ff0000; }
        .fault-title { font-weight: 600; margin-bottom: 5px; }
        .fault-desc { color: #888; font-size: 14px; }
        .diagnosis-box {
            background: #1a1a2e; border-radius: 8px;
            padding: 20px; margin-top: 15px;
        }
        .diagnosis-question {
            display: flex; gap: 10px; margin-bottom: 15px;
        }
        .diagnosis-question input {
            flex: 1; background: #0a0a0f;
            border: 1px solid #2a2a3a; border-radius: 8px;
            padding: 12px 15px; color: #fff; font-size: 14px;
        }
        .diagnosis-question input:focus { outline: none; border-color: #00ff88; }
        .btn {
            background: linear-gradient(135deg, #00ff88 0%, #00cc6a 100%);
            color: #000; border: none; padding: 12px 24px;
            border-radius: 8px; font-weight: 600; cursor: pointer;
            transition: transform 0.1s;
        }
        .btn:hover { transform: scale(1.02); }
        .btn:active { transform: scale(0.98); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-secondary { background: #2a2a3a; color: #fff; }
        .diagnosis-result {
            background: #0a0a0f; border-radius: 8px; padding: 20px;
            margin-top: 15px; white-space: pre-wrap;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 13px; line-height: 1.6;
            max-height: 400px; overflow-y: auto;
        }
        .latency-badge {
            background: #2a2a3a; padding: 4px 10px;
            border-radius: 4px; font-size: 12px; color: #888;
        }
        .latency-badge.fast { color: #00ff88; }
        .latency-badge.slow { color: #ffaa00; }
        .refresh-indicator {
            width: 8px; height: 8px; border-radius: 50%;
            background: #00ff88; animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 4px #00ff88; }
            50% { opacity: 0.3; box-shadow: none; }
        }
        @keyframes flash {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.2; }
        }
        @keyframes flashbg {
            0%, 100% { background: #ff4444; }
            50% { background: #aa0000; }
        }
        .critical-flash {
            border-color: #ff4444 !important;
            animation: panel-pulse 1s infinite;
        }
        @keyframes panel-pulse {
            0%, 100% { border-color: #ff4444; box-shadow: 0 0 0 0 rgba(255, 68, 68, 0); }
            50% { border-color: #ff0000; box-shadow: 0 0 20px 4px rgba(255, 68, 68, 0.4); }
        }
        .inject-btn {
            padding: 6px 14px; border-radius: 4px; cursor: pointer;
            font-size: 0.8em; letter-spacing: 1px; font-weight: 600;
        }
        .history-log {
            max-height: 200px; overflow-y: auto;
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 12px; line-height: 1.8; color: #888;
        }
        .history-log .entry-fault { color: #ff4444; }
        .history-log .entry-diag { color: #4488ff; }
        .history-log .entry-clear { color: #00ff88; }
        .footer {
            text-align: center; padding: 20px;
            color: #444; font-size: 12px;
        }
    </style>
</head>
<body>
    <!-- NVIDIA Branding -->
    <div class="nvidia-strip"></div>
    <div class="nvidia-bar">
        Powered by <span class="nv">NVIDIA Cosmos Reason 2</span>
        &nbsp;&bull;&nbsp; NVIDIA Cosmos Cookoff 2026
        &nbsp;&bull;&nbsp; FactoryLM
    </div>

    <!-- Speed Mismatch Banner (sticky top, hidden by default) -->
    <div id="mismatch-banner">SPEED MISMATCH DETECTED</div>

    <div class="header">
        <div>
            <h1>FactoryLM — Overhead Crane AI</h1>
            <p>Physical AI Safety System for Overhead Cranes &amp; Hoists</p>
        </div>
        <div class="conn-badge">
            <span class="conn-dot"></span>
            LIVE &mdash; Micro 820 @ 192.168.1.100
        </div>
    </div>

    <div class="container">
        <!-- Live IO Panel -->
        <div class="panel">
            <div class="panel-header">
                <h2>Live I/O Status</h2>
                <div style="display: flex; align-items: center; gap: 10px;">
                    <span id="lastUpdate" class="latency-badge">--</span>
                    <div class="refresh-indicator"></div>
                </div>
            </div>
            <div class="panel-body">
                <div class="tag-grid" id="tagGrid">
                    <div class="tag-item"><span class="tag-name">Loading...</span></div>
                </div>
            </div>
        </div>

        <!-- Webcam Feed Panel -->
        <div class="panel" id="vision-panel">
            <div class="panel-header">
                <h2>Vision Input &rarr; Cosmos R2</h2>
                <span class="status-badge status-ok">LIVE</span>
            </div>
            <div class="panel-body" style="padding: 10px;">
                <img src="/webcam"
                     style="width:100%;border-radius:6px;border:1px solid #00ff88;display:block"
                     onerror="this.style.opacity=0.3;this.alt='Camera unavailable'">
                <div style="color:#555;font-size:0.7em;margin-top:4px">
                    Live feed &bull; Tape markers tracked for belt speed fusion
                </div>
            </div>
        </div>

        <!-- Faults Panel -->
        <div class="panel">
            <div class="panel-header">
                <h2>Detected Faults</h2>
                <span id="faultCount" class="status-badge status-ok">0 Active</span>
            </div>
            <div class="panel-body">
                <div class="fault-list" id="faultList">
                    <div class="fault-item">
                        <div class="fault-title">Scanning...</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Fault History Timeline -->
        <div class="panel">
            <div class="panel-header">
                <h2>Event Timeline</h2>
                <span class="latency-badge" id="historyCount">0 events</span>
            </div>
            <div class="panel-body">
                <div class="history-log" id="historyLog">
                    <div style="color:#555">Waiting for events...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Speed Fusion Monitor -->
    <div style="max-width: 1400px; margin: 0 auto; padding: 0 20px;">
        <div class="panel" id="fusionPanel">
            <div class="panel-header">
                <h2>Speed Fusion Monitor</h2>
                <span id="fusionStatus" class="status-badge status-ok">MATCH</span>
            </div>
            <div class="panel-body">
                <div style="display: flex; gap: 30px; align-items: center; flex-wrap: wrap;">
                    <div style="flex: 1; min-width: 200px;">
                        <div style="color: #888; font-size: 13px; margin-bottom: 6px;">PLC Commanded</div>
                        <div style="background: #1a1a2e; border-radius: 8px; height: 32px; overflow: hidden;">
                            <div id="plcBar" style="height: 100%; background: #0066ff; border-radius: 8px; transition: width 0.5s; width: 0%; display: flex; align-items: center; padding-left: 10px; font-size: 13px; font-weight: 600; color: #fff; min-width: 40px;">0%</div>
                        </div>
                    </div>
                    <div style="flex: 1; min-width: 200px;">
                        <div style="color: #888; font-size: 13px; margin-bottom: 6px;">Visual (Camera)</div>
                        <div style="background: #1a1a2e; border-radius: 8px; height: 32px; overflow: hidden;">
                            <div id="visualBar" style="height: 100%; background: #00cc6a; border-radius: 8px; transition: width 0.5s; width: 0%; display: flex; align-items: center; padding-left: 10px; font-size: 13px; font-weight: 600; color: #fff; min-width: 40px;">0%</div>
                        </div>
                    </div>
                    <div style="text-align: center; min-width: 120px;">
                        <div style="color: #888; font-size: 13px; margin-bottom: 6px;">Mismatch</div>
                        <div id="mismatchValue" style="font-size: 28px; font-weight: 700; color: #00ff88;">0%</div>
                    </div>
                </div>
                <div id="mismatchWarning" style="display: none; margin-top: 15px; text-align: center; padding: 15px; border-radius: 8px; background: #ff000030; border: 2px solid #ff4444;">
                    <div style="font-size: 24px; font-weight: 800; color: #ff4444; animation: flash 0.5s infinite;">SPEED MISMATCH</div>
                    <div id="mismatchDetail" style="color: #ff8888; margin-top: 5px; font-size: 14px;">PLC commanding motion but belt not moving</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Diagnosis Panel -->
    <div style="max-width: 1400px; margin: 0 auto; padding: 20px 20px 0;">
        <div class="panel">
            <div class="panel-header">
                <h2>AI Fault Diagnosis</h2>
                <span id="diagnosisModel" class="latency-badge">--</span>
            </div>
            <div class="panel-body">
                <div class="diagnosis-box">
                    <div class="diagnosis-question">
                        <input type="text" id="questionInput" placeholder="Ask a question... (e.g., Why is this stopped?)" value="Why is this equipment stopped?">
                        <button class="btn" onclick="runDiagnosis()">Diagnose</button>
                        <button class="btn btn-secondary" onclick="quickDiagnose()">Quick Check</button>
                    </div>

                    <!-- Fault Injection Buttons -->
                    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:15px">
                        <button onclick="injectFault('jam')" class="inject-btn"
                                style="background:#1a0a0a;color:#ff4444;border:1px solid #ff4444">
                            INJECT JAM</button>
                        <button onclick="injectFault('slip')" class="inject-btn"
                                style="background:#1a1500;color:#ffcc00;border:1px solid #ffcc00">
                            INJECT SLIP</button>
                        <button onclick="injectFault('estop')" class="inject-btn"
                                style="background:#0a0a1a;color:#4488ff;border:1px solid #4488ff">
                            E-STOP</button>
                        <button onclick="injectFault('clear')" class="inject-btn"
                                style="background:#0a1a0a;color:#00ff88;border:1px solid #00ff88">
                            CLEAR ALL</button>
                    </div>

                    <!-- Chain-of-thought reasoning block -->
                    <details id="think-block" style="display:none;margin-bottom:12px">
                        <summary style="color:#555;font-size:0.75em;cursor:pointer">
                            Cosmos R2 Chain-of-Thought Reasoning
                        </summary>
                        <pre id="think-text"
                             style="color:#446644;font-size:0.7em;white-space:pre-wrap;
                                    border-left:2px solid #1a3a1a;padding-left:8px;
                                    margin-top:6px;font-family:monospace"></pre>
                    </details>

                    <div id="diagnosisResult" class="diagnosis-result" style="display: none;"></div>
                    <div id="diagnosisLatency" style="margin-top: 10px; display: none;">
                        <span class="latency-badge" id="latencyValue">--</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="footer">
        FactoryLM | Webcam + Modbus TCP &rarr; Cosmos Reason 2 (8B) &rarr; Crane Safety AI
    </div>

    <script>
        const API_BASE = '';
        const eventHistory = [];

        function addHistoryEvent(type, message) {
            const now = new Date().toLocaleTimeString();
            eventHistory.unshift({ time: now, type, message });
            if (eventHistory.length > 50) eventHistory.pop();

            const log = document.getElementById('historyLog');
            const countEl = document.getElementById('historyCount');
            countEl.textContent = eventHistory.length + ' events';

            log.innerHTML = eventHistory.map(e => {
                const cls = e.type === 'fault' ? 'entry-fault'
                          : e.type === 'diag' ? 'entry-diag'
                          : 'entry-clear';
                return '<div class="' + cls + '">' + e.time + '  ' + e.message + '</div>';
            }).join('');
        }

        const tagConfig = {
            motor_running: { label: 'Motor', type: 'bool' },
            motor_speed: { label: 'Motor Speed', type: 'percent' },
            motor_current: { label: 'Motor Current', type: 'amps' },
            temperature: { label: 'Temperature', type: 'temp', warn: 65, crit: 80 },
            pressure: { label: 'Pressure', type: 'psi', warn: 70, crit: 60 },
            conveyor_running: { label: 'Conveyor', type: 'bool' },
            conveyor_speed: { label: 'Conveyor Speed', type: 'percent' },
            sensor_1: { label: 'Sensor 1', type: 'bool' },
            sensor_2: { label: 'Sensor 2', type: 'bool' },
            fault_alarm: { label: 'Fault Alarm', type: 'alarm' },
            e_stop: { label: 'E-Stop', type: 'estop' },
            error_code: { label: 'Error Code', type: 'int' }
        };

        function formatTagValue(key, value, config) {
            if (!config) return { text: String(value), class: '' };
            switch (config.type) {
                case 'bool':
                    return { text: value ? 'RUNNING' : 'STOPPED', class: value ? 'on' : 'off' };
                case 'percent':
                    return { text: value + '%', class: '' };
                case 'amps': {
                    const amps = parseFloat(value).toFixed(2);
                    return { text: amps + ' A', class: value > 5 ? 'critical' : '' };
                }
                case 'temp': {
                    const temp = parseFloat(value).toFixed(1);
                    let c = '';
                    if (value > config.crit) c = 'critical';
                    else if (value > config.warn) c = 'warning';
                    return { text: temp + ' C', class: c };
                }
                case 'psi': {
                    let c = '';
                    if (value < config.crit) c = 'critical';
                    else if (value < config.warn) c = 'warning';
                    return { text: value + ' PSI', class: c };
                }
                case 'alarm':
                    return { text: value ? 'ACTIVE' : 'Clear', class: value ? 'critical' : 'on' };
                case 'estop':
                    return { text: value ? 'PRESSED' : 'Clear', class: value ? 'critical' : 'on' };
                case 'int':
                    return { text: value || 'None', class: value ? 'warning' : '' };
                default:
                    return { text: String(value), class: '' };
            }
        }

        async function fetchTags() {
            try {
                const resp = await fetch(API_BASE + '/api/tags');
                const tags = await resp.json();
                if (tags.error) { console.error('Tag error:', tags.error); return; }

                const grid = document.getElementById('tagGrid');
                grid.innerHTML = '';
                for (const [key, config] of Object.entries(tagConfig)) {
                    const value = tags[key];
                    if (value === undefined) continue;
                    const formatted = formatTagValue(key, value, config);
                    const item = document.createElement('div');
                    item.className = 'tag-item';
                    item.innerHTML = '<span class="tag-name">' + config.label + '</span>'
                        + '<span class="tag-value ' + formatted.class + '">' + formatted.text + '</span>';
                    grid.appendChild(item);
                }
                document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
            } catch (err) { console.error('Failed to fetch tags:', err); }
        }

        async function fetchFaults() {
            try {
                const resp = await fetch(API_BASE + '/api/faults');
                const data = await resp.json();
                if (data.error) { console.error('Fault error:', data.error); return; }

                const list = document.getElementById('faultList');
                const countBadge = document.getElementById('faultCount');
                const activeFaults = data.faults.filter(f => f.severity !== 'info');

                if (activeFaults.length === 0) {
                    list.innerHTML = '<div class="fault-item"><div class="fault-title" style="color: #00ff88;">No Active Faults</div><div class="fault-desc">System operating normally</div></div>';
                    countBadge.textContent = 'OK';
                    countBadge.className = 'status-badge status-ok';
                } else {
                    list.innerHTML = '';
                    for (const fault of activeFaults) {
                        const item = document.createElement('div');
                        item.className = 'fault-item ' + fault.severity;
                        item.innerHTML = '<div class="fault-title">[' + fault.code + '] ' + fault.title + '</div>'
                            + '<div class="fault-desc">' + fault.description + '</div>';
                        list.appendChild(item);
                    }
                    countBadge.textContent = activeFaults.length + ' Active';
                    countBadge.className = 'status-badge status-' + activeFaults[0].severity;
                }
            } catch (err) { console.error('Failed to fetch faults:', err); }
        }

        function typewriterEffect(elementId, text, speed) {
            const el = document.getElementById(elementId);
            el.textContent = '';
            let i = 0;
            const timer = setInterval(() => {
                el.textContent += text[i++];
                el.scrollTop = el.scrollHeight;
                if (i >= text.length) clearInterval(timer);
            }, speed);
        }

        async function runDiagnosis() {
            const question = document.getElementById('questionInput').value;
            const resultDiv = document.getElementById('diagnosisResult');
            const latencyDiv = document.getElementById('diagnosisLatency');
            const modelBadge = document.getElementById('diagnosisModel');
            const thinkBlock = document.getElementById('think-block');

            resultDiv.style.display = 'block';
            resultDiv.textContent = 'Analyzing...';
            thinkBlock.style.display = 'none';
            latencyDiv.style.display = 'none';

            addHistoryEvent('diag', 'Diagnosis requested: ' + question.substring(0, 50));

            try {
                const resp = await fetch(API_BASE + '/api/diagnose', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ question })
                });
                const data = await resp.json();

                // Parse chain-of-thought if present
                const thinkMatch = data.answer.match(/<think>([\\s\\S]*?)<\\/think>/);
                const thinkText = thinkMatch ? thinkMatch[1].trim() : '';
                const answerText = thinkMatch
                    ? data.answer.replace(/<think>[\\s\\S]*?<\\/think>/, '').trim()
                    : data.answer;

                if (thinkText) {
                    thinkBlock.style.display = 'block';
                    thinkBlock.open = true;
                    typewriterEffect('think-text', thinkText, 12);
                    setTimeout(() => typewriterEffect('diagnosisResult', answerText, 20),
                        Math.min(thinkText.length * 12, 3000) + 500);
                } else {
                    resultDiv.textContent = answerText;
                }

                latencyDiv.style.display = 'block';
                const latencyEl = document.getElementById('latencyValue');
                latencyEl.textContent = data.latency_ms + 'ms';
                latencyEl.className = 'latency-badge ' + (data.latency_ms < 5000 ? 'fast' : 'slow');
                modelBadge.textContent = data.model;

                addHistoryEvent('diag', 'Diagnosis complete (' + data.latency_ms + 'ms) via ' + data.model);

            } catch (err) {
                resultDiv.textContent = 'Error: ' + err.message;
            }
        }

        function quickDiagnose() {
            document.getElementById('questionInput').value = 'Give me a quick status check of this equipment.';
            runDiagnosis();
        }

        async function injectFault(type) {
            await fetch(API_BASE + '/api/inject-fault/' + type, { method: 'POST' });
            if (type === 'clear') {
                addHistoryEvent('clear', 'Fault cleared - motor restarted');
            } else {
                const labels = { jam: 'Conveyor jam', slip: 'Belt slip', estop: 'E-Stop pressed' };
                addHistoryEvent('fault', (labels[type] || type) + ' injected');
            }
            fetchSpeedFusion();
        }

        let prevFusionStatus = 'MATCH';

        async function fetchSpeedFusion() {
            try {
                const resp = await fetch(API_BASE + '/api/speed-fusion');
                const data = await resp.json();

                const plcBar = document.getElementById('plcBar');
                const visualBar = document.getElementById('visualBar');
                const mismatchValue = document.getElementById('mismatchValue');
                const warning = document.getElementById('mismatchWarning');
                const panel = document.getElementById('fusionPanel');
                const badge = document.getElementById('fusionStatus');
                const detail = document.getElementById('mismatchDetail');
                const banner = document.getElementById('mismatch-banner');

                const plcPct = Math.min(100, Math.max(0, data.plc_speed_pct));
                const visPct = Math.min(100, Math.max(0, data.visual_speed_pct));
                plcBar.style.width = plcPct + '%';
                plcBar.textContent = data.plc_speed_pct + '%';
                visualBar.style.width = visPct + '%';
                visualBar.textContent = data.visual_speed_pct + '%';
                mismatchValue.textContent = data.mismatch_pct + '%';

                if (data.mismatch_pct > 20) {
                    mismatchValue.style.color = '#ff4444';
                    warning.style.display = 'block';
                    banner.style.display = 'block';
                    panel.classList.add('critical-flash');
                    badge.textContent = data.status;
                    badge.className = 'status-badge status-critical';
                    if (data.status === 'JAM') {
                        detail.textContent = 'PLC commanding ' + data.plc_speed_pct + '% but belt at ' + data.visual_speed_pct + '% - possible jam';
                        banner.textContent = 'SPEED MISMATCH DETECTED - POSSIBLE JAM - MOTOR AT ' + data.plc_speed_pct + '% / BELT AT ' + data.visual_speed_pct + '%';
                    } else {
                        detail.textContent = 'Belt slipping: expected ' + data.plc_speed_pct + '%, measured ' + data.visual_speed_pct + '%';
                        banner.textContent = 'SPEED MISMATCH DETECTED - BELT SLIPPING';
                    }
                    if (prevFusionStatus === 'MATCH') {
                        addHistoryEvent('fault', data.status + ' detected - mismatch ' + data.mismatch_pct + '%');
                    }
                } else if (data.mismatch_pct > 10) {
                    mismatchValue.style.color = '#ffaa00';
                    warning.style.display = 'none';
                    banner.style.display = 'none';
                    panel.classList.remove('critical-flash');
                    badge.textContent = data.status;
                    badge.className = 'status-badge status-warning';
                } else {
                    mismatchValue.style.color = '#00ff88';
                    warning.style.display = 'none';
                    banner.style.display = 'none';
                    panel.classList.remove('critical-flash');
                    badge.textContent = 'MATCH';
                    badge.className = 'status-badge status-ok';
                    if (prevFusionStatus !== 'MATCH' && prevFusionStatus !== data.status) {
                        addHistoryEvent('clear', 'Speed fusion recovered - MATCH');
                    }
                }
                prevFusionStatus = data.status;
            } catch (err) { console.error('Failed to fetch speed fusion:', err); }
        }

        // Initial load
        fetchTags();
        fetchFaults();
        fetchSpeedFusion();

        // Auto-refresh every 2 seconds
        setInterval(fetchTags, 2000);
        setInterval(fetchFaults, 2000);
        setInterval(fetchSpeedFusion, 2000);

        // Enter key triggers diagnosis
        document.getElementById('questionInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') runDiagnosis();
        });

        // Ctrl+F fullscreen toggle for filming
        document.addEventListener('keydown', e => {
            if (e.key === 'F' && e.ctrlKey) {
                e.preventDefault();
                if (!document.fullscreenElement) {
                    document.documentElement.requestFullscreen();
                } else {
                    document.exitFullscreen();
                }
            }
        });
    </script>
</body>
</html>"""


# ============================================================================
# Health check
# ============================================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "factorylm-demo",
        "matrix_api": MATRIX_API,
        "nvidia_api": bool(NVIDIA_API_KEY)
    }


if __name__ == "__main__":
    import uvicorn
    print("Starting Pi Factory Demo UI on http://0.0.0.0:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
