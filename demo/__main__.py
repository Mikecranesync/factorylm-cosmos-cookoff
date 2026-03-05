#!/usr/bin/env python3
"""
FactoryLM Demo — Cosmos Cookoff 2026
=====================================
Three-mode CLI for industrial AI diagnosis, live dashboard, and video reel.

Usage:
    python -m demo diagnose --mock
    python -m demo diagnose --simulate-plc jam --image demo/clips/screenshot.png
    python -m demo dashboard
    python -m demo video-reel --input recordings/raw --output output/demo-reel.mp4
"""

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    for env_file in [".env", ".env.demo"]:
        if Path(env_file).exists():
            load_dotenv(env_file)
            break
except ImportError:
    pass

from demo._paths import BASE_PATH, CLIPS_DIR, OUTPUT_DIR

VERSION = "3.1.0"
BANNER = f"""
 FactoryLM Demo v{VERSION} — Cosmos Cookoff 2026
 ─────────────────────────────────────────────
 Base: {BASE_PATH}
"""


def cmd_diagnose(args):
    """Run Cosmos R2 diagnosis: image/video + PLC tags -> chain-of-thought."""
    from demo.diagnosis_engine import main as diag_main

    # Build argv for diagnosis_engine
    argv = []
    if args.image:
        argv += ["--image", args.image]
    elif args.video:
        argv += ["--video", args.video]
    else:
        # Default image
        default_img = CLIPS_DIR / "screenshot.png"
        if default_img.exists():
            argv += ["--image", str(default_img)]
        else:
            pngs = sorted(CLIPS_DIR.glob("*.png"))
            if pngs:
                argv += ["--image", str(pngs[0])]
            else:
                print("Error: No image found. Use --image <path> or add a PNG to demo/clips/")
                sys.exit(1)

    if args.mock:
        argv += ["--simulate-plc", "jam"]
    elif args.simulate_plc:
        argv += ["--simulate-plc", args.simulate_plc]
    elif args.live_plc:
        argv += ["--live-plc"]
        if args.plc_host:
            argv += ["--plc-host", args.plc_host]
    elif args.plc_json:
        argv += ["--plc-json", args.plc_json]

    if args.question:
        argv += ["--question", args.question]
    if args.url:
        argv += ["--url", args.url]
    if args.json:
        argv += ["--json"]

    sys.argv = ["demo.diagnosis_engine"] + argv
    diag_main()


def cmd_dashboard(args):
    """Launch Matrix dashboard + optional MockPLC feeder + Cosmos watcher."""
    procs = []

    def cleanup(sig=None, frame=None):
        for p in procs:
            try:
                p.terminate()
            except OSError:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    matrix_port = str(args.port)
    matrix_url = f"http://localhost:{matrix_port}"

    # Start Matrix API dashboard
    print(f"Starting Matrix dashboard on :{matrix_port}...")
    matrix_cmd = [
        sys.executable, "-m", "uvicorn",
        "services.matrix.app:app",
        "--host", "0.0.0.0", "--port", matrix_port,
    ]
    procs.append(subprocess.Popen(matrix_cmd, cwd=str(BASE_PATH)))

    # Start MockPLC feeder (unless --live-plc)
    if not args.live_plc:
        bridge_path = BASE_PATH / "sim" / "factoryio_bridge.py"
        if bridge_path.exists():
            print("Starting MockPLC data feeder...")
            bridge_cmd = [sys.executable, str(bridge_path), "--sim"]
            procs.append(subprocess.Popen(bridge_cmd, cwd=str(BASE_PATH)))

    # Optionally start Cosmos watcher
    if args.watcher:
        print("Starting Cosmos incident watcher...")
        watcher_cmd = [
            sys.executable, "-m", "cosmos.watcher",
            "--matrix-url", matrix_url,
        ]
        procs.append(subprocess.Popen(watcher_cmd, cwd=str(BASE_PATH)))

    print(f"\nDashboard: {matrix_url}")
    print("Press Ctrl+C to stop all services.\n")

    # Wait for processes
    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        cleanup()


def cmd_video_reel(args):
    """Chain: ingest -> analyze -> select highlights -> build reel."""
    from video.ingester import run_ingester
    from video.cosmos_analyzer import run_analyzer
    from video.highlight_selector import select_highlights
    from video.short_builder import concatenate_clips

    matrix_url = args.matrix_url
    input_dir = args.input
    output_file = args.output
    top_n = args.top

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Video reel pipeline: {input_dir} -> {output_file}")
    print(f"  Matrix: {matrix_url}, top {top_n} highlights\n")

    # Run highlight selection and build
    highlights = select_highlights(matrix_url=matrix_url, top=top_n)
    if not highlights:
        print("No highlights found. Run ingester + analyzer first, or use:")
        print(f"  python video/ingester.py --input {input_dir}")
        print(f"  python video/cosmos_analyzer.py")
        sys.exit(1)

    clip_files = [h["file"] for h in highlights if Path(h["file"]).exists()]
    if not clip_files:
        print("Highlight clips not found on disk.")
        sys.exit(1)

    success = concatenate_clips(clip_files, output_file)
    if not success:
        sys.exit(1)
    print(f"\nDone: {output_file}")


def cmd_test(args):
    """Run the test session."""
    from demo.test_session import main as test_main
    argv = []
    if args.quick:
        argv.append("--quick")
    if args.skip_plc:
        argv.append("--skip-plc")
    if args.skip_vllm:
        argv.append("--skip-vllm")
    sys.argv = ["demo.test_session"] + argv
    test_main()


def cmd_capture(args):
    """Capture Factory I/O screenshot or recording."""
    from demo.capture_fio import main as capture_main
    sys.argv = ["demo.capture_fio"] + args.capture_args
    capture_main()


def cmd_watch(args):
    """Start Cosmos incident watcher."""
    from cosmos.watcher import main as watcher_main
    sys.argv = ["cosmos.watcher"]
    if args.matrix_url:
        sys.argv += ["--matrix-url", args.matrix_url]
    watcher_main()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m demo",
        description="FactoryLM Demo — Cosmos Cookoff 2026",
    )
    parser.add_argument("--version", action="version", version=f"FactoryLM Demo v{VERSION}")
    sub = parser.add_subparsers(dest="command", help="Demo mode")

    # --- diagnose ---
    p_diag = sub.add_parser("diagnose", help="Run Cosmos R2 diagnosis on image/video + PLC data")
    media = p_diag.add_mutually_exclusive_group()
    media.add_argument("--image", help="Path to factory image (PNG/JPG)")
    media.add_argument("--video", help="Path to factory video (MP4)")
    p_diag.add_argument("--mock", action="store_true", help="Use MockPLC jam scenario (judges: start here)")
    p_diag.add_argument("--simulate-plc", choices=["normal", "jam", "estop", "idle", "overheat"])
    p_diag.add_argument("--live-plc", action="store_true", help="Read live PLC via Modbus TCP")
    p_diag.add_argument("--plc-host", default="192.168.1.100")
    p_diag.add_argument("--plc-json", help="Path to PLC register JSON snapshot")
    p_diag.add_argument("--question", help="Ask a specific question")
    p_diag.add_argument("--url", default=None, help="Override vLLM endpoint URL")
    p_diag.add_argument("--json", action="store_true", help="Output as JSON")

    # --- dashboard ---
    p_dash = sub.add_parser("dashboard", help="Launch live web dashboard + PLC polling")
    p_dash.add_argument("--port", type=int, default=8000, help="Dashboard port (default: 8000)")
    p_dash.add_argument("--live-plc", action="store_true", help="Use real PLC instead of MockPLC")
    p_dash.add_argument("--watcher", action="store_true", help="Also start Cosmos incident watcher")

    # --- video-reel ---
    p_vid = sub.add_parser("video-reel", help="Build highlight reel from analyzed video clips")
    p_vid.add_argument("--input", default="recordings/raw", help="Raw video input directory")
    p_vid.add_argument("--output", default="output/demo-reel.mp4", help="Output video path")
    p_vid.add_argument("--top", type=int, default=5, help="Number of top highlights")
    p_vid.add_argument("--matrix-url", default=os.getenv("MATRIX_URL", "http://localhost:8000"))

    # --- utility subcommands ---
    p_test = sub.add_parser("test", help="Run comprehensive test session")
    p_test.add_argument("--quick", action="store_true")
    p_test.add_argument("--skip-plc", action="store_true")
    p_test.add_argument("--skip-vllm", action="store_true")

    p_cap = sub.add_parser("capture", help="Capture Factory I/O screenshot/recording")
    p_cap.add_argument("capture_args", nargs="*", default=[])

    p_watch = sub.add_parser("watch", help="Start Cosmos incident watcher")
    p_watch.add_argument("--matrix-url", default=os.getenv("MATRIX_URL", "http://localhost:8000"))

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        print(BANNER)
        parser.print_help()
        sys.exit(0)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(BANNER)

    dispatch = {
        "diagnose": cmd_diagnose,
        "dashboard": cmd_dashboard,
        "video-reel": cmd_video_reel,
        "test": cmd_test,
        "capture": cmd_capture,
        "watch": cmd_watch,
    }

    handler = dispatch.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
