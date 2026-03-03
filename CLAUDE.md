# CLAUDE.md - FactoryLM Cosmos Cookoff

## READ FIRST

Before doing ANY work, read these two documents:
1. **FactoryLM Vision**: https://github.com/Mikecranesync/factorylm/blob/main/README.md
2. **Conveyor of Destiny Playbook**: `docs/CONVEYOR_OF_DESTINY.md` (the single source of truth for this project)

## What This Repo Is

This is the **NVIDIA Cosmos Cookoff submission + Conveyor of Destiny demo** — the first public proof that FactoryLM works on real hardware.

**The mission:** Fuse live video + PLC telemetry through Cosmos Reason2-8B to diagnose factory faults in seconds. Then let anyone on the internet control the machine.

**The tagline:** "Type a command. Move a machine. From anywhere on Earth."

## The System

```
Internet (Discord / Web / Telegram)
         |
         v
  FactoryLM Matrix (VPS 100.68.120.99)
         | task dispatch via Tailscale
         v
  Raspberry Pi (192.168.1.30:8000)    ← Edge Gateway
         | Modbus TCP read (coils+regs)
         v
  Micro 820 PLC (192.168.1.100:502)
         | RS485 Modbus RTU
         v
  ATO VFD --> Motor --> Conveyor Belt
         ^
  Pi CompactCom (:5020) ← PLC reads 21 regs via MSG
```

## Hardware Reference

- **PLC**: Allen-Bradley Micro 820 (2080-LC30-48QWB), IP 192.168.1.100, Modbus TCP port 502
- **VFD**: ATO VFD, RS485 slave address 1, 9600 baud 8N1
- **AI Model**: NVIDIA Cosmos Reason2-8B via vLLM on Vast.ai L40S

### Canonical Modbus Address Map

**Coils (0-17):**

| Addr | Tag | Description |
|------|-----|-------------|
| 0 | Conveyor | Belt motor command |
| 1 | Emitter | Item spawner |
| 2 | SensorStart | Entry photoeye |
| 3 | SensorEnd | Exit photoeye |
| 4 | RunCommand | Remote API trigger |
| 7 | _IO_EM_DI_00 | 3-pos switch CENTER |
| 8 | _IO_EM_DI_01 | E-stop NO contact |
| 9 | _IO_EM_DI_02 | E-stop NC contact |
| 10 | _IO_EM_DI_03 | 3-pos switch RIGHT |
| 11 | _IO_EM_DI_04 | Green pushbutton |
| 15 | _IO_EM_DO_00 | Indicator LED / VFD FWD |
| 16 | _IO_EM_DO_01 | E-stop LED / VFD REV |
| 17 | _IO_EM_DO_03 | Aux output |

**Holding Registers (100-105):**

| Addr | Tag | Scale | Description |
|------|-----|-------|-------------|
| 100 | item_count | 1x | Items reached SensorEnd |
| 101 | motor_speed | 1x | Speed 0-100% |
| 102 | motor_current | /10 | Amps |
| 103 | temperature | /10 | Degrees C |
| 104 | pressure | 1x | PSI |
| 105 | error_code | 1x | 0=OK, 1=Overload, 2=Overheat, 3=Jam, 4=Sensor, 5=Comms |

**VFD Registers (RS485):**

| Addr | Direction | Description |
|------|-----------|-------------|
| 0x2000 | Write | Control word: 0x0001=FWD, 0x0003=REV, 0x0007=Stop |
| 0x2001 | Write | Freq setpoint x100 (1000 = 10.00 Hz) |
| 0x2103 | Read | Actual freq /100 |
| 0x2104 | Read | Actual current /10 |

### Derived Values

```
fault_alarm = coil[8] AND NOT coil[9]   # E-stop dual-contact validation
motor_stopped = NOT coil[0]
```

## Repository Structure

```
factorylm-cosmos-cookoff/
├── CLAUDE.md             # YOU ARE HERE — read this first
├── cookoff/              # Cosmos Cookoff submission
│   ├── diagnosis_engine.py  # Core: frame + PLC tags -> Cosmos prompt
│   ├── WHITEPAPER.md     # Technical whitepaper
│   └── USER_MANUAL.md    # Setup guide
├── cosmos/               # Cosmos R2 client and agent
├── diagnosis/            # Fault classifier (8 codes) + prompt templates
├── services/             # Matrix API dashboard + PLC Modbus driver
├── sim/                  # Factory I/O bridge (plc_simulator removed in v3.0)
├── config/               # YAML configs (factoryio.yaml)
├── pi-factory/           # Raspberry Pi deployment
│   ├── setup.sh          # Master setup script (9 steps)
│   ├── systemd/          # Service files
│   └── configs/          # Config templates
├── docs/                 # Architecture + CONVEYOR_OF_DESTINY.md
│   ├── CONVEYOR_OF_DESTINY.md    # THE PLAYBOOK — single source of truth
│   ├── PI_DEPLOY_CHECKLIST.md    # Pi deployment runbook
│   └── WIRING_GUIDE.md
├── tools/                # Standalone utilities
│   └── plc_live_reader.py  # pylogix EtherNet/IP tag discovery
├── video/                # Video analysis pipeline
└── infra/                # Docker Compose
```

## Key Files

| File | What It Does |
|------|-------------|
| `docs/CONVEYOR_OF_DESTINY.md` | Complete playbook: wiring, VFD, PLC, edge stack, internet control, safety |
| `cookoff/diagnosis_engine.py` | Multimodal diagnosis: captures frame + reads PLC -> Cosmos R2 prompt |
| `diagnosis/conveyor_faults.py` | 8-code fault classifier (E001-T002) |
| `config/factoryio.yaml` | Modbus bridge config (coil/register mapping, poll interval) |
| `services/matrix/app.py` | Dashboard + diagnosis API endpoint |
| `cookoff/USER_MANUAL.md` | Full operator manual for all components |

## Known Discrepancies

These conflicts exist across source files. `CONVEYOR_OF_DESTINY.md` is the canonical resolution.

| Issue | Resolution |
|-------|-----------|
| Register 100: `motor_speed` vs `item_count` | Use `item_count` |
| Coil 0: `motor_running` vs `conveyor_running` | Use `Conveyor` (CCW tag name) |
| Coils 2-3: `fault_alarm/conveyor_running` vs `SensorStart/SensorEnd` | Use `SensorStart`/`SensorEnd` |

If you encounter a naming conflict, check `CONVEYOR_OF_DESTINY.md` Section 6 tables first.

## Engineering Commandments

1. Create Issue First
2. Branch from Main
3. No Direct Push to Main
4. Link PRs to Issues
5. No Merge Without Approval
6. No Deploy Without Approval
7. Meaningful Commits
8. Test Before Pushing
9. Document Changes
10. Learn from Failures

## Constitution

- **Mission**: Ship products, generate revenue
- **Boundaries**: Merge/deploy requires Mike's approval
- **Human in Loop**: Mike approves what ships
- **Safety**: Hardware E-stop always wired. Software never overrides hardware safety.

## Raspberry Pi Edge Gateway (192.168.1.30)

The Pi runs the full v3.0 pipeline: ModbusTagSource → Poller → Publisher → CompactCom.

- **Dashboard**: `http://192.168.1.30:8000`
- **Live tags**: `http://192.168.1.30:8000/api/plc/live`
- **CompactCom**: `192.168.1.30:5020` (21 registers, PLC reads via MSG FC3)
- **Systemd**: `pi-factory.service` + watchdog
- **Deploy guide**: `docs/PI_DEPLOY_CHECKLIST.md`

## Quick Commands

```bash
# Start edge gateway (dev machine, no hardware)
python server.py --port 8081

# Start edge gateway with PLC + VFD + camera + CompactCom
PLC_HOST=192.168.1.100 VFD_HOST=192.168.1.101 VIDEO_SOURCE=0 PI_COMPACTCOM_PORT=5020 python server.py --port 8081

# Run diagnosis (live PLC)
python cookoff/diagnosis_engine.py --live-plc --plc-ip 192.168.1.100

# Start Matrix API dashboard
python -m uvicorn services.matrix.app:app --host 0.0.0.0 --port 8000

# Read PLC coils (pymodbus one-liner)
python -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient('192.168.1.100',port=502,timeout=3); c.connect(); r=c.read_coils(0,18); print([int(b) for b in r.bits[:18]])"

# Read CompactCom registers from Pi (from any machine)
python -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient('192.168.1.30',port=5020,timeout=3); c.connect(); r=c.read_holding_registers(0,21); print(r.registers)"

# pylogix tag discovery (EtherNet/IP)
python tools/plc_live_reader.py --host 192.168.1.100
```

Full docs: https://github.com/Mikecranesync/factorylm/blob/main/README.md
