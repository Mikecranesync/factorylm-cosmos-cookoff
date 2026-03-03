#!/usr/bin/env python3
"""
FactoryLM Pi Factory — main entry point.

Starts the FastAPI edge gateway with optional belt tachometer support.
If VIDEO_SOURCE is set (e.g. VIDEO_SOURCE=0 for webcam), the belt
tachometer is activated and belt endpoints become available.

Usage:
    python server.py --port 8081
    VIDEO_SOURCE=0 python server.py --port 8081
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
import time

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("server")


def _start_belt_tachometer(video_source: str | int) -> None:
    """Initialize belt tachometer in a background thread.

    Grabs frames every 500ms, processes them, and caches results.
    The tachometer instance is injected into net.api.main so the
    belt endpoints can serve it.
    """
    try:
        import cv2
        from cosmos.belt_tachometer import BeltTachometer
    except ImportError as e:
        logger.warning("Belt tachometer unavailable: %s", e)
        return

    tach = BeltTachometer()

    # Inject into the API module so endpoints can access it
    import net.api.main as api
    api.belt_tachometer = tach

    # Hot-swap into publisher if CompactCom is running
    if hasattr(api, 'compactcom_publisher') and api.compactcom_publisher is not None:
        api.compactcom_publisher.set_belt_tachometer(tach)

    try:
        source = int(video_source)
    except (ValueError, TypeError):
        source = video_source

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        logger.warning("Cannot open video source %s — belt tachometer disabled", video_source)
        api.belt_tachometer = None
        return

    logger.info("Belt tachometer started (source=%s)", video_source)
    tick_count = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Video source lost — belt tachometer stopping")
                break

            result = tach.process_frame(frame)
            tick_count += 1

            # Log stats every 10 seconds (20 ticks at 500ms)
            if tick_count % 20 == 0:
                logger.info(
                    "Belt: %s | RPM: %.1f | Speed: %.0f%% | Offset: %dpx",
                    result["status"],
                    result["rpm"],
                    result["speed_pct"],
                    result["offset_px"],
                )

            time.sleep(0.5)
    finally:
        cap.release()
        logger.info("Belt tachometer stopped")


def main():
    parser = argparse.ArgumentParser(description="FactoryLM Pi Factory Server")
    parser.add_argument("--port", type=int, default=8081, help="API port (default: 8081)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Bind address")
    args = parser.parse_args()

    video_source = os.environ.get("VIDEO_SOURCE")
    plc_host = os.environ.get("PLC_HOST", "")
    plc_port = os.environ.get("PLC_PORT", "502")
    vfd_host = os.environ.get("VFD_HOST", "")
    cc_port = os.environ.get("PI_COMPACTCOM_PORT", "")
    hostname = socket.gethostname()

    # Hostname warning
    if hostname != "pi-factory":
        logger.warning(
            "Running on '%s' not 'pi-factory'. "
            "This is a dev machine. Real hardware may "
            "not be reachable.",
            hostname,
        )

    # Per-device status
    if plc_host:
        logger.info("PLC: %s:%s", plc_host, plc_port)
    else:
        logger.warning("PLC: not configured (PLC_HOST not set)")

    if vfd_host:
        logger.info("VFD: %s", vfd_host)
    else:
        logger.warning("VFD: not configured (VFD_HOST not set)")

    if cc_port:
        logger.info("CompactCom: port %s", cc_port)

    if video_source is not None:
        logger.info("VIDEO_SOURCE=%s — starting belt tachometer", video_source)
        t = threading.Thread(
            target=_start_belt_tachometer,
            args=(video_source,),
            daemon=True,
        )
        t.start()
        # Give the tachometer a moment to initialize
        time.sleep(1.0)
    else:
        logger.info("No VIDEO_SOURCE — running without belt tachometer")

    logger.info("Starting API server on %s:%d", args.host, args.port)
    uvicorn.run(
        "net.api.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
