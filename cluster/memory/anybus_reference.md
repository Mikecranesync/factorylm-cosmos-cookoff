# Anybus CompactCom 40 — Integration Reference

**Created:** 2026-03-03
**Author:** CHARLIE
**Source:** HMS GitHub repos + tech support articles

---

## Module Overview

The CompactCom 40 is a network interface module that sits between a host application (Pi) and an industrial network (Modbus TCP or EtherNet/IP). It translates Application Data Instances (ADIs) defined by the host into network-accessible registers/assemblies.

**Key fact:** The CompactCom is a network SLAVE, not a master. It does not initiate communication — the PLC polls it.

---

## SPI Configuration (Pi 4B)

| Parameter | Value |
|-----------|-------|
| Device | `/dev/spidev0.0` |
| Speed | 10 MHz (`10000000`) |
| Mode | SPI_MODE_0 (CPOL=0, CPHA=0) |
| Chip Select | CS0, active LOW |
| Bits per unit | 8 |
| GPIO chip | `/dev/gpiochip0` (Pi 3/4), `/dev/gpiochip4` (Pi 5) |

**If using fly wires:** reduce to clock divider 128 (~1.5 MHz).

---

## GPIO Pin Assignments

| GPIO | Name | Direction | Function |
|------|------|-----------|----------|
| 17 | RESET | Output | Module hardware reset |
| 5 | OM0 | Output (default ACTIVE) | Operating Mode bit 0 |
| 6 | OM1 | Output (default ACTIVE) | Operating Mode bit 1 |
| 13 | OM2 | Output (default ACTIVE) | Operating Mode bit 2 |
| 19 | OM3 | Output (default ACTIVE) | Operating Mode bit 3 |
| 27 | MD0 | Input (pull-up) | Module Detect 0 |
| 22 | MD1 | Input (pull-up) | Module Detect 1 |
| 23 | MI0 | Input | Module ID 0 |
| 24 | MI1 | Input | Module ID 1 |
| 26 | IRQ | Input (pull-up) | Interrupt Request |

---

## Software Stack

```
Micro820 PLC (Modbus TCP master, reads/writes CompactCom registers)
    │  Ethernet (Modbus TCP)
CompactCom 40 Module (AB6603-E)
    │  Internal module bus
CompactCom 40 Adapter Board (Pi HAT)
    │  SPI + 10 GPIO pins
abcc-example-raspberrypi (C host app, runs as root, systemd)
    │  Unix domain socket (/run/abcc/process_data.sock)
AnybusTagSource (Python, pi-factory)
    │
Pi-Factory tag server, VFD reader, belt encoder (existing)
```

---

## ADI Mapping — Conveyor Tags

### Process Data Read (Pi → PLC)

| ADI # | Tag | ABP Type | Size | Scale | Description |
|-------|-----|----------|------|-------|-------------|
| 1 | belt_rpm | ABP_UINT16 | 2B | x10 | Belt RPM (0-6550.0) |
| 2 | belt_speed_pct | ABP_UINT16 | 2B | x10 | Belt speed % (0-100.0) |
| 3 | belt_status | ABP_UINT8 | 1B | enum | 0=unknown,1=normal,2=warning,3=critical,4=stopped |
| 4 | belt_offset_px | ABP_SINT16 | 2B | x1 | Belt tracking offset (-500..500 px) |
| 5 | vfd_output_hz | ABP_UINT16 | 2B | x100 | VFD freq (0-655.00 Hz) |
| 6 | vfd_output_amps | ABP_UINT16 | 2B | x10 | VFD current (0-6553.5 A) |
| 7 | vfd_fault_code | ABP_UINT8 | 1B | x1 | VFD fault 0-13 |
| 8 | ai_fault_code | ABP_UINT8 | 1B | x1 | AI diagnosis fault code |
| 9 | ai_confidence | ABP_UINT8 | 1B | x1 | AI confidence 0-100% |
| 10 | pi_heartbeat | ABP_UINT16 | 2B | x1 | Incrementing counter (watchdog) |
| **Total** | | | **17B** | | |

### Process Data Write (PLC → Pi)

| ADI # | Tag | ABP Type | Size | Scale | Description |
|-------|-----|----------|------|-------|-------------|
| 11 | cmd_run | ABP_BOOL | 1B | | Remote run command |
| 12 | cmd_speed_pct | ABP_UINT16 | 2B | x10 | Requested speed 0-100.0% |
| 13 | cmd_mode | ABP_UINT8 | 1B | enum | 0=manual,1=auto,2=maintenance |
| 14 | cmd_reset_fault | ABP_BOOL | 1B | | Fault reset command |
| **Total** | | | **5B** | | |

**Total process data: 22 bytes** (well within 4096B max).

---

## ADI Direction Naming (CONFUSING — memorize this)

- **PD_READ** = "the network READS from the host" = Pi → PLC (Pi publishes, PLC reads)
- **PD_WRITE** = "the network WRITES to the host" = PLC → Pi (PLC sends, Pi receives)

The naming is from the NETWORK's perspective, not the host's.

---

## Protocol Recommendation

**Start with Modbus TCP** (module: AB6603-E).

Reasons:
1. Proven Modbus TCP comms with Micro820 (ModbusTagSource works)
2. Straightforward register mapping, any Modbus tool can debug
3. No EDS files or assembly config needed
4. Less PLC-side configuration

**EtherNet/IP (AB6651) later** — native Allen-Bradley protocol, implicit messaging, CIP safety.

### Modbus TCP Register Layout

- Holding Regs 0x0000-0x0008: Process Data Read (ADIs 1-10, 17B → 9 registers)
- Holding Regs 0x0300+: Individual ADI access (16 registers per ADI)
- Coils 0x0000+: Bit-level access to boolean ADIs

---

## Architecture: Anybus vs ModbusTagSource

**They are COMPLEMENTARY, not alternatives. They run in PARALLEL.**

```
EXISTING:  Micro820 PLC ──Modbus TCP──→ Pi (ModbusTagSource reads PLC tags)
                                         Data flow: PLC → Pi

ANYBUS:    Pi ──SPI──→ CompactCom 40 ──Network──→ Micro820 PLC
                                         Data flow: Pi → PLC (and PLC → Pi commands)
```

- **ModbusTagSource**: Pi reads raw PLC I/O (coils 0-17, registers 100-105)
- **AnybusTagSource**: Pi publishes processed data (belt RPM, AI results) TO the PLC network, and receives PLC commands (run, speed setpoint)

---

## Bridge Layer: Unix Domain Socket

**Path:** `/run/abcc/process_data.sock`
**Protocol:** JSON lines (newline-delimited JSON objects)

```
C→Python: {"type":"pd_write","adis":{"11":true,"12":500,"13":0,"14":false}}
Python→C: {"type":"pd_read","adis":{"1":452,"2":750,"3":1,"10":12345}}
```

Why Unix socket over alternatives:
- Simple in both C (POSIX) and Python (stdlib `socket`)
- ~0.1ms latency
- Bidirectional
- Debuggable with `socat`

---

## Host App Lifecycle

1. `Init()` — open log file, set console mode
2. `ABCC_API_Init()` — initialize driver, open SPI/GPIO
3. Main loop: `ABCC_API_Run()` cyclically
4. Timer thread: `ABCC_API_RunTimerSystem(50)` every 50ms
5. State machine: SETUP → NW_INIT → WAIT_PROCESS → **PROCESS_ACTIVE**
6. Process data exchange only in PROCESS_ACTIVE state

---

## Build Requirements (Pi)

```bash
sudo raspi-config  # Interface Options → SPI → Enable
sudo apt install libgpiod-dev gpiod cmake build-essential
# Verify: ls /dev/spidev0.0
# Verify: gpiodetect → gpiochip0
# Host app must run as root
```

---

## HMS Reference Repos

- Host app example: `github.com/hms-networks/abcc-example-raspberrypi`
- Python REST client: `github.com/hms-networks/hms-abcc40` (metadata only, Python 2!)
- Driver API: `github.com/hms-networks/abcc-driver-api`
- Driver: `github.com/hms-networks/abcc-driver`
- Tech support SPI article: KB 22794171326994

---

## Gap Report Summary

| Priority | Item | Status |
|----------|------|--------|
| P1 | Pi SPI enabled + verified | MISSING |
| P1 | libgpiod V2 installed | MISSING |
| P1 | C host app cloned + ADI table modified + compiled | MISSING |
| P1 | Unix socket bridge (C side) | MISSING |
| P1 | CompactCom hardware (AB6603-E) physically installed | UNKNOWN |
| P2 | Unix socket bridge (Python side) | MISSING |
| P2 | AnybusTagSource class | MISSING |
| P2 | Poller integration (parallel, not priority) | MISSING |
| P2 | ANYBUS_HARDWARE env var | MISSING |
| P2 | systemd service for C host app | MISSING |
| P3 | Tests (mock socket) | MISSING |
| P3 | Panel UI anybus status | MISSING |
