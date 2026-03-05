# FactoryLM Vision — NVIDIA Cosmos Cookoff 2026

> Fuse live video + PLC telemetry through **Cosmos Reason2-8B** to diagnose factory faults in seconds — not hours.

**Entry:** NVIDIA Cosmos Cookoff 2026
**Model:** nvidia/Cosmos-Reason2-8B via vLLM 0.15.1
**Hardware:** Allen-Bradley Micro 820 PLC, Raspberry Pi edge gateway, Vast.ai L40S GPU
**Submission:** March 5, 2026

---

## The Problem

Factory technicians spend **40% of their time** diagnosing equipment faults — walking to machines, reading HMI screens, cross-referencing error codes against paper manuals. PLCs record motor current, temperature, and pressure at 10 Hz. Cameras watch production lines. But nobody connects these observations into a coherent diagnosis automatically.

The cost: **$50,000/hour** in unplanned downtime (ARC Advisory Group, 2024) and **$170B/year** in workplace injury costs (U.S. BLS).

## The Solution

FactoryLM Vision feeds **live video** and **real-time PLC registers** into NVIDIA Cosmos Reason2-8B. The model reasons across both modalities — seeing what the camera sees and reading what the instruments report — to produce a structured diagnosis in **6-19 seconds**.

A motor drawing 5.8A while the conveyor shows zero speed? Cosmos R2 identifies the mechanical jam that neither source alone could surface.

---

## Quick Start (3 commands)

```bash
git clone https://github.com/Mikecranesync/factorylm-cosmos-cookoff.git
cd factorylm-cosmos-cookoff
pip install requests pyyaml pymodbus mss
```

### Run a diagnosis (no hardware needed)

```bash
# Set your vLLM endpoint (or use our default)
export VLLM_URL=http://localhost:8001/v1/chat/completions

# Diagnose a simulated conveyor jam (MockPLC — no hardware needed)
python -m demo diagnose --mock

# Try other scenarios: normal, estop, overheat, idle
python -m demo diagnose --simulate-plc overheat

# Ask a specific question
python -m demo diagnose --simulate-plc jam \
    --question "Is it safe to restart the conveyor?"
```

### Run against a live PLC

```bash
python -m demo diagnose --live-plc --plc-host 192.168.1.100
```

---

## Architecture

```
  Technician (phone / Telegram / browser)
         |
         v
  ┌──────────────────────────────────────────────────┐
  │  CLOUD AI LAYER (Vast.ai L40S GPU)               │
  │                                                    │
  │  vLLM 0.15.1 → nvidia/Cosmos-Reason2-8B           │
  │  OpenAI-compatible /v1/chat/completions            │
  │                                                    │
  │  diagnosis_engine.py                               │
  │    1. Encode image/video as base64                 │
  │    2. Read PLC registers (Modbus TCP)              │
  │    3. Run 8-code fault pre-filter                  │
  │    4. Build multimodal prompt (media + telemetry)  │
  │    5. POST to Cosmos R2                            │
  │    6. Parse <think> chain-of-thought               │
  │    7. Return structured diagnosis                  │
  └───────────────────┬──────────────────────────────┘
                      │ Tailscale VPN / SSH tunnel
                      v
  ┌─────────────────────────────────────────────────┐
  │  EDGE LAYER                                      │
  │                                                   │
  │  Raspberry Pi (192.168.1.30)                      │
  │    └─ Edge gateway: Modbus TCP → CompactCom       │
  │                                                   │
  │  PLC Laptop                                       │
  │    └─ Factory I/O "From A to B" scene             │
  │    └─ Allen-Bradley Micro 820 @ 192.168.1.100     │
  └───────────────────┬─────────────────────────────┘
                      │ Modbus TCP (port 502)
                      v
  ┌─────────────────────────────────────────────────┐
  │  PHYSICAL HARDWARE                               │
  │                                                   │
  │  Micro 820 PLC — 18 coils, 6 holding registers   │
  │  ATO VFD — RS485 Modbus RTU                       │
  │  Conveyor belt, photoeyes, E-stop                 │
  └─────────────────────────────────────────────────┘
```

---

## How It Works

### 1. Multimodal Input Fusion

The diagnosis engine accepts **video or images** (Factory I/O screenshots, webcam frames, or MP4 clips at 4 FPS) alongside a **PLC register snapshot** (18 coils + 6 holding registers read via Modbus TCP). Both are encoded into a single Cosmos R2 prompt.

### 2. Rule-Based Pre-Filter

Before calling the LLM, a deterministic fault classifier checks for 8 known conditions:

| Code | Severity | Condition |
|------|----------|-----------|
| E001 | EMERGENCY | E-stop active |
| M001 | CRITICAL | Motor overcurrent (>5.0A) |
| T001 | CRITICAL | Over-temperature (>80C) |
| C001 | CRITICAL | Conveyor jam (both sensors + motor ON) |
| M002 | CRITICAL | Unexpected motor stop |
| P001 | WARNING | Low pneumatic pressure (<60 PSI) |
| M003 | WARNING | Speed mismatch |
| T002 | WARNING | Elevated temperature (65-80C) |

Detected faults are injected into the R2 prompt: "Here is what the rule engine found. Now look at the video and tell me if the visual evidence confirms or contradicts."

### 3. Cosmos R2 Chain-of-Thought Reasoning

Cosmos Reason2-8B returns a `<think>` block with its full reasoning chain, followed by the diagnosis. This is critical for industrial safety — technicians need to know **why**, not just **what**.

### 4. Cross-Modal Diagnosis

The magic: R2 correlates **visual observations** (stationary box on belt, motor housing visible) with **instrument readings** (motor current spike, zero conveyor speed) to diagnose faults that neither source alone could identify.

---

## Results

### Scenario Test Matrix (March 5, 2026 — Live Cosmos R2 on Vast.ai L40S)

| Scenario | Latency | Tokens | Key Finding |
|----------|---------|--------|-------------|
| `normal` | 9.6s | 393 | HMI display mismatch detected, no mechanical faults |
| `jam` | 12.1s | 494 | CRITICAL: Motor engagement failure, control vs. physical mismatch |
| `overheat` | 13.8s | 570 | CRITICAL: 85C alarm, cooling system failure diagnosis |
| `live PLC` | 17.0s | 693 | Motor paradox + cross-modal reasoning (Feb 20 test) |

### Cross-Modal Reasoning Example

From the live PLC test — R2 identified a **motor paradox** that neither video nor telemetry alone could surface:

- PLC says `motor_running=ON` but `motor_speed=0`
- Camera shows box stationary on an energized conveyor
- R2 concludes: "System energized but producing no mechanical output" — flagging a potential encoder fault or mechanical seizure

---

## Repository Structure

```
factorylm-cosmos-demo/
├── demo/                    # Cosmos Cookoff submission
│   ├── diagnosis_engine.py     # Core: image/video + PLC → Cosmos R2 → diagnosis
│   ├── capture_fio.py          # Factory I/O screen capture (4 FPS MP4)
│   ├── test_session.py         # Full test matrix runner
│   ├── prompts/                # YAML prompt templates
│   ├── clips/                  # Screenshots and video captures
│   ├── WHITEPAPER.md           # Technical whitepaper (12 pages)
│   ├── USER_MANUAL.md          # Full operator manual
│   └── DEMO_VIDEO_SCRIPT.md    # Demo video script (2:55)
├── diagnosis/                  # Rule-based fault classifier (8 codes)
├── net/                        # Pi Factory gateway (FastAPI + Modbus poller)
├── services/matrix/            # Matrix API dashboard
├── pi-factory/                 # Raspberry Pi deployment (setup.sh + systemd)
├── config/                     # Modbus register maps (YAML)
├── tests/                      # 70+ pytest tests (sim mode)
├── docs/                       # Architecture, wiring, playbook
└── .github/workflows/          # CI pipelines
```

---

## Key Files

| File | Purpose |
|------|---------|
| `demo/diagnosis_engine.py` | Multimodal diagnosis orchestrator (426 lines) |
| `demo/prompts/factory_diagnosis.yaml` | System + user prompt templates for R2 |
| `diagnosis/conveyor_faults.py` | Deterministic fault classifier (8 codes) |
| `demo/capture_fio.py` | Factory I/O screen capture |
| `config/factoryio.yaml` | Coil + register map for Micro 820 |
| `demo/WHITEPAPER.md` | Full technical whitepaper |

---

## Documentation

- **[Technical Whitepaper](demo/WHITEPAPER.md)** — Full architecture, implementation, and validation results
- **[User Manual](demo/USER_MANUAL.md)** — Operator guide for all components
- **[Conveyor of Destiny Playbook](docs/CONVEYOR_OF_DESTINY.md)** — Complete system playbook
- **[Pi Factory Guide](pi-factory/PI_FACTORY_GUIDE.md)** — Hardware setup and deployment
- **[Wiring Guide](docs/WIRING_GUIDE.md)** — PLC and VFD wiring diagrams

---

## Why Cosmos Reason2-8B

1. **Physical world understanding** — Trained on world simulation data, R2 reasons about mechanical causality (not just token patterns)
2. **Chain-of-thought for safety** — `<think>` blocks provide auditable reasoning traces for safety-critical decisions
3. **Video-native** — Accepts MP4 at 4 FPS, observing temporal patterns (developing jams, intermittent faults)
4. **256K context** — Fits full shift histories + maintenance logs alongside real-time snapshots

---

## Reproducibility

| Component | Implementation | Protocol |
|-----------|---------------|----------|
| PLC communication | pymodbus 3.11 | Modbus TCP (port 502) |
| Video capture | mss + ffmpeg | H.264/MP4 at 4 FPS |
| AI inference | vLLM 0.15.1 | OpenAI `/v1/chat/completions` |
| Network mesh | Tailscale | WireGuard VPN |
| Simulation | Factory I/O | Modbus TCP driver |

No proprietary protocols. No vendor SDKs. Any Modbus TCP PLC works.

GPU: Vast.ai L40S spot instance, ~$0.53/hr.

---

## Development

```bash
# Run tests (no hardware needed)
FACTORYLM_NET_MODE=sim python3 -m pytest tests/ -v

# Run the full Cosmos test session
export VLLM_URL=http://localhost:8001/v1/chat/completions
python -m demo test --quick --skip-plc

# Start Pi Factory gateway in sim mode
FACTORYLM_NET_MODE=sim python3 -m uvicorn net.api.main:app --host 0.0.0.0 --port 8000
```

---

## License

[MIT](LICENSE)

---

*Built by [FactoryLM](https://factorylm.com) — making factories smarter, one diagnosis at a time.*

*NVIDIA Cosmos Cookoff 2026 Entry | [Whitepaper](demo/WHITEPAPER.md) | [Demo Video](#)*
