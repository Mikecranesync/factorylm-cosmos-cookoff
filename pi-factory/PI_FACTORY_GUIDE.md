# Pi Factory — Setup Guide

**Turn a stock Raspberry Pi into an industrial PLC monitoring appliance in 10 minutes.**

---

## What You Need

| Item | Notes |
|------|-------|
| Raspberry Pi 3B+, 4, 5, or Zero 2W | 64-bit recommended |
| 16GB+ microSD card | Class 10 or better |
| Ethernet cable | To connect to PLC subnet |
| USB-C power supply | 5V 3A for Pi 4/5 |
| A phone or laptop | For the setup wizard |

## Quick Start (3 Commands)

Flash Raspberry Pi OS Bookworm (64-bit Lite) to your SD card using [Raspberry Pi Imager](https://www.raspberrypi.com/software/).

Boot the Pi, SSH in, then run:

```bash
git clone https://github.com/Mikecranesync/factorylm-cosmos-cookoff.git
cd factorylm-cosmos-cookoff
sudo bash pi-factory/setup.sh
```

That's it. The script handles everything. When it finishes you'll see:

```
  Pi Factory is LIVE

  Gateway ID:   flm-a7b3c9e1f2d4
  Dashboard:    http://192.168.1.50:8000
  Setup Wizard: http://192.168.1.50:8000/setup
  WiFi AP:      PiFactory-Connect (password: factorylm)
```

## What the Setup Does

The `setup.sh` script runs 9 steps automatically:

1. **System deps** — installs hostapd, dnsmasq, Python 3, networking tools
2. **Directory structure** — creates `/opt/factorylm/` with all subdirs
3. **Python venv** — installs pymodbus, pycomm3, opcua, FastAPI, uvicorn
4. **App deployment** — copies all Pi Factory application code
5. **WiFi captive portal** — sets up `PiFactory-Connect` hotspot on `192.168.4.1`
6. **Systemd services** — `pi-factory.service` auto-starts on boot + watchdog
7. **Gateway identity** — generates unique `flm-xxxxxxxxxxxx` ID
8. **Branding** — sets hostname to `pi-factory`, installs MOTD and CLI helpers
9. **Launch** — starts everything, verifies API is responding

## First-Time Wizard

After setup completes:

1. **Connect your phone** to WiFi network `PiFactory-Connect` (password: `factorylm`)
2. **Browser auto-opens** to the setup wizard (or go to `http://192.168.4.1:8000/setup`)
3. **Screen 1 — Welcome**: Tap "Begin Setup"
4. **Screen 2 — Discovery**: Pi scans the Ethernet subnet for PLCs
5. **Screen 3 — Tag Extraction**: Auto-detects tags via EtherNet/IP → OPC UA → Modbus waterfall
6. **Screen 4 — Tag Selection**: Tap tags to give them human-readable names
7. **Screen 5 — Live Panel**: See real-time PLC data flowing at 5Hz
8. **Screen 6 — WiFi Uplink**: Connect Pi to your plant WiFi for cloud access

## Connecting to Your PLC

Plug an Ethernet cable from the Pi to a switch on the same subnet as your PLC. Common setups:

| PLC | Default IP | Protocol | Port |
|-----|-----------|----------|------|
| Allen-Bradley Micro 820 | 192.168.1.100 | Modbus TCP | 502 |
| Allen-Bradley CompactLogix | 192.168.1.1 | EtherNet/IP | 44818 |
| Siemens S7-1200 | 192.168.0.1 | S7 | 102 |
| Any Modbus device | varies | Modbus TCP | 502 |

The wizard auto-scans and discovers PLCs — no manual IP entry needed.

## CLI Commands

After SSH login, these shortcuts are available:

| Command | What it does |
|---------|-------------|
| `pf-status` | Check if Pi Factory is running |
| `pf-logs` | Tail live application logs |
| `pf-restart` | Restart the service |
| `pf-stop` | Stop the service |
| `pf-start` | Start the service |
| `pf-info` | Show gateway ID, IP, dashboard URL |

## File Layout on the Pi

```
/opt/factorylm/
├── net/                 # Application code
│   ├── api/main.py      # FastAPI backend (port 8000)
│   ├── drivers/          # PLC protocol drivers
│   ├── platform/         # WiFi scanner abstraction
│   ├── portal/           # Setup wizard HTML
│   ├── services/         # Poller (5Hz read, 1Hz write)
│   ├── sim/              # PLC simulator
│   └── diagnosis/        # Fault engine
├── config/               # YAML configs
├── config.json           # Gateway identity
├── data/net.db           # SQLite database (tags, history)
└── venv/                 # Python virtual environment
```

## API Endpoints

All accessible at `http://pi-factory.local:8000`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/setup` | Setup wizard |
| GET | `/api/status` | Gateway health check |
| GET | `/api/plc/scan` | Scan subnet for PLCs |
| POST | `/api/plc/extract` | Auto-extract tags |
| POST | `/api/plc/test` | Single Modbus read |
| GET | `/api/plc/tags` | Saved tag config |
| GET | `/api/plc/live` | Real-time tag values |
| POST | `/api/plc/name_tag` | Rename a tag |
| POST | `/api/plc/config` | Save PLC + start polling |
| GET | `/api/wifi/scan` | Available WiFi networks |
| POST | `/api/wifi/connect` | Join a WiFi network |
| GET | `/api/gateway/qr` | QR code for pairing |

## Running in Simulator Mode

For testing without hardware:

```bash
FACTORYLM_NET_MODE=sim pf-restart
```

Or manually:

```bash
cd /opt/factorylm
FACTORYLM_NET_MODE=sim venv/bin/uvicorn net.api.main:app --host 0.0.0.0 --port 8000
```

All endpoints return realistic fake data — perfect for demos.

## Updating

Pull the latest code and re-run setup:

```bash
cd ~/factorylm-cosmos-cookoff
git pull
sudo bash pi-factory/setup.sh
```

The script is idempotent — safe to run multiple times.

## Uninstalling

```bash
sudo bash pi-factory/uninstall.sh
```

Removes all Pi Factory files, services, WiFi config, and branding.

## Troubleshooting

**Service won't start:**
```bash
pf-logs          # Check for errors
pf-restart       # Try restarting
```

**Can't find PLC:**
- Confirm Ethernet cable is connected
- Check Pi has an IP on the PLC subnet: `ip addr show eth0`
- Try manual scan: `curl http://localhost:8000/api/plc/scan?subnet=192.168.1.0/24`

**WiFi AP not appearing:**
```bash
sudo systemctl status hostapd
sudo systemctl restart hostapd
```

**Database issues:**
```bash
# Reset database
rm /opt/factorylm/data/net.db
pf-restart
```

---

*Pi Factory — Type a command. Move a machine. From anywhere on Earth.*
