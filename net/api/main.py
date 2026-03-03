"""
Pi Factory Net — Edge Gateway API

FastAPI backend serving the setup wizard and PLC management endpoints.
Reads FACTORYLM_NET_MODE env var: "real" (default) or "sim".

Run:
    uvicorn net.api.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from net.drivers.discovery import (
    DiscoveredPLC,
    fake_scan_result,
    load_template,
    scan_subnet,
)
from net.drivers.tag_extractor import extract_tags
from net.platform import get_wifi_scanner

_wifi_scanner = get_wifi_scanner()


def scan_wifi():
    return _wifi_scanner.scan_networks()


def connect_wifi(ssid, password):
    return _wifi_scanner.connect_network(ssid, password)
from net.services.poller import Poller
from cosmos.client import CosmosClient
from cosmos.reasoner import BeltVideoReasoner

# Try to import qrcode for QR generation
try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("net.api")

MODE = os.environ.get("FACTORYLM_NET_MODE", "real")
DB_PATH = os.environ.get("FACTORYLM_NET_DB", "net.db")

# Shared poller instance
poller = Poller(db_path=DB_PATH)

# Cosmos AI client (singleton)
cosmos_client = CosmosClient()

# Belt tachometer + reasoner (initialized when camera available)
belt_tachometer = None  # Set by simulate.py or external caller
belt_reasoner = BeltVideoReasoner()

# VFD reader (initialized during lifespan if VFD_HOST configured)
vfd_reader = None

# CompactCom server + publisher + command handler (when PI_COMPACTCOM_PORT is set)
compactcom_server = None    # PiCompactCom
compactcom_publisher = None  # Publisher
compactcom_cmd_handler = None  # PLCCommandHandler

WIZARD_PATH = Path(__file__).parent.parent / "portal" / "wizard.html"
PANEL_PATH = Path(__file__).parent.parent / "portal" / "panel.html"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PLCTestRequest(BaseModel):
    ip: str
    port: int = 502
    template: str = "micro820"


class PLCConfigRequest(BaseModel):
    ip: str
    port: int = 502
    brand: str = ""
    template: str = "micro820"
    custom_names: dict[str, str] | None = None


class PLCConfigWizardRequest(BaseModel):
    """Payload shape from the rewritten wizard's savePanel()."""
    name: str = "Live Dashboard"
    device_ip: str
    device_port: int = 502
    protocol: str = "modbus"
    tags: list[dict] | None = None


class PLCLiveRequest(BaseModel):
    """Payload from wizard's pollLiveData()."""
    ip: str
    port: int = 502
    tags: list[str] = []


class PLCExtractRequest(BaseModel):
    ip: str
    port: int = 502


class PLCNameTagRequest(BaseModel):
    plc_id: str
    modbus_path: str
    human_name: str


class WiFiConnectRequest(BaseModel):
    ssid: str
    password: str


# ---------------------------------------------------------------------------
# Database utilities
# ---------------------------------------------------------------------------

def _init_db():
    """Initialize or upgrade database schema."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    
    # Create tables
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
    
    # Create gateway_config table for storing gateway_id and other settings
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gateway_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    conn.commit()
    conn.close()


def _get_gateway_id() -> str:
    """Get or create the gateway_id."""
    _init_db()  # Ensure tables exist
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("SELECT value FROM gateway_config WHERE key = 'gateway_id'")
    row = cursor.fetchone()
    
    if row:
        gateway_id = row[0]
    else:
        # Generate new gateway_id
        gateway_id = f"flm-{uuid.uuid4().hex[:12]}"
        conn.execute("INSERT INTO gateway_config (key, value) VALUES (?, ?)",
                     ("gateway_id", gateway_id))
        conn.commit()
        logger.info(f"Generated new gateway_id: {gateway_id}")
    
    conn.close()
    return gateway_id


def _save_gateway_config(key: str, value: str):
    """Save a gateway config value."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO gateway_config (key, value) VALUES (?, ?)",
                 (key, value))
    conn.commit()
    conn.close()


def _get_active_plc() -> dict | None:
    """Get the currently active PLC config."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("""
        SELECT plc_id, ip, port, brand, template_name, tags_json, custom_names_json
        FROM plc_configs
        ORDER BY created_at DESC
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        "plc_id": row[0],
        "ip": row[1],
        "port": row[2],
        "brand": row[3],
        "template_name": row[4],
        "tags_json": row[5],
        "custom_names_json": row[6],
    }


def _save_tag_name(plc_id: str, modbus_path: str, human_name: str):
    """Save or update human name mapping for a tag."""
    conn = sqlite3.connect(DB_PATH)
    
    # Get current config
    cursor = conn.execute(
        "SELECT custom_names_json FROM plc_configs WHERE plc_id = ?",
        (plc_id,)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise ValueError(f"PLC {plc_id} not found")
    
    # Parse existing names
    custom_names = {}
    if row[0]:
        try:
            custom_names = json.loads(row[0])
        except json.JSONDecodeError:
            pass
    
    # Add or update
    custom_names[modbus_path] = human_name
    
    # Save back
    conn.execute(
        "UPDATE plc_configs SET custom_names_json = ? WHERE plc_id = ?",
        (json.dumps(custom_names), plc_id)
    )
    conn.commit()
    conn.close()
    logger.info(f"Saved tag name: {plc_id} / {modbus_path} → {human_name}")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Pi Factory Net starting (mode=%s, db=%s)", MODE, DB_PATH)
    _init_db()
    gateway_id = _get_gateway_id()
    logger.info(f"Gateway ID: {gateway_id}")

    # Auto-start poller when PLC_HOST is set (real PLC mode)
    plc_host = os.environ.get("PLC_HOST", "")
    if plc_host:
        plc_port = int(os.environ.get("PLC_PORT", "502"))
        logger.info("PLC_HOST=%s:%d — auto-starting poller", plc_host, plc_port)
        poller.configure(ip=plc_host, port=plc_port)
        poller.start()

    # Auto-start VFD reader when VFD_HOST is set
    global vfd_reader
    vfd_host = os.environ.get("VFD_HOST", "")
    if vfd_host:
        vfd_port = int(os.environ.get("VFD_PORT", "502"))
        vfd_slave = int(os.environ.get("VFD_SLAVE", "1"))
        from net.drivers.vfd_reader import VfdReader
        vfd_reader = VfdReader(host=vfd_host, port=vfd_port, slave=vfd_slave)
        if vfd_reader.connect():
            logger.info("VFD connected: %s:%d slave=%d", vfd_host, vfd_port, vfd_slave)
        else:
            logger.warning("VFD connection failed — running without VFD")
            vfd_reader = None

    # Auto-start CompactCom server when PI_COMPACTCOM_PORT is set
    global compactcom_server, compactcom_publisher, compactcom_cmd_handler
    cc_port_str = os.environ.get("PI_COMPACTCOM_PORT", "")
    if cc_port_str:
        from net.drivers.pi_compactcom import PiCompactCom
        from net.services.publisher import Publisher
        from net.services.plc_command_handler import PLCCommandHandler
        compactcom_server = PiCompactCom(port=int(cc_port_str))
        compactcom_server.start()
        compactcom_publisher = Publisher(
            compactcom=compactcom_server,
            poller=poller,
            belt_tachometer=belt_tachometer,
            vfd_reader=vfd_reader,
        )
        compactcom_publisher.start()
        compactcom_cmd_handler = PLCCommandHandler(
            compactcom=compactcom_server,
            publisher=compactcom_publisher,
        )
        compactcom_cmd_handler.start()
        logger.info("CompactCom server + publisher + command handler started on port %s", cc_port_str)

    yield
    if compactcom_cmd_handler:
        compactcom_cmd_handler.stop()
    if compactcom_publisher:
        compactcom_publisher.stop()
    if compactcom_server:
        compactcom_server.stop()
    poller.stop()
    logger.info("Pi Factory Net stopped")


app = FastAPI(
    title="Pi Factory Net",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handler — catch any unhandled errors and return JSON
# ---------------------------------------------------------------------------

from starlette.requests import Request
from starlette.responses import Response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> Response:
    """Catch unhandled exceptions and return a structured JSON error."""
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": str(exc),
            "path": request.url.path,
        },
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Serve the Live I/O Panel if available, otherwise redirect to wizard."""
    if PANEL_PATH.exists():
        return HTMLResponse(PANEL_PATH.read_text())
    return RedirectResponse(url="/setup", status_code=302)


@app.get("/panel", response_class=HTMLResponse)
async def live_panel():
    """Serve the Live I/O Panel."""
    if PANEL_PATH.exists():
        return HTMLResponse(PANEL_PATH.read_text())
    return HTMLResponse("<h1>panel.html not found</h1>", status_code=500)


@app.get("/setup", response_class=HTMLResponse)
async def setup_wizard():
    """Serve the 5-screen setup wizard."""
    if WIZARD_PATH.exists():
        return HTMLResponse(WIZARD_PATH.read_text())
    return HTMLResponse("<h1>wizard.html not found</h1>", status_code=500)


@app.get("/api/status")
async def gateway_status():
    """Gateway health check — PLC connection, WiFi, mode."""
    active_plc = _get_active_plc()
    plc_host = os.environ.get("PLC_HOST", "")
    hardware_mode = bool(plc_host)

    return {
        "gateway_id": _get_gateway_id(),
        "mode": MODE,
        "hardware_mode": hardware_mode,
        "plc": {
            "connected": poller.plc_connected,
            "polling": poller.is_running,
            "ip": plc_host or poller._plc_ip,
            "port": int(os.environ.get("PLC_PORT", "502")) if plc_host else poller._plc_port,
            "active_plc_id": active_plc["plc_id"] if active_plc else None,
            "source": "ModbusTagSource" if plc_host else "template",
        },
        "wifi": {
            "connected": True,  # TODO: real check on Pi
        },
        "latest_tags": poller.latest,
    }


@app.get("/api/gateway/id")
async def gateway_id():
    """Return the gateway ID for the wizard's Screen 1."""
    return {"id": _get_gateway_id()}


@app.get("/api/plc/scan")
async def plc_scan(subnet: str = Query(default="192.168.1.0/24")):
    """Scan subnet for Modbus TCP devices."""
    if MODE == "sim":
        devices = fake_scan_result()
    else:
        devices = await scan_subnet(subnet)

    return {
        "mode": MODE,
        "subnet": subnet,
        "devices": [
            {
                "ip": d.ip,
                "port": d.port,
                "protocol": getattr(d, "protocol", "Modbus TCP"),
                "brand": d.brand,
                "model": d.model,
                "template": d.template,
                "response_ms": d.response_ms,
                "status": "online",
            }
            for d in devices
        ],
    }


@app.post("/api/plc/extract")
async def plc_extract(req: PLCExtractRequest):
    """Run tag extractor on a PLC to discover tags automatically."""
    gateway_id = _get_gateway_id()
    
    logger.info(f"Starting tag extraction for {req.ip}:{req.port}")
    
    try:
        result = await extract_tags(
            gateway_id=gateway_id,
            plc_ip=req.ip,
            sim_mode=(MODE == "sim"),
        )
        
        if result is None:
            raise HTTPException(
                status_code=502,
                detail=f"Could not extract tags from {req.ip}:{req.port}"
            )
        
        return result.to_dict()
    
    except Exception as e:
        logger.error(f"Tag extraction failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Tag extraction failed: {str(e)}"
        )


@app.post("/api/plc/test")
async def plc_test(req: PLCTestRequest):
    """Single Modbus read to test connectivity and return current tag values."""
    template = load_template(req.template)
    if not template:
        raise HTTPException(status_code=400, detail=f"Unknown template: {req.template}")

    if MODE == "sim":
        from net.sim.plc_simulator import PLCSimulator
        sim = PLCSimulator(node_id="test-probe", db_path=None)
        sim._store_snapshot = lambda snap: None
        snap = sim.tick()
        return {
            "mode": "sim",
            "ip": req.ip,
            "port": req.port,
            "template": req.template,
            "tags": snap.to_dict(),
        }

    # Real mode — synchronous Modbus read in thread pool
    from net.drivers.modbus_reader import ModbusReader

    def _read():
        reader = ModbusReader(
            host=req.ip,
            port=req.port,
            template=template,
        )
        tags = reader.read_tags()
        reader.disconnect()
        return tags

    loop = asyncio.get_event_loop()
    tags = await loop.run_in_executor(None, _read)

    if tags is None:
        raise HTTPException(
            status_code=502,
            detail=f"Could not read from {req.ip}:{req.port}",
        )

    return {
        "mode": "real",
        "ip": req.ip,
        "port": req.port,
        "template": req.template,
        "tags": tags,
    }


@app.get("/api/plc/tags")
async def plc_tags():
    """Return saved tags for the active PLC."""
    active_plc = _get_active_plc()
    
    if not active_plc:
        return {
            "plc_id": None,
            "tags": None,
        }
    
    tags = None
    if active_plc["tags_json"]:
        try:
            tags = json.loads(active_plc["tags_json"])
        except json.JSONDecodeError:
            pass
    
    return {
        "plc_id": active_plc["plc_id"],
        "ip": active_plc["ip"],
        "port": active_plc["port"],
        "brand": active_plc["brand"],
        "template_name": active_plc["template_name"],
        "tags": tags,
    }


@app.get("/api/plc/live")
async def plc_live_get():
    """Return current live values for all tags (GET — legacy)."""
    tags = poller.latest
    if tags is None:
        return {"polling": False, "tags": None}
    return {"polling": True, "tags": tags}


@app.post("/api/plc/live")
async def plc_live_post(req: PLCLiveRequest):
    """Return live values filtered to requested tags (POST — wizard Screen 5).

    The wizard polls this at 500ms with {ip, port, tags: ["name1", ...]}.
    Response: {data: {tag_name: value, ...}}
    """
    all_tags = poller.latest

    if all_tags is None:
        # If poller isn't running yet, try to start it in sim mode
        if MODE == "sim" and not poller.is_running:
            poller.configure(ip=req.ip, port=req.port)
            poller.start()
            # Give it a beat to produce first snapshot
            await asyncio.sleep(0.25)
            all_tags = poller.latest

    if all_tags is None:
        return {"data": {}}

    # Filter to only the requested tag names
    if req.tags:
        data = {k: v for k, v in all_tags.items() if k in req.tags}
    else:
        data = {k: v for k, v in all_tags.items() if k not in ("timestamp", "node_id")}

    return {"data": data}


# Keep old endpoint as alias for backwards compatibility
@app.get("/api/tags/live")
async def live_tags():
    """Alias for /api/plc/live (deprecated, use /api/plc/live)."""
    return await plc_live_get()


@app.post("/api/plc/name_tag")
async def plc_name_tag(req: PLCNameTagRequest):
    """Save human name mapping for a tag."""
    try:
        _save_tag_name(req.plc_id, req.modbus_path, req.human_name)
        return {
            "status": "saved",
            "plc_id": req.plc_id,
            "modbus_path": req.modbus_path,
            "human_name": req.human_name,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to save tag name: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/plc/config")
async def plc_config(body: dict):
    """Save PLC configuration and start polling.

    Accepts both the legacy payload (ip, port, template, custom_names)
    and the wizard's new payload (name, device_ip, device_port, protocol, tags).
    """
    # Detect wizard payload vs legacy payload
    if "device_ip" in body:
        # Wizard shape: {name, device_ip, device_port, protocol, tags}
        ip = body["device_ip"]
        port = int(body.get("device_port", 502))
        protocol = body.get("protocol", "modbus")
        wizard_tags = body.get("tags", [])
        template_name = body.get("template", "micro820")
        brand = body.get("brand", "")
        custom_names = None

        # Build a template-like dict from the wizard's tag list
        template = load_template(template_name)
        if not template:
            template = {"coils": {}, "registers": {}}

        # Save wizard tag list as JSON for retrieval
        tags_json = json.dumps(wizard_tags) if wizard_tags else json.dumps(template)
    else:
        # Legacy shape: {ip, port, template, brand, custom_names}
        ip = body.get("ip", "")
        port = int(body.get("port", 502))
        template_name = body.get("template", "micro820")
        brand = body.get("brand", "")
        custom_names = body.get("custom_names")

        template = load_template(template_name)
        if not template:
            raise HTTPException(status_code=400, detail=f"Unknown template: {template_name}")
        tags_json = json.dumps(template)

    plc_id = f"plc-{ip}"

    # Save config to SQLite
    poller.save_plc_config(
        plc_id=plc_id,
        ip=ip,
        port=port,
        brand=brand,
        template_name=template_name,
        tags_json=tags_json,
        custom_names_json=json.dumps(custom_names) if custom_names else None,
    )

    # Configure and start poller
    poller.configure(
        ip=ip,
        port=port,
        template=template,
        custom_names=custom_names,
    )

    if not poller.is_running:
        poller.start()

    return {
        "status": "configured",
        "plc_id": plc_id,
        "polling": poller.is_running,
        "mode": MODE,
    }


@app.post("/api/cosmos/diagnose")
async def cosmos_diagnose():
    """Run Cosmos Reason 2 diagnosis on current PLC tags.

    Returns flat JSON with incident_id, summary, root_cause, confidence,
    reasoning, suggested_checks, cosmos_model, and timestamp.
    Works with both real NVIDIA API and stub mode.
    """
    tags = poller.latest
    if tags is None:
        raise HTTPException(
            status_code=503,
            detail="No PLC data available — configure and start polling first",
        )

    active_plc = _get_active_plc()
    node_id = active_plc["plc_id"] if active_plc else "unknown"
    incident_id = f"diag-{uuid.uuid4().hex[:8]}"

    loop = asyncio.get_event_loop()
    insight = await loop.run_in_executor(
        None,
        lambda: cosmos_client.analyze_incident(
            incident_id=incident_id,
            node_id=node_id,
            tags=tags,
        ),
    )

    return {
        "incident_id": insight.incident_id,
        "summary": insight.summary,
        "root_cause": insight.root_cause,
        "confidence": insight.confidence,
        "reasoning": insight.reasoning,
        "suggested_checks": insight.suggested_checks,
        "cosmos_model": insight.cosmos_model,
        "timestamp": insight.timestamp.isoformat(),
    }


@app.get("/api/wifi/scan")
async def wifi_scan():
    """Scan for WiFi networks (mock on macOS, real on Pi)."""
    try:
        networks = scan_wifi()
        return {"networks": networks}
    except RuntimeError as e:
        logger.warning(f"WiFi scan unavailable: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": "wifi_unavailable", "detail": str(e)},
        )
    except Exception as e:
        logger.error(f"WiFi scan failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "wifi_scan_failed", "detail": str(e)},
        )


@app.post("/api/wifi/connect")
async def wifi_connect_endpoint(req: WiFiConnectRequest):
    """Connect to a WiFi network."""
    try:
        result = connect_wifi(req.ssid, req.password)
        return result
    except RuntimeError as e:
        logger.warning(f"WiFi connect unavailable: {e}")
        return JSONResponse(
            status_code=503,
            content={"error": "wifi_unavailable", "detail": str(e)},
        )
    except Exception as e:
        logger.error(f"WiFi connect failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "wifi_connect_failed", "detail": str(e)},
        )


@app.get("/api/gateway/qr")
async def gateway_qr():
    """Generate and return QR code PNG for gateway pairing."""
    if not QRCODE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="qrcode library not installed"
        )
    
    gateway_id = _get_gateway_id()
    
    # Generate pairing URL/data
    pairing_data = f"flm://gateway/{gateway_id}"
    
    try:
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(pairing_data)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to PNG bytes
        img_bytes = BytesIO()
        img.save(img_bytes, format="PNG")
        img_bytes.seek(0)
        
        return StreamingResponse(img_bytes, media_type="image/png")
    
    except Exception as e:
        logger.error(f"QR code generation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"QR code generation failed: {str(e)}"
        )


# ---------------------------------------------------------------------------
# Belt tachometer endpoints (V1.5)
# ---------------------------------------------------------------------------

@app.get("/api/belt/status")
async def belt_status():
    """Return current belt tachometer readings: RPM, speed %, offset, status.

    Lightweight — no AI call. Returns 503 if no camera / tachometer.
    """
    if belt_tachometer is None:
        raise HTTPException(
            status_code=503,
            detail="Belt tachometer not available — no camera connected",
        )

    return {
        "rpm": belt_tachometer.rpm,
        "speed_pct": round(belt_tachometer.speed_pct, 1),
        "offset_px": belt_tachometer.offset_px,
        "status": belt_tachometer.status.value,
        "tape_detected": belt_tachometer.tape_detected,
        "calibrated": belt_tachometer._calibrated,
        "baseline_rpm": round(belt_tachometer._baseline_rpm, 1),
    }


@app.post("/api/belt/diagnose")
async def belt_diagnose():
    """Trigger full Cosmos R2 video analysis on the belt.

    Sends the last 5 seconds of video + PLC tags + tachometer data to
    the AI for diagnosis. Skips the expensive AI call if belt is NORMAL.
    """
    if belt_tachometer is None:
        raise HTTPException(
            status_code=503,
            detail="Belt tachometer not available — no camera connected",
        )

    from cosmos.belt_tachometer import BeltStatus

    # Skip AI call if belt is healthy — no point asking "what's wrong?"
    if belt_tachometer.status == BeltStatus.NORMAL:
        return {
            "skipped": True,
            "reason": "Belt status is NORMAL — no diagnosis needed",
            "status": belt_tachometer.status.value,
            "rpm": belt_tachometer.rpm,
        }

    # Gather data for diagnosis
    tach_data = {
        "rpm": belt_tachometer.rpm,
        "speed_pct": belt_tachometer.speed_pct,
        "offset_px": belt_tachometer.offset_px,
        "status": belt_tachometer.status.value,
    }

    tags = poller.latest or {}
    video_bytes = belt_tachometer.get_clip_bytes()

    # Run diagnosis (may be async-heavy — run in executor)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: belt_reasoner.diagnose_belt_video(
            video_bytes=video_bytes,
            tachometer_data=tach_data,
            tags=tags,
        ),
    )

    return result


@app.get("/api/belt/stream")
async def belt_stream():
    """Live MJPEG video stream with tachometer overlay.

    Open in a browser: http://host:port/api/belt/stream
    """
    if belt_tachometer is None:
        raise HTTPException(
            status_code=503,
            detail="Belt tachometer not available — no camera connected",
        )

    import cv2

    video_source = os.environ.get("VIDEO_SOURCE", "0")
    try:
        source = int(video_source)
    except ValueError:
        source = video_source

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise HTTPException(status_code=503, detail="Cannot open video source")

    def generate():
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # Process through tachometer and annotate
                belt_tachometer.process_frame(frame)
                annotated = belt_tachometer.annotate_frame(frame)

                # Encode as JPEG
                _, jpeg = cv2.imencode(".jpg", annotated)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + jpeg.tobytes()
                    + b"\r\n"
                )
        finally:
            cap.release()

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ---------------------------------------------------------------------------
# VFD endpoints (V2)
# ---------------------------------------------------------------------------

@app.get("/api/vfd/status")
async def vfd_status():
    """Return current VFD register values, or 'not configured' message."""
    if vfd_reader is None:
        return {"vfd_connected": False, "message": "VFD not configured (set VFD_HOST)"}
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, vfd_reader.tick)
    return data


@app.get("/api/conflicts")
async def conflicts():
    """Cross-reference PLC + VFD + belt vision for conflict detection."""
    from net.diagnosis.vfd_conflicts import detect_conflicts

    plc_tags = poller.latest or {}

    vfd_tags = None
    if vfd_reader:
        loop = asyncio.get_event_loop()
        vfd_tags = await loop.run_in_executor(None, vfd_reader.tick)

    belt = None
    if belt_tachometer:
        belt = {
            "belt_rpm": belt_tachometer.rpm,
            "belt_speed_pct": belt_tachometer.speed_pct,
            "belt_status": belt_tachometer.status.value,
        }

    result = detect_conflicts(plc_tags, vfd_tags, belt)
    return {
        "conflicts": [
            {
                "code": c.code,
                "severity": c.severity,
                "title": c.title,
                "description": c.description,
            }
            for c in result
        ],
        "vfd_connected": vfd_tags is not None and vfd_tags.get("vfd_connected", False),
    }


# ---------------------------------------------------------------------------
# CompactCom endpoints (V2)
# ---------------------------------------------------------------------------

@app.get("/api/compactcom/status")
async def compactcom_status():
    """Return CompactCom server and publisher status."""
    cc_port = os.environ.get("PI_COMPACTCOM_PORT", "")
    return {
        "enabled": bool(cc_port),
        "port": int(cc_port) if cc_port else None,
        "server_running": compactcom_server.is_running if compactcom_server else False,
        "publisher_running": compactcom_publisher.is_running if compactcom_publisher else False,
        "commands": compactcom_publisher.commands if compactcom_publisher else None,
    }


@app.get("/api/compactcom/registers")
async def compactcom_registers():
    """Return named CompactCom register values for debug/dashboard."""
    if compactcom_server is None:
        return {"published": None, "commands": None}

    raw = compactcom_server.read_published()
    published = {
        "belt_rpm": raw[0],
        "belt_speed_pct": raw[1],
        "belt_status": raw[2],
        "belt_offset_px": raw[3],
        "vfd_output_hz": raw[4],
        "vfd_output_amps": raw[5],
        "vfd_fault_code": raw[6],
        "ai_fault_code": raw[7],
        "ai_confidence": raw[8],
        "pi_heartbeat": raw[9],
    }

    cmds = compactcom_server.read_commands()
    return {"published": published, "commands": cmds}


@app.get("/api/compactcom/commands")
async def compactcom_commands():
    """Return PLC command history and current decoded state."""
    if compactcom_cmd_handler is None:
        return {
            "commands_received": [],
            "current_state": {
                "cmd_run": 0,
                "cmd_speed_pct": 0.0,
                "cmd_mode": "manual",
                "cmd_reset_fault": 0,
            },
        }
    return {
        "commands_received": compactcom_cmd_handler.history,
        "current_state": compactcom_cmd_handler.current_state,
    }
