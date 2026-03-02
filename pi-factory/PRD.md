# PRD: Pi-Factory Watchdog

**Project:** FactoryLM Cosmos Cookoff
**Component:** `pi-factory/watchdog.py`
**Deadline:** March 5, 2026
**Author:** Mike (via Claude Code)
**Status:** Ready to build

---

## 1. What & Why

The Pi-Factory device (`pi-factory`, `192.168.1.30`) is a Raspberry Pi sitting on the same LAN switch as the Micro820 PLC, GS10 VFD, and PLC Laptop. It needs a watchdog that monitors all three devices and sends Telegram alerts when anything goes offline or comes back online.

This is the Pi's V1 scope — one script, no UI, no web server.

---

## 2. Network Map

```
LAN Switch (192.168.1.x)
├── Micro820 PLC     192.168.1.100   EtherNet/IP (pylogix)
├── GS10 VFD         192.168.1.101   Modbus TCP port 502
├── CHARLIE (laptop) 192.168.1.12    ICMP ping
└── pi-factory       192.168.1.30    ← runs this script
```

---

## 3. Pi Device Spec

| Field | Value |
|-------|-------|
| Hostname | `pi-factory` |
| IP | `192.168.1.30` (static, NetworkManager) |
| OS | Raspberry Pi OS Bookworm 64-bit, headless |
| User | `pi` / password: `factorylm` |
| Python | 3.11+ (system Python on Bookworm) |

---

## 4. Deliverables

### 4.1 `pi-factory/watchdog.py` (~150 lines)

Single self-contained Python script. No imports from anywhere else in this repo.

**Poll loop (every 10 seconds):**

| Device | How to Check | "Online" means |
|--------|-------------|----------------|
| Micro820 PLC | `pylogix.PLC("192.168.1.100").Read("Conveyor")` | No exception thrown |
| GS10 VFD | `pymodbus.ModbusTcpClient("192.168.1.101", port=502)` → read holding register `0x2103` | Connection succeeds + valid response |
| CHARLIE | `subprocess: ping -c 1 -W 2 192.168.1.12` | Return code 0 |

**Alert rules:**
- **Transition-based only** — alert on ONLINE→OFFLINE and OFFLINE→ONLINE, not every poll
- **Startup message** — "FactoryLM Watchdog started. Monitoring: Micro820, GS10 VFD, CHARLIE"
- **Offline alert format:** `⚠️ OFFLINE: {device} ({ip}) at {timestamp}`
- **Recovery alert format:** `✅ ONLINE: {device} ({ip}) at {timestamp}`
- **Timestamp format:** `2026-03-02 21:45:03` (local time)
- **If Telegram is unreachable** — print to stdout, don't crash

**Environment variables:**
```
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<chat id>
```

**CLI usage:**
```bash
# Normal run
python3 watchdog.py

# Override poll interval (default 10s)
python3 watchdog.py --interval 5

# Dry run (print alerts to stdout instead of Telegram)
python3 watchdog.py --dry-run
```

### 4.2 `pi-factory/requirements.txt`

```
pylogix
pymodbus
requests
```

### 4.3 `pi-factory/install.sh`

Bash script that:
1. Copies `watchdog.py` to `/home/pi/watchdog.py`
2. Creates `/etc/systemd/system/factorylm-watchdog.service`
3. Enables and starts the service
4. Reads env vars from `/home/pi/.env`

Service config:
```ini
[Unit]
Description=FactoryLM Watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
ExecStart=/usr/bin/python3 /home/pi/watchdog.py
Restart=always
RestartSec=10
EnvironmentFile=/home/pi/.env

[Install]
WantedBy=multi-user.target
```

---

## 5. What This Does NOT Do (V1 scope)

- No GPIO reading (old spec, ignore for now)
- No Modbus TCP server (that's a future feature)
- No web dashboard
- No tag value logging (just online/offline)
- No PLC tag writes
- No connection to Matrix API or VPS

---

## 6. Deployment Steps

```bash
# 1. On dev machine: build the files
#    (Claude Code creates pi-factory/watchdog.py, requirements.txt, install.sh)

# 2. Copy to Pi
scp -r pi-factory/ pi@192.168.1.30:~/pi-factory/

# 3. SSH into Pi
ssh pi@192.168.1.30

# 4. Install deps
cd ~/pi-factory
pip3 install -r requirements.txt

# 5. Create env file
cat > ~/.env << 'EOF'
TELEGRAM_BOT_TOKEN=your-token-here
TELEGRAM_CHAT_ID=your-chat-id-here
EOF

# 6. Test manually first
export $(cat ~/.env | xargs)
python3 watchdog.py --dry-run

# 7. Install as service
sudo bash install.sh

# 8. Check it's running
sudo systemctl status factorylm-watchdog
journalctl -u factorylm-watchdog -f
```

---

## 7. Verification Checklist

- [ ] `watchdog.py` runs without crashing when all devices are offline (graceful)
- [ ] Startup message appears in Telegram (or stdout with `--dry-run`)
- [ ] Unplug PLC Ethernet → offline alert within 10 seconds
- [ ] Plug PLC back in → recovery alert within 10 seconds
- [ ] Same for VFD and CHARLIE
- [ ] `--dry-run` flag prints to stdout instead of sending Telegram
- [ ] `--interval` flag changes poll rate
- [ ] Service survives Pi reboot (`sudo reboot`, then check Telegram for startup message)

---

## 8. Files Summary

| File | Lines | Purpose |
|------|-------|---------|
| `pi-factory/watchdog.py` | ~150 | Main watchdog script |
| `pi-factory/requirements.txt` | 3 | Python dependencies |
| `pi-factory/install.sh` | ~30 | Systemd service installer |
