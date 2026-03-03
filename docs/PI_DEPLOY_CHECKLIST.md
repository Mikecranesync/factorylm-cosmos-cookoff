# Pi Factory Deployment Checklist

Deploy the proven v3.0 edge gateway pipeline onto a Raspberry Pi at **192.168.1.30**.

Zero application code changes needed — the entire stack is env-var-driven.

## Prerequisites

- Raspberry Pi 3B+, 4, 5, or Zero 2W
- microSD card (16GB+)
- Ethernet cable to PLC subnet (192.168.1.x)
- Micro 820 PLC at 192.168.1.100:502, program running

## 1. Flash Pi OS

1. Download Raspberry Pi Imager
2. Flash **Raspberry Pi OS Bookworm Lite (64-bit)**
3. In Imager settings:
   - Enable SSH (password or key)
   - Set hostname: `pi-factory`
   - Set username: `pi`
   - Set WiFi creds (for initial access)
   - Set locale/timezone

## 2. First Boot + Network

1. Boot Pi, wait 60s
2. SSH in: `ssh pi@pi-factory.local` (or find IP via router)
3. Set static IP on eth0:

```bash
sudo nmcli con mod "Wired connection 1" \
  ipv4.addresses 192.168.1.30/24 \
  ipv4.gateway 192.168.1.1 \
  ipv4.method manual
sudo nmcli con up "Wired connection 1"
```

4. Verify PLC reachable: `ping 192.168.1.100`

## 3. Clone Repo + Run Setup

```bash
sudo git clone https://github.com/Mikecranesync/factorylm-cosmos-cookoff.git /opt/factorylm
cd /opt/factorylm
sudo bash pi-factory/setup.sh
```

This runs all 10 steps: system deps, directory structure, Python venv, app code,
WiFi captive portal, Tailscale, systemd services, gateway ID, branding, and launch.

## 4. Activate Tailscale

Setup.sh installs Tailscale but can't authenticate automatically (requires browser).

```bash
sudo tailscale up
```

Follow the URL printed to authenticate. After this, the Pi is reachable from the Matrix VPS (100.68.120.99) and all cluster nodes via Tailscale.

Verify: `tailscale status` — should show the Pi connected to the tailnet.

## 5. Verify Service

```bash
# Check systemd status
sudo systemctl status pi-factory

# Tail logs
sudo journalctl -u pi-factory -f --no-pager

# Check API responds
curl http://localhost:8000/api/status
```

Expected: service active, API returns JSON with `status: "ok"`.

## 6. Verify PLC Tag Flow

```bash
# From the Pi itself
curl -s http://localhost:8000/api/plc/live | python3 -m json.tool

# From the PLC laptop (192.168.1.20)
curl -s http://192.168.1.30:8000/api/plc/live | python3 -m json.tool
```

Expected: real coil values (0/1) and register values from the Micro 820.

## 7. Verify CompactCom (Modbus TCP Server)

The Pi serves 21 registers on port 5020 for the PLC to read via MSG instruction.

```bash
# From any machine on the subnet — read 21 registers from Pi
python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('192.168.1.30', port=5020, timeout=3)
c.connect()
r = c.read_holding_registers(0, 21)
print('Registers 0-20:', r.registers)
c.close()
"
```

Expected: 21 values, with register 19 (pi_heartbeat) incrementing on each read.

## 8. Verify Tag Discovery (pylogix)

```bash
cd /opt/factorylm
source venv/bin/activate
python tools/plc_live_reader.py --host 192.168.1.100
```

Expected: lists all PLC tags by name (uses EtherNet/IP `comm.Micro800 = True`).

## 9. Verify Dashboard

Open browser: `http://192.168.1.30:8000`

Expected: Live I/O Panel showing real-time coil/register values.

## 10. PLC MSG Instruction Setup

On the Micro 820, configure a MSG instruction to read from the Pi:

| Parameter | Value |
|-----------|-------|
| Type | Modbus TCP Read (FC3) |
| Remote IP | 192.168.1.30 |
| Remote Port | 5020 |
| Start Register | 0 |
| Count | 21 |
| Destination | Local INT array[0..20] |

---

## CompactCom Register Map (21 registers, 0-20)

| Reg | Name | Scale | Source |
|-----|------|-------|--------|
| 0 | belt_rpm | x10 | Camera/BeltTachometer |
| 1 | belt_speed_pct | x10 | Camera/BeltTachometer |
| 2 | belt_status | enum 0-4 | Camera/BeltTachometer |
| 3 | belt_offset_px | +32768 (signed→unsigned) | Camera/BeltTachometer |
| 4 | vfd_output_hz | x100 | VFD RS485 reg 0x2103 |
| 5 | vfd_output_amps | x10 | VFD RS485 reg 0x2104 |
| 6 | vfd_fault_code | direct | VFD RS485 |
| 7 | motor_running | 0/1 | PLC coil 0 |
| 8 | motor_speed | 0-100 | PLC reg 101 |
| 9 | motor_current | x10 | PLC reg 102 |
| 10 | conveyor_running | 0/1 | PLC coil 0 |
| 11 | temperature | x10 | PLC reg 103 |
| 12 | pressure | direct | PLC reg 104 |
| 13 | sensor_1 | 0/1 | PLC coil 2 (SensorStart) |
| 14 | sensor_2 | 0/1 | PLC coil 3 (SensorEnd) |
| 15 | e_stop | 0/1 | PLC coil 8 (E-stop NO) |
| 16 | fault_alarm | 0/1 | coil[8] AND NOT coil[9] |
| 17 | error_code | direct | PLC reg 105 |
| 18 | ai_confidence | 0-100 | Cosmos R2 diagnosis |
| 19 | pi_heartbeat | 0-65535 wrapping | Pi edge gateway |
| 20 | source_flags | bitmask | bit0=PLC, bit1=VFD, bit2=camera |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PLC_HOST` | _(none)_ | Micro 820 IP (required: `192.168.1.100`) |
| `PLC_PORT` | `502` | Modbus TCP port |
| `PI_COMPACTCOM_PORT` | _(none)_ | CompactCom server port (set: `5020`) |
| `VFD_HOST` | _(none)_ | VFD Modbus gateway IP (optional) |
| `VFD_SLAVE` | `1` | VFD Modbus slave address |
| `VIDEO_SOURCE` | _(none)_ | Camera index or URL (optional) |
| `FACTORYLM_NET_DB` | `net.db` | SQLite history path |
| `FACTORYLM_NET_MODE` | `real` | Operating mode |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Service won't start | `journalctl -u pi-factory -e` — check for import errors |
| PLC unreachable | `ping 192.168.1.100` — check Ethernet cable, subnet |
| No register values | Verify PLC program is running in CCW |
| CompactCom timeout | Check port 5020 not blocked: `ss -tlnp \| grep 5020` |
| pylogix fails | Ensure PLC is in Remote Run mode, EtherNet/IP enabled |
