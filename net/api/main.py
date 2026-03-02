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

WIZARD_PATH = Path(__file__).parent.parent / "portal" / "wizard.html"


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
    yield
    poller.stop()
    logger.info("Pi Factory Net stopped")


app = FastAPI(
    title="Pi Factory Net",
    version="1.0.0",
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
    """Redirect to /setup."""
    return RedirectResponse(url="/setup", status_code=302)


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
    
    return {
        "gateway_id": _get_gateway_id(),
        "mode": MODE,
        "plc": {
            "connected": poller.plc_connected,
            "polling": poller.is_running,
            "ip": poller._plc_ip,
            "port": poller._plc_port,
            "active_plc_id": active_plc["plc_id"] if active_plc else None,
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
