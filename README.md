# Pi Factory — Industrial PLC Monitor + AI Diagnosis

> Plug a Raspberry Pi into any Modbus PLC. Get a live dashboard, fault detection, and AI-powered diagnosis in under 5 minutes.

**Flash → Boot → Connect → Monitor.** That's it.

---

## What It Does

Pi Factory turns a Raspberry Pi into a plug-and-play industrial gateway. It auto-discovers PLCs on the local network, reads tags over Modbus TCP at 5 Hz, detects 8 fault conditions in real time, and serves a browser-based dashboard over WiFi. No cloud account required — everything runs on the Pi.

For advanced diagnosis, Pi Factory can fuse live video with PLC telemetry through NVIDIA Cosmos Reason2-8B to diagnose faults that neither camera nor instruments alone can catch.

---

## Install

### Option A — Pre-built Image (fastest)

1. Download `PiFactory-v1.0.0.img.xz` from [Releases](../../releases)
2. Flash to microSD with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
3. Insert SD card, power on the Pi
4. Connect your phone to **PiFactory-Connect** WiFi (password: `factorylm`)
5. Open `http://192.168.4.1:8000/setup` — the wizard walks you through PLC discovery

### Option B — Install on Existing Pi OS

```bash
git clone https://github.com/Mikecranesync/factorylm-cosmos-cookoff.git
cd factorylm-cosmos-cookoff
sudo bash pi-factory/setup.sh
sudo reboot
```

After reboot, connect to **PiFactory-Connect** WiFi and open the setup wizard.

### Option C — Developer Mode (no Pi needed)

```bash
git clone https://github.com/Mikecranesync/factorylm-cosmos-cookoff.git
cd factorylm-cosmos-cookoff
pip install -r requirements.txt
FACTORYLM_NET_MODE=sim python -m uvicorn net.api.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/setup` to walk through the wizard with simulated PLC data.

---

## Architecture

```
  Phone / Laptop (browser)
         |
    PiFactory-Connect WiFi
         |
         v
  ┌──────────────────────────────┐
  │  Raspberry Pi (Pi Factory)   │
  │                              │
  │  FastAPI (port 8000)         │
  │    /setup     → Wizard UI    │
  │    /api/plc/* → PLC mgmt     │
  │    /api/wifi  → Network cfg  │
  │                              │
  │  Poller (5 Hz)               │
  │    → Reads Modbus TCP tags   │
  │    → Writes SQLite history   │
  │    → Runs fault detection    │
  │                              │
  │  Fault Engine (8 codes)      │
  │    E001 E-Stop               │
  │    M001 Overcurrent          │
  │    T001 Over-temperature     │
  │    C001 Conveyor jam         │
  │    M002 Motor stopped        │
  │    P001 Low pressure         │
  │    M003 Speed mismatch       │
  │    T002 Elevated temp        │
  └───────────┬──────────────────┘
              │ Modbus TCP
              v
  ┌──────────────────────────────┐
  │  PLC (Allen-Bradley, etc.)   │
  │  Coils 0-17, Registers 100+ │
  └──────────────────────────────┘
```

---

## Compatible Hardware

| Component | Supported |
|-----------|-----------|
| **Pi** | Raspberry Pi 3B+, Pi 4 (all RAM), Pi 5, Pi Zero 2W |
| **PLC** | Any Modbus TCP device (tested: Allen-Bradley Micro 820) |
| **VFD** | ATO VFD via RS485 (optional) |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/setup` | Setup wizard (6-screen flow) |
| GET | `/api/status` | Gateway health + PLC connection state |
| GET | `/api/gateway/id` | Unique gateway identifier |
| GET | `/api/gateway/qr` | QR code PNG for pairing |
| GET | `/api/plc/scan` | Discover PLCs on subnet |
| POST | `/api/plc/extract` | Auto-detect tags from a PLC |
| POST | `/api/plc/config` | Save PLC config + start polling |
| GET | `/api/plc/live` | Current tag values |
| POST | `/api/plc/live` | Filtered live values (wizard) |
| GET | `/api/plc/tags` | Saved tag configuration |
| GET | `/api/wifi/scan` | Available WiFi networks |
| POST | `/api/wifi/connect` | Connect Pi to WiFi |

---

## Repository Structure

```
factorylm-cosmos-cookoff/
├── net/                   # Core application
│   ├── api/main.py        # FastAPI gateway server
│   ├── drivers/           # PLC discovery, Modbus, EtherNet/IP
│   ├── diagnosis/         # Fault engine (8 codes)
│   ├── portal/wizard.html # 6-screen setup wizard
│   ├── services/poller.py # Background tag polling
│   ├── sim/               # PLC simulator for dev/testing
│   └── platform/          # WiFi scanner (Linux/macOS/mock)
├── services/matrix/       # Matrix API (telemetry + incidents + Cosmos insights)
├── pi-factory/            # Raspberry Pi deployment
│   ├── setup.sh           # DIY installer
│   ├── first_boot.sh      # First-boot identity generation
│   ├── systemd/           # Service files
│   └── configs/           # hostapd, dnsmasq, motd
├── factorylm-image/       # pi-gen stages for .img.xz build
├── cookoff/               # NVIDIA Cosmos Cookoff submission
│   ├── WHITEPAPER.md      # Technical whitepaper
│   ├── diagnosis_engine.py # Multimodal AI diagnosis
│   └── USER_MANUAL.md     # Full operator manual
├── tests/                 # 70 pytest tests (sim mode)
├── .github/workflows/     # CI + image build pipelines
└── docs/                  # Architecture, wiring guide, playbook
```

---

## Development

```bash
# Run tests (no hardware needed)
FACTORYLM_NET_MODE=sim python -m pytest tests/ -v

# Start the gateway in sim mode
FACTORYLM_NET_MODE=sim python -m uvicorn net.api.main:app --host 0.0.0.0 --port 8000

# Start the Matrix dashboard
MATRIX_DB_PATH=matrix.db python -m uvicorn services.matrix.app:app --host 0.0.0.0 --port 8001
```

---

## Documentation

- **[Pi Factory Guide](pi-factory/PI_FACTORY_GUIDE.md)** — Hardware setup and deployment
- **[Conveyor of Destiny Playbook](docs/CONVEYOR_OF_DESTINY.md)** — Complete system playbook
- **[Wiring Guide](docs/WIRING_GUIDE.md)** — PLC and VFD wiring diagrams
- **[Whitepaper](cookoff/WHITEPAPER.md)** — Cosmos Reason2-8B multimodal diagnosis
- **[User Manual](cookoff/USER_MANUAL.md)** — Operator guide for all components

---

## License

[MIT](LICENSE)

---

*Built by [FactoryLM](https://factorylm.com) — making factories smarter, one Pi at a time.*
