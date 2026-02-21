# FactoryLM Vision: Multimodal AI Diagnostics for Industrial Automation

> Fuse live video + PLC telemetry through NVIDIA Cosmos Reason2-8B to diagnose factory faults in seconds — not hours.

**NVIDIA Cosmos Cookoff Submission** | [Whitepaper](cookoff/WHITEPAPER.md) | [User Manual](cookoff/USER_MANUAL.md) | [Architecture](docs/cosmos_architecture.md)

---

## Demo Video

<!-- TODO: Replace with final recording before March 5 -->
[![Demo Video](https://img.shields.io/badge/Demo-Coming%20Soon-blue)](https://github.com/Mikecranesync/factorylm-cosmos-cookoff)

---

## The Problem

Factory technicians spend **40% of their time diagnosing equipment faults** — walking to machines, reading HMI screens, cross-referencing error codes against manuals. PLCs record motor current, temperature, and conveyor speed at 10 Hz. Cameras watch production lines 24/7. Yet when something goes wrong, no system connects what the instruments report with what the cameras see.

**The data exists. The inference doesn't.**

---

## What FactoryLM Vision Does

FactoryLM Vision captures a live frame from the factory floor and reads real-time PLC registers over Modbus TCP, then feeds both into **NVIDIA Cosmos Reason2-8B** (self-hosted via vLLM on a Vast.ai L40S GPU). The model reasons across both modalities and returns a structured diagnosis: what it sees, what the instruments say, where they conflict, and what the technician should check first.

A technician texts their factory from their phone. The AI answers.

Next: AR glasses on the factory floor — look at a machine, ask what's wrong, see the diagnosis in your field of view.

---

## Architecture

```
+------------------------------------------------------------------+
|                     TECHNICIAN INTERFACE                          |
|   Phone / Telegram  →  "Is the conveyor jammed?"                 |
+------------------------------------------------------------------+
         |
         v
+------------------------------------------------------------------+
|                     DIAGNOSIS ENGINE                              |
|   cookoff/diagnosis_engine.py                                    |
|   Captures frame + reads PLC tags → builds multimodal prompt     |
+------------------------------------------------------------------+
         |                          |
         v                          v
+------------------+    +------------------------+
|  Factory I/O     |    |  Allen-Bradley         |
|  Screen Capture  |    |  Micro 820 PLC         |
|  (PIL)           |    |  via Modbus TCP        |
+------------------+    +------------------------+
         |                          |
         v                          v
+------------------------------------------------------------------+
|                   COSMOS REASON2-8B                               |
|   Self-hosted on Vast.ai L40S via vLLM 0.15.1                   |
|   OpenAI-compatible /v1/chat/completions endpoint                |
+------------------------------------------------------------------+
         |
         v
+------------------------------------------------------------------+
|                   STRUCTURED DIAGNOSIS                            |
|   - Visual observations (what the camera sees)                   |
|   - PLC anomalies (what the instruments report)                  |
|   - Cross-modal conflicts (motor ON but belt stopped)            |
|   - Recommended actions (check roller alignment)                 |
+------------------------------------------------------------------+
```

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/Mikecranesync/factorylm-cosmos-cookoff.git
cd factorylm-cosmos-cookoff

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your vLLM endpoint and PLC IP

# 4. Start the Matrix API (dashboard + diagnosis endpoint)
python -m uvicorn services.matrix.app:app --host 0.0.0.0 --port 8000

# 5. Run a diagnosis session (simulator mode — no hardware needed)
python cookoff/test_session.py
```

---

## Key Results

From the validated end-to-end test on February 20, 2026:

| Metric | Value |
|--------|-------|
| **End-to-end diagnosis time** | 17.0 seconds |
| **PLC tags read** | 19 live registers via Modbus TCP |
| **Key finding** | Motor paradox: motor energized but speed register at zero |
| **Cross-modal detection** | Visual (stationary box on conveyor) + PLC (motor ON, speed 0) |
| **Model** | Cosmos Reason2-8B via vLLM 0.15.1 |
| **GPU** | NVIDIA L40S (48 GB VRAM) on Vast.ai |

The motor paradox — where the PLC reports the motor as energized but the speed register reads zero — is a fault that **neither video nor telemetry alone can diagnose**. Only the fusion of both modalities surfaces it.

---

## Hardware & Infrastructure

| Component | Details |
|-----------|---------|
| **PLC** | Allen-Bradley Micro 820 (2080-LC30-48QWB) |
| **Simulation** | Factory I/O "From A to B" scene, Modbus TCP |
| **Edge Device** | Raspberry Pi (on-premise data collection) |
| **GPU** | NVIDIA L40S (48 GB VRAM) via Vast.ai |
| **Model Runtime** | vLLM 0.15.1, OpenAI-compatible API |
| **Model** | NVIDIA Cosmos Reason2-8B |

---

## Repository Structure

```
factorylm-cosmos-cookoff/
├── cookoff/              # Competition entry: whitepaper, user manual, core engine
│   ├── WHITEPAPER.md     # Full technical whitepaper (650+ lines)
│   ├── USER_MANUAL.md    # Complete setup and usage guide
│   ├── diagnosis_engine.py  # Core: captures frame + PLC tags → Cosmos prompt
│   ├── capture_fio.py    # Factory I/O screen capture utility
│   └── test_session.py   # End-to-end test harness
├── cosmos/               # Cosmos Reason2-8B client and agent
├── diagnosis/            # Fault classification and prompt templates
├── services/             # Matrix API dashboard + PLC Modbus driver
├── sim/                  # Factory I/O bridge and PLC simulator
├── config/               # YAML configuration files
├── video/                # Video analysis pipeline
├── infra/                # Docker Compose for local deployment
└── docs/                 # Architecture and demo runbook
```

---

## Documentation

- **[Whitepaper](cookoff/WHITEPAPER.md)** — Full technical paper: problem, architecture, implementation, validation results
- **[User Manual](cookoff/USER_MANUAL.md)** — Step-by-step setup guide for all components
- **[Architecture](docs/cosmos_architecture.md)** — System design and data flow diagrams
- **[Demo Runbook](docs/cosmos_cookoff_demo_runbook.md)** — How to run the live demo

---

## License

[MIT](LICENSE)

---

*Built by [FactoryLM](https://factorylm.com) for the NVIDIA Cosmos Cookoff 2026.*
