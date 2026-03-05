# FactoryLM Demo — Cosmos Cookoff 2026

Three-mode CLI for industrial AI diagnosis, live dashboard, and video highlight reel.

## Quick Start

```bash
pip install -r requirements.txt

# Mode 1: Diagnose (MockPLC — no hardware needed)
python -m demo diagnose --mock

# Mode 2: Dashboard (live web UI at :8000)
python -m demo dashboard

# Mode 3: Video reel (build highlight MP4 from analyzed clips)
python -m demo video-reel --input recordings/raw --output output/demo-reel.mp4
```

## All Subcommands

| Command | Description |
|---------|-------------|
| `diagnose` | Image/video + PLC tags -> Cosmos R2 -> chain-of-thought diagnosis |
| `dashboard` | Live web UI with PLC polling, fault history, auto-incident detection |
| `video-reel` | Build highlight reel from Cosmos-scored video clips |
| `test` | Run comprehensive test session (5 scenarios + PLC + Q&A) |
| `capture` | Capture Factory I/O screenshots or recordings |
| `watch` | Start Cosmos incident watcher (polls Matrix API) |

## Diagnose Flags

| Flag | Description |
|------|-------------|
| `--mock` | Use MockPLC jam scenario (judges: start here) |
| `--simulate-plc {normal,jam,estop,idle,overheat}` | Simulated PLC scenario |
| `--live-plc` | Read real PLC via Modbus TCP |
| `--plc-host IP` | PLC IP address (default: 192.168.1.100) |
| `--image PATH` | Factory image (PNG/JPG) |
| `--video PATH` | Factory video (MP4) |
| `--question TEXT` | Ask a specific question |
| `--json` | Output as JSON |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_URL` | `http://localhost:8000/v1/chat/completions` | Cosmos R2 vLLM endpoint |
| `PLC_HOST` | `192.168.1.100` | PLC IP for Modbus TCP |
| `MATRIX_URL` | `http://localhost:8000` | Matrix API dashboard URL |
| `NVIDIA_COSMOS_API_KEY` | (none) | NVIDIA cloud API key (optional) |
| `VIDEO_SOURCE` | `0` | Webcam index or video file path |

Copy `.env.demo` to `.env` and fill in your values.

## PyInstaller Build

```bash
# Debug (onedir)
pyinstaller --onedir demo/__main__.py

# Production (onedir with spec)
pyinstaller --onedir --name FactoryLM-Demo FactoryLM-Demo.spec

# Single file
pyinstaller --onefile --name FactoryLM-Demo FactoryLM-Demo.spec
```

## Judging Criteria Evidence Map

| Criteria | Evidence |
|----------|---------|
| **Quality of Ideas** | First system to fuse live PLC Modbus + factory video through Cosmos R2. Chain-of-thought flags discrepancies between camera and PLC data. |
| **Technical Implementation** | 5/5 fault scenarios diagnosed. Real Micro 820 PLC + ATO VFD. Cosmos R2 via vLLM on L40S. 6-19s latency. |
| **Design** | Single `python -m demo diagnose --mock` runs entire pipeline. Built-in dashboard. MockPLC fallback. |
| **Impact** | Replaces $3-8K/seat/year diagnostic tools with open-source AI. Built by an actual maintenance tech. |

## Full Documentation

- [Technical Whitepaper](WHITEPAPER.md)
- [User Manual](USER_MANUAL.md)
- [Conveyor of Destiny Playbook](../docs/CONVEYOR_OF_DESTINY.md)
