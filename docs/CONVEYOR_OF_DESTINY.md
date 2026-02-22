# Conveyor of Destiny

**Type a command. Move a machine. From anywhere on Earth.**

> Complete playbook: physical wiring → PLC program → FactoryLM edge stack → internet control demo.
> One file. Everything a human needs to wire it, program it, connect it to the internet, and let anyone on Earth move a real conveyor belt in Lake Wales, FL.

---

## Table of Contents

1. [The Big Idea](#1-the-big-idea)
2. [Three-Hour Build Timeline](#2-three-hour-build-timeline)
3. [Physical Wiring](#3-physical-wiring)
4. [ATO VFD Setup](#4-ato-vfd-setup)
5. [PLC Program](#5-plc-program)
6. [FactoryLM Edge Connection](#6-factorylm-edge-connection)
7. [Internet Control Layer — Turn-Based Game](#7-internet-control-layer--turn-based-game)
8. [Webcam Setup](#8-webcam-setup)
9. [Data Collection](#9-data-collection)
10. [Safety](#10-safety)
11. [Claude Code Pump Prompt](#11-claude-code-pump-prompt)
12. [Test & Verification Checklist](#12-test--verification-checklist)

---

## 1. The Big Idea

**You're the Factory Manager.**

A real Allen-Bradley Micro820 PLC spins a real ATO VFD-driven conveyor belt. You're watching it on a live webcam. You type `left` or `right` — and the belt moves. From your couch. From Tokyo. From anywhere with internet.

This is FactoryLM's product in miniature: natural language → real machine control.

### The Hook

- Real machine. Real motor. Real belt. Live webcam.
- Two actions: `left` or `right` — belt moves until the photoeye trips, then your turn ends.
- Turn-based crowd control: one person at a time, FIFO queue, position indicator.
- AI narrates after each turn: *"Belt moved right 4.2 feet in 3.1 seconds, motor drew 2.8A"*
- Colored blocks on the belt make direction visually obvious on camera.

### Tagline

> "Type a command. Move a machine. From anywhere on Earth."

---

## 2. Three-Hour Build Timeline

| Hour | What | Done When |
|------|------|-----------|
| **1** | Wire all I/O + RS485 + VFD power | Meter shows no shorts, 24V present on common rail |
| **2** | Set VFD params + write CCW program + download | PLC online, input LEDs match physical switches |
| **3** | Functional test all modes + Modbus readback | Motor runs FWD/REV on command, freq/current reads back via Modbus |

---

## 3. Physical Wiring

### PLC Model

**Allen-Bradley Micro 820** — Model 2080-LC30-48QWB
- 12 digital inputs, 8 digital outputs
- Embedded serial port (RS485)
- Modbus TCP on port 502
- Firmware v12

### Input Strip Table

| Terminal | Signal | Wire Color | Description |
|----------|--------|------------|-------------|
| I-00 | 3-pos switch CENTER | Blue | Selector center position |
| I-01 | E-Stop NO contact | Blue | Normally-open (ON when pressed) |
| I-02 | E-Stop NC contact | Blue | Normally-closed (ON when released) |
| I-03 | 3-pos switch RIGHT | Blue | Selector right position |
| I-04 | Green pushbutton | Blue | Dead-man / momentary start |
| COM0 | Common | Blue | Input common tied to 24VDC rail |

### Output Strip Table

| Terminal | Signal | Wire Color | Description |
|----------|--------|------------|-------------|
| O-00 | VFD FWD / Indicator LED | White | Forward command or pendant LED 1 |
| O-01 | VFD REV / E-stop LED | White | Reverse command or pendant LED 2 |
| O-02 | Pendant LED 3 | White | Status indicator |
| O-03 | Pendant LED 4 | White | Status indicator |
| +CM0/-CM0 | Output common group 1 | — | Shared ground for O-00 to O-03 |
| +CM1/-CM1 | Output common group 2 | — | Aux output group |

### RS485 Wiring — PLC to ATO VFD

```
Micro 820 Embedded Serial Port          ATO VFD
┌─────────────────────────┐             ┌──────────┐
│  Pin 1  (485+)  ────────┼─── A+ ────→│  485+    │
│  Pin 2  (485-)  ────────┼─── B- ────→│  485-    │
│  Shield (GND)   ────────┼─── ⏚  ────→│  (N/C)   │
└─────────────────────────┘             └──────────┘
        ▲
        │ Ground shield at PLC end ONLY
        │ (prevents ground loops)
        │
     Use shielded twisted pair cable
```

**Critical:** Delete the default CIP Serial driver in Connected Components Workbench (CCW) before wiring. The embedded serial port must be reconfigured as Modbus RTU Master.

### Complete Wire List (12 Wires)

| # | From | To | Color | Purpose |
|---|------|-----|-------|---------|
| 1 | E-Stop terminal 1 | PLC I/0 | Blue | NC contact signal |
| 2 | E-Stop terminal 2 | Common rail | Blue | NC common return |
| 3 | Green Btn pin 3 | PLC I/1 | Blue | NO contact signal |
| 4 | Green Btn pin 4 | Common rail | Blue | NO common return |
| 5 | Selector FWD output | PLC I/2 | Blue | Forward position signal |
| 6 | Selector REV output | PLC I/3 | Blue | Reverse position signal |
| 7 | Selector common | Common rail | Blue | Selector common return |
| 8 | Common rail | PLC C1 | Blue | Input common bus |
| 9 | PLC V1 | Common rail | Red | 24VDC supply to switches/buttons |
| 10 | PLC O/0 | VFD FWD terminal | White | Forward run command |
| 11 | PLC O/1 | VFD REV terminal | White | Reverse run command |
| 12 | PLC C2 | VFD DCM terminal | Black | Digital common reference |

### 24VDC Power Distribution

```
PLC V1 (24VDC out) ──Red──→ Common Rail
                              │
                    ┌─────────┼─────────┐
                    │         │         │
                 E-Stop   Green Btn  Selector
                 term 2    pin 4     common
```

### E-Stop Dual-Contact Truth Table

| State | DI_01 (coil 8) NO | DI_02 (coil 9) NC | Fault? |
|-------|-------------------|-------------------|--------|
| Released (normal) | OFF | ON | No |
| Pressed (fault) | ON | OFF | **YES** |
| Wiring fault (both same) | same | same | **YES** |

**Fault detection logic:** `fault_alarm = e_stop_active AND NOT e_stop_nc`

The dual-contact design catches wiring faults — if both contacts read the same state, something is wrong.

### 3-Position Switch Truth Table

| Position | DI_00 (coil 7) | DI_03 (coil 10) | Result |
|----------|----------------|-----------------|--------|
| LEFT (REV) | OFF | OFF | Reverse |
| CENTER (OFF) | ON | OFF | Neutral/Stop |
| RIGHT (FWD) | ON | ON | Forward |

### Operation Truth Table

| E-Stop | Green Btn | Selector | Motor |
|--------|-----------|----------|-------|
| PRESSED | Any | Any | **STOP** |
| UP | Released | Any | **STOP** |
| UP | HELD | FWD | Forward @ set speed |
| UP | HELD | REV | Reverse @ set speed |
| UP | HELD | Neutral | **STOP** |

---

## 4. ATO VFD Setup

### 8 Critical Parameters

| Param | Set To | Purpose |
|-------|--------|---------|
| **P0.01** | 4 | Frequency source = serial/Modbus |
| **P0.03** | 2 | Run command source = serial/Modbus |
| **P0.04** | 30.00 | Max frequency (Hz) |
| **P0.05** | 3.0 | Acceleration time (seconds) |
| **P0.06** | 3.0 | Deceleration time (seconds) |
| **P3.09** | 163 | Comm config: 9600 baud, 8N1, Modbus RTU |
| **P3.10** | 1 | Modbus slave address |
| **P3.11** | 2 | Response delay (2 ms) |

### Motor Nameplate Reference

Match these to your actual motor:
- HP: 0.5 or 1.0
- Voltage: 230V
- Base frequency: 60 Hz (or motor nameplate)
- RPM: ~1725 (typical 4-pole)

### Speed Calculation

For the demo, target ~300 RPM (slow, safe, visible on camera):

```
Target RPM: 300
Motor nameplate RPM: 1725
Motor nameplate Hz: 60

Frequency = (300 / 1725) × 60 = 10.4 Hz → set ~10 Hz
```

At P0.04 = 30.00 Hz max, the Modbus setpoint for 10 Hz = `1000` (value × 100).

### Modbus RTU Register Map (RS485)

#### Write Registers

| Register | Address | Values | Description |
|----------|---------|--------|-------------|
| Control Word | 0x2000 | `0x0001` = Run FWD | Start motor forward |
| | | `0x0003` = Run REV | Start motor reverse |
| | | `0x0007` = Stop | Stop motor |
| Freq Setpoint | 0x2001 | Value × 100 | e.g. `3000` = 30.00 Hz, `1000` = 10.00 Hz |

#### Read Registers

| Register | Address | Scale | Description |
|----------|---------|-------|-------------|
| Actual Frequency | 0x2103 | ÷ 100 = Hz | e.g. `1000` → 10.00 Hz |
| Actual Current | 0x2104 | ÷ 10 = Amps | e.g. `28` → 2.8 A |

### MSG Block Timing Diagram

The PLC and VFD share one RS485 bus. Only one MSG block can be active at a time.

```
Time ──────────────────────────────────────────────────→

Write MSG:  ████████░░░░░░░░░░░░████████░░░░░░░░░░░░
Read MSG:   ░░░░░░░░████████░░░░░░░░░░░░████████░░░░
                     ▲               ▲
              write_done=TRUE  write_done=TRUE
              triggers Read    triggers Read

Cycle: Write → wait → Read → wait → Write → ...
No bus collisions. Clean alternating.
```

---

## 5. PLC Program

### CCW Serial Port Configuration

**Before programming:**

1. Open Connected Components Workbench (CCW)
2. Navigate to the Micro 820 project → Serial Port
3. **Delete** the default CIP Serial driver
4. **Add** Modbus RTU driver:
   - Mode: Master
   - Baud: 9600
   - Data bits: 8
   - Parity: None
   - Stop bits: 1
   - Slave address: 1 (for the ATO VFD)

### CCW Tag Definitions

| Tag Name | Type | Address | Description |
|----------|------|---------|-------------|
| System_Ready | BOOL | — | 3-pos switch not in OFF |
| Run_Permitted | BOOL | — | System ready AND E-stop released |
| fault_alarm | BOOL | — | Derived: DI_01 AND NOT DI_02 |
| VFD_ActualFreq | INT | HR 40001 | Hz × 100 from VFD |
| VFD_ActualCurrent | INT | HR 40002 | Amps × 10 from VFD |
| ConveyorRunning | BOOL | HR 40003 | Motor status |
| ConveyorDirection | INT | HR 40004 | 0=Stop, 1=FWD, 2=REV |
| EStopActive | BOOL | HR 40005 | E-stop pressed |
| FaultCode | INT | HR 40006 | Error code |

### Ladder Logic (6 Rungs)

```
RUNG 0 — System Ready:
──┤ DI_00 ├──────────────────────────────────────( System_Ready )

RUNG 1 — Run Permission:
──┤ System_Ready ├──┤ DI_01 ├────────────────────( Run_Permitted )

RUNG 2 — Forward Command:
──┤ Run_Permitted ├──┤ DI_02 ├──┤/ DO_01 ├───────( DO_00 )  [VFD FWD]

RUNG 3 — Reverse Command:
──┤ Run_Permitted ├──┤ DI_03 ├──┤/ DO_00 ├───────( DO_01 )  [VFD REV]

RUNG 4 — (reserved for Modbus MSG write)

RUNG 5 — (reserved for Modbus MSG read)

RUNG 6 — Fault Detection:
──┤ DI_01 ├──┤/ DI_02 ├──────────────────────────( fault_alarm )
```

**Interlock logic:**
- Rung 2: Forward only runs if Run_Permitted AND FWD switch AND Reverse is NOT active
- Rung 3: Reverse only runs if Run_Permitted AND REV switch AND Forward is NOT active
- Rung 6: Fault alarm if NO contact active AND NC contact NOT active (dual-contact validation)

### Structured Text Control Logic (Alternative)

```iecst
PROGRAM ConveyorControl
    VAR
        System_Ready   : BOOL;
        Run_Permitted  : BOOL;
        fault_alarm    : BOOL;
        VFD_Control    : INT;
        VFD_Setpoint   : INT;
    END_VAR

    // Fault detection — dual-contact E-stop validation
    fault_alarm := _IO_EM_DI_01 AND NOT _IO_EM_DI_02;

    // System ready — selector not in OFF position
    System_Ready := _IO_EM_DI_00;

    // Run permission — system ready AND no fault
    Run_Permitted := System_Ready AND NOT fault_alarm;

    // E-stop override — kill everything
    IF fault_alarm THEN
        _IO_EM_DO_00 := FALSE;  // FWD off
        _IO_EM_DO_01 := FALSE;  // REV off
        VFD_Control := 16#0007; // VFD stop command
        RETURN;
    END_IF;

    // Forward — selector RIGHT + button held + reverse not active
    IF Run_Permitted AND _IO_EM_DI_03 AND _IO_EM_DI_04 AND NOT _IO_EM_DO_01 THEN
        _IO_EM_DO_00 := TRUE;
        VFD_Control := 16#0001;  // Run FWD
        VFD_Setpoint := 1000;    // 10.00 Hz
    // Reverse — selector LEFT + button held + forward not active
    ELSIF Run_Permitted AND NOT _IO_EM_DI_00 AND _IO_EM_DI_04 AND NOT _IO_EM_DO_00 THEN
        _IO_EM_DO_01 := TRUE;
        VFD_Control := 16#0003;  // Run REV
        VFD_Setpoint := 1000;    // 10.00 Hz
    ELSE
        _IO_EM_DO_00 := FALSE;
        _IO_EM_DO_01 := FALSE;
        VFD_Control := 16#0007;  // Stop
        VFD_Setpoint := 0;
    END_IF;

END_PROGRAM
```

---

## 6. FactoryLM Edge Connection

**Write → Download → Run → Supervise**

### Architecture

```
Internet (Discord / Web / Telegram)
         │
         ▼
  FactoryLM Matrix (VPS 100.68.120.99)
         │ task dispatch via Tailscale
         ▼
  Edge Gateway (pymodbus over Tailscale)
         │ Modbus TCP, ~33ms latency
         ▼
  Micro 820 PLC (192.168.1.100:502)
         │ RS485 Modbus RTU
         ▼
  ATO VFD ──► Motor ──► Conveyor Belt
```

### Phase: Write

**LLM4PLC** (`llm4plc.py`) generates IEC 61131-3 Structured Text from templates or natural language descriptions.

Three built-in templates:
- **ConveyorControl** — Start on sensor_1 rising edge, stop on sensor_2 rising edge, E-stop override
- **MotorSafety** — Temperature limit 80.0°C, current limit 10.0A, fault_alarm + error_code, manual reset required
- **SortingStation** — 4-state machine (idle → running → sorting → fault), part counting, dual safety thresholds

Micro 820 compatibility is validated automatically:
- No POINTER types
- No REFERENCE types
- No CLASS constructs
- No global variable redeclaration in local scope

### Phase: Download

1. CCW compiles the ST program
2. Download to PLC via USB or Ethernet (192.168.1.100)
3. Switch PLC to RUN mode

### Phase: Run

Remote start/stop via Modbus TCP:

```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('192.168.1.100', port=502, timeout=3)
client.connect()

# Start the conveyor remotely
client.write_coil(address=4, value=True)   # RunCommand coil

# Stop
client.write_coil(address=4, value=False)
```

Or via the FastAPI edge gateway:

```bash
# Start
curl -X POST http://100.72.2.99:8765/api/plc/write-coil \
  -H "Content-Type: application/json" \
  -d '{"address": 4, "value": true}'

# Health check
curl http://100.72.2.99:8765/health
```

### Phase: Supervise

**edge_gateway.py** polls 18 coils + 6 registers over the Tailscale mesh network.

Poll schedule:
- Health check: every 60 seconds
- Register read: every 5 seconds
- Coil read: every 5 seconds

**diagnosis_engine.py** derives `fault_alarm` from raw coil states and feeds AI diagnosis via Cosmos Reason 2.

Dashboard available at `localhost:8000`.

### Master Coil Map (Addresses 0–17)

| Addr | Tag | Direction | Description |
|------|-----|-----------|-------------|
| 0 | Conveyor | PLC → FIO | Belt motor command |
| 1 | Emitter | PLC → FIO | Item spawner |
| 2 | SensorStart | FIO → PLC | Entry photoeye |
| 3 | SensorEnd | FIO → PLC | Exit photoeye |
| 4 | RunCommand | Remote | API/Telegram trigger |
| 5–6 | *(reserved)* | — | — |
| 7 | _IO_EM_DI_00 | Physical | 3-pos switch CENTER |
| 8 | _IO_EM_DI_01 | Physical | E-stop NO contact |
| 9 | _IO_EM_DI_02 | Physical | E-stop NC contact |
| 10 | _IO_EM_DI_03 | Physical | 3-pos switch RIGHT |
| 11 | _IO_EM_DI_04 | Physical | Green pushbutton |
| 12–14 | _IO_EM_DI_05–07 | Physical | Unused inputs |
| 15 | _IO_EM_DO_00 | Physical | Indicator LED / VFD FWD |
| 16 | _IO_EM_DO_01 | Physical | E-stop LED / VFD REV |
| 17 | _IO_EM_DO_03 | Physical | Aux output |

### Master Register Map (Addresses 100–105)

| Addr | Tag | Scale | Description |
|------|-----|-------|-------------|
| 100 | item_count | 1× | Items that reached SensorEnd |
| 101 | motor_speed | 1× | Speed 0–100% |
| 102 | motor_current | ÷ 10 | Amps (e.g. 28 → 2.8A) |
| 103 | temperature | ÷ 10 | Degrees C (e.g. 420 → 42.0°C) |
| 104 | pressure | 1× | PSI |
| 105 | error_code | 1× | 0=OK, 1=Overload, 2=Overheat, 3=Jam, 4=Sensor, 5=Comms |

### pymodbus Quick Reference

```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('192.168.1.100', port=502, timeout=3)
client.connect()

# Read all 18 coils
result = client.read_coils(address=0, count=18)
bits = [int(b) for b in result.bits[:18]]
# bits[0]  = Conveyor (motor command)
# bits[2]  = SensorStart (entry photoeye)
# bits[3]  = SensorEnd (exit photoeye)
# bits[7]  = 3-pos switch center
# bits[8]  = E-stop NO
# bits[9]  = E-stop NC
# bits[11] = Green pushbutton

# Read 6 holding registers
regs = client.read_holding_registers(address=100, count=6)
motor_speed    = regs.registers[1]           # 0-100%
motor_current  = regs.registers[2] / 10.0    # Amps
temperature    = regs.registers[3] / 10.0    # °C
error_code     = regs.registers[5]           # 0=OK

# Write a single coil
client.write_coil(address=15, value=True)    # Turn on indicator LED

# Derived fault detection
fault_alarm = bits[8] and not bits[9]  # E-stop NO active AND NC not active

client.close()
```

### Raspberry Pi Edge Device

For physical GPIO bridging (optional — extends the system to real buttons/LEDs beyond the PLC):

- Pi IP: 192.168.1.200, port 502 (or 5020 without sudo)
- Runs `edge_server.py` — Modbus TCP server with GPIO sync
- GPIO mapping: BCM pin numbers

| Function | Coil | GPIO (BCM) | Physical Pin |
|----------|------|------------|-------------|
| Start Button | 0 | GPIO17 | Pin 11 |
| Stop Button | 1 | GPIO27 | Pin 13 |
| E-Stop | 2 | GPIO22 | Pin 15 |
| LED Green | 10 | GPIO5 | Pin 29 |
| LED Red | 11 | GPIO6 | Pin 31 |
| Relay 1 | 12 | GPIO13 | Pin 33 |
| Relay 2 | 13 | GPIO19 | Pin 35 |

Install and enable as systemd service:

```bash
cd factorylm-edge && sudo ./install.sh
sudo systemctl enable factorylm-edge
sudo systemctl start factorylm-edge
sudo journalctl -u factorylm-edge -f
```

### Jarvis Node (Remote Laptop Control)

The Jarvis Node (`remoteme-jarvis-node`) runs on each machine, exposing:
- `/health` — connectivity check
- `/shell` — execute commands remotely
- `/files/read` — read files remotely

```bash
# Check PLC laptop is online
curl http://100.72.2.99:8765/health

# Execute a command on PLC laptop
curl -X POST http://100.72.2.99:8765/shell \
  -H "Content-Type: application/json" \
  -d '{"command": "python --version", "timeout": 30}'
```

---

## 7. Internet Control Layer — Turn-Based Game

**This is the viral demo.**

### Game Mechanic

Dead simple. User types `left` or `right`. That's it.

The belt moves in that direction at a predetermined safe speed until it trips the photoeye at that end. Their turn is over. Next person goes.

### Turn Lifecycle

```
User types "right"
  │
  ├─ Queue check: is it their turn?
  │   ├─ NO → Add to queue, show position: "You're #3, ~45 sec wait"
  │   └─ YES ↓
  │
  ├─ Write VFD forward command via Modbus
  │   └─ write_coil(0, True) + VFD control word 0x0001
  │
  ├─ Belt moves right →→→→→→→→→→→→→
  │
  ├─ SensorEnd photoeye trips (coil 3)
  │   └─ PLC stops belt automatically
  │
  ├─ Read telemetry: duration, distance, motor current, frequency
  │
  ├─ AI narrates: "Belt moved right 4.2 ft in 3.1 sec, motor drew 2.8A"
  │
  └─ Turn ends → next person in queue gets notified
```

### Queue System

- **FIFO** — first come, first served
- User gets a position number on entry: *"You're #3 in line, ~45 seconds wait"*
- When their turn starts: *"It's your turn! Type `left` or `right`"*
- **10-second timeout** to type a command or they're skipped
- One person at a time — prevents command flooding
- AI narrates each turn with real telemetry data

### Discord — `#conveyor-live` Channel

**Commands:** `left`, `right` — that's it.

**Status embed after each turn:**

```
🏭 FactoryLM Conveyor
━━━━━━━━━━━━━━━━━━━━
Last move:   ◀ LEFT
Distance:    4.2 ft
Time:        3.1 sec
Motor:       40.2 Hz / 2.8A
Moved by:    @user
Queue:       2 waiting
━━━━━━━━━━━━━━━━━━━━
📺 Watch live → [YouTube link]
```

### GitHub — README Live Badge

Conveyor status badge at top of the factorylm repo README:

```markdown
[![Conveyor Status](https://img.shields.io/badge/conveyor-ONLINE-green)](https://factorylm.com/demo)
```

Links to watch live + control it.

### factorylm.com — `/demo` Control Panel

**Top half:** Embedded YouTube/Cloudflare live stream of the belt

**Bottom half:**
- Two big buttons: **◀ LEFT** | **RIGHT ▶**
- Queue indicator: *"3 people in line"* or *"Your turn!"*
- Live status bar (auto-refresh every 2 seconds):
  - Last direction
  - Motor Hz
  - Belt position
- Turn log: last 10 turns with usernames and timestamps
- **No login required** — open to anyone

### Cosmos Cookoff Submission Page

For the judges:

- Narrative: *"This isn't a simulation — you're looking at the product."*
- Embedded live stream + control buttons
- Judges can move the belt from the review page
- Real telemetry displayed alongside the video

---

## 8. Webcam Setup

### Mount Requirements

- **Angle:** Entire belt visible, slight downward angle (~30° above horizontal)
- **Position:** Side-on or 3/4 view so direction is obvious
- **Props:** Place colored cubes/blocks on the belt — makes direction visually obvious on camera

### Streaming Options

| Option | Complexity | Latency | Cost |
|--------|-----------|---------|------|
| **YouTube Live** | Simplest | ~5-10s | Free |
| Restream.io | Multi-platform | ~5-10s | Free tier available |
| Cloudflare Stream | Lowest latency | ~2-3s | Pay per minute |

**Recommendation:** Start with YouTube Live. It's free, stable, and embeddable.

### Stream Key Setup (YouTube Live)

1. Go to YouTube Studio → Go Live
2. Copy the stream key
3. In OBS or similar: set stream key, 720p, 30fps
4. Scene: webcam pointed at belt, "FactoryLM" overlay in corner
5. Start streaming

---

## 9. Data Collection

### What Gets Logged

Every turn generates a data point:

| Field | Source | Example |
|-------|--------|---------|
| direction | User command | `right` |
| duration_sec | Timestamp delta | 3.1 |
| distance_ft | Calculated from speed × time | 4.2 |
| motor_freq_hz | Register 0x2103 ÷ 100 | 10.0 |
| motor_current_a | Register 0x2104 ÷ 10 | 2.8 |
| user | Discord/web username | `@factoryfan42` |
| timestamp | ISO 8601 | `2026-02-22T14:30:00Z` |
| platform | Source | `discord` / `web` / `telegram` |

### 24/7 Data Builds Real Training Dataset

Running this continuously generates labeled motor events:

- **Motor current per direction/speed** — does forward draw more than reverse?
- **Acceleration/deceleration curves** — current spikes during ramp-up
- **Photoeye trip timing** — belt travel time = distance / speed (consistency check)
- **Human command patterns** — do people prefer left or right? (behavioral data)
- **Fault events** — if a jam occurs, we have the current/temperature leading up to it

### The Pitch

> *"We generated 10,000 labeled motor events from a live physical system that anyone on the internet can interact with."*

This feeds Cosmos Reason 2 training — real industrial data, not simulated.

---

## 10. Safety

### Defense in Depth

| Layer | Mechanism | Who Controls |
|-------|-----------|-------------|
| **Hardware** | Physical E-stop button (dual-contact) | Anyone at the machine |
| **PLC** | Photoeye auto-stop at belt ends | Automatic |
| **PLC** | Dual-contact E-stop validation | Automatic |
| **Software** | Fixed speed — no public speed control | System config |
| **Software** | Queue system — 1 user at a time | Automatic |
| **Software** | Software E-stop — `/estop` command | Mike only |
| **Network** | Tailscale mesh — no open ports | System config |

### Hardware E-Stop

Always wired. Always functional. Dual-contact validation catches wiring faults.

- NC contact (coil 9): ON when released (normal)
- NO contact (coil 8): ON when pressed (fault)
- `fault_alarm = coil[8] AND NOT coil[9]`
- If both contacts read the same → wiring fault → treated as E-stop

### Belt Auto-Stop

The belt **cannot overrun** — it always stops when the photoeye trips:

- SensorEnd (coil 3) trips → PLC stops motor → turn ends
- SensorStart (coil 2) trips → PLC stops motor → turn ends
- This is PLC logic, not software — it runs even if the internet stack is down

### Fixed Speed

Public users cannot set speed. The VFD frequency setpoint is fixed in the PLC program. The demo uses ~10 Hz (≈300 RPM) — slow, safe, visible on camera.

### Software E-Stop

Hidden URL or Telegram command — only Mike can trigger:

```bash
# Telegram (via Clawdbot)
/estop

# Direct API
curl -X POST http://100.72.2.99:8765/api/plc/write-coil \
  -H "Content-Type: application/json" \
  -d '{"address": 4, "value": false}'
```

### Queue Flood Protection

One user at a time. 10-second timeout per turn. FIFO queue. No way to spam commands — the queue enforces sequential access.

---

## 11. Claude Code Pump Prompt

Paste this into Claude Code on the PLC laptop to generate all project files:

````
You are setting up the "Conveyor of Destiny" — an internet-controlled conveyor belt demo.

## Hardware Context

**PLC:** Allen-Bradley Micro 820 (2080-LC30-48QWB), IP 192.168.1.100, Modbus TCP port 502
**VFD:** ATO VFD, RS485 Modbus RTU slave address 1, 9600 baud 8N1
**Motor:** 0.5-1.0 HP, 230V, ~1725 RPM nameplate

## I/O Map

### Coils (0-17)
- 0: Conveyor (belt motor command, PLC→FIO)
- 1: Emitter (item spawner, PLC→FIO)
- 2: SensorStart (entry photoeye, FIO→PLC)
- 3: SensorEnd (exit photoeye, FIO→PLC)
- 4: RunCommand (remote API trigger)
- 7: _IO_EM_DI_00 (3-pos switch CENTER)
- 8: _IO_EM_DI_01 (E-stop NO)
- 9: _IO_EM_DI_02 (E-stop NC)
- 10: _IO_EM_DI_03 (3-pos switch RIGHT)
- 11: _IO_EM_DI_04 (Green pushbutton)
- 15: _IO_EM_DO_00 (Indicator LED / VFD FWD)
- 16: _IO_EM_DO_01 (E-stop LED / VFD REV)

### Holding Registers (100-105)
- 100: item_count (1×)
- 101: motor_speed (1×, 0-100%)
- 102: motor_current (÷10, Amps)
- 103: temperature (÷10, °C)
- 104: pressure (1×, PSI)
- 105: error_code (0=OK, 1=Overload, 2=Overheat, 3=Jam, 4=Sensor, 5=Comms)

### VFD Modbus Registers (RS485)
- Write 0x2000: control word (0x0001=FWD, 0x0003=REV, 0x0007=Stop)
- Write 0x2001: freq setpoint (×100, e.g. 1000=10.00Hz)
- Read 0x2103: actual freq (÷100)
- Read 0x2104: actual current (÷10)

## What to Generate

1. **FastAPI server** (`conveyor_api.py`):
   - POST `/move` — accepts `{"direction": "left"|"right"}`, writes Modbus command, waits for photoeye trip, returns telemetry
   - GET `/status` — reads all 18 coils + 6 registers, returns JSON
   - POST `/estop` — emergency stop (auth required)
   - WebSocket `/ws` — real-time status stream every 2 seconds

2. **Queue manager** (`queue_manager.py`):
   - FIFO queue, one user at a time
   - 10-second timeout per turn
   - Position indicator
   - Callback on turn completion

3. **Discord bot** (`discord_bot.py`):
   - Listens in #conveyor-live
   - Commands: `left`, `right`
   - Posts status embed after each turn
   - Integrates with queue manager

4. **Turn logger** (`turn_logger.py`):
   - Logs every turn: direction, duration, current, freq, user, timestamp
   - SQLite database
   - Export to CSV

Use pymodbus for Modbus TCP. Use discord.py for the bot. Use FastAPI + uvicorn for the API.
````

---

## 12. Test & Verification Checklist

### Phase 1: VFD Manual Test (Keypad)

- [ ] VFD powered on, display shows frequency
- [ ] Set P0.01=0 (keypad frequency source, temporarily)
- [ ] Set P0.03=0 (keypad run command, temporarily)
- [ ] Press RUN on keypad — motor spins forward
- [ ] Press STOP — motor stops
- [ ] Set frequency to 10 Hz — motor runs at ~300 RPM
- [ ] Reset P0.01=4, P0.03=2 (back to Modbus control)

### Phase 2: PLC I/O Test (Force in CCW)

- [ ] PLC powered on, connected via USB or Ethernet
- [ ] CCW shows PLC in PROGRAM mode
- [ ] Toggle E-stop — DI_01 and DI_02 change correctly
- [ ] Toggle 3-pos switch — DI_00 and DI_03 change correctly
- [ ] Press green button — DI_04 goes TRUE
- [ ] Force DO_00 TRUE in CCW — VFD FWD terminal sees 24V
- [ ] Force DO_01 TRUE in CCW — VFD REV terminal sees 24V
- [ ] Unforce all, switch PLC to RUN mode

### Phase 3: VFD Under PLC Control

- [ ] Selector to FWD, hold green button — motor runs forward
- [ ] Release green button — motor stops
- [ ] Selector to REV, hold green button — motor runs reverse
- [ ] Release green button — motor stops
- [ ] Press E-stop — motor stops immediately, fault_alarm activates
- [ ] Release E-stop, reset — system returns to normal

### Phase 4: Modbus Readback Verification

- [ ] PLC program includes MSG blocks for RS485 communication
- [ ] Read 0x2103 returns actual frequency (matches VFD display)
- [ ] Read 0x2104 returns actual current (reasonable value, non-zero when running)
- [ ] Write 0x2000 = 0x0001 — motor starts forward via Modbus
- [ ] Write 0x2000 = 0x0007 — motor stops via Modbus
- [ ] MSG timing: write and read alternate cleanly (no bus collisions)

### Phase 5: Edge Gateway → Modbus TCP → Dashboard

- [ ] `edge_gateway.py` connects to PLC at 192.168.1.100:502
- [ ] Read coils 0-17 returns valid data
- [ ] Read registers 100-105 returns valid data
- [ ] `write_coil(4, True)` starts conveyor remotely
- [ ] `write_coil(4, False)` stops conveyor remotely
- [ ] Health check returns latency < 100ms over local network
- [ ] Over Tailscale: latency < 50ms

### Phase 6: Internet Control End-to-End

- [ ] Webcam streaming to YouTube Live (belt visible, blocks visible)
- [ ] Discord bot online in `#conveyor-live`
- [ ] Type `right` in Discord — belt moves right on camera
- [ ] Photoeye trips — belt stops automatically
- [ ] Status embed posts with telemetry data
- [ ] Type `left` — belt moves left on camera
- [ ] Queue system works: second user gets position indicator
- [ ] 10-second timeout works: idle user gets skipped
- [ ] AI narration fires after each turn
- [ ] factorylm.com/demo page loads with live stream + buttons
- [ ] Web buttons trigger belt movement
- [ ] Software E-stop (`/estop`) kills belt immediately
- [ ] Data logger captures all turns to SQLite

---

## Fault Codes Reference

From the diagnosis engine's fault classifier:

| Code | Severity | Trigger Condition |
|------|----------|-------------------|
| E001 | EMERGENCY | `e_stop_active == True` |
| M001 | CRITICAL | `motor_running AND motor_current > 5.0A` |
| T001 | CRITICAL | `temperature > 80.0°C` |
| C001 | CRITICAL | `motor_running AND sensor_1 AND sensor_2` (both photoeyes = jam) |
| M002 | CRITICAL | `NOT motor_running AND conveyor_speed > 0 AND NOT e_stop` |
| P001 | WARNING | `pressure < 60 PSI AND motor_running` |
| M003 | WARNING | `motor_running AND motor_speed < 30 AND conveyor_speed > 50` |
| T002 | WARNING | `65.0°C < temperature <= 80.0°C` |

---

## AI Integration — Cosmos Reason 2

The diagnosis engine uses NVIDIA Cosmos Reason 2 (8B) for multimodal analysis:

- **Model:** `nvidia/Cosmos-Reason2-8B`
- **Serving:** vLLM on Vast.ai L40S GPU (~$0.50/hr spot)
- **Inference params:** temperature 0.6, top_p 0.95, max_tokens 4096
- **Reasoning parser:** `qwen3` (chain-of-thought via `<think>` tags)

```bash
# Start vLLM server
nohup vllm serve nvidia/Cosmos-Reason2-8B \
    --host 0.0.0.0 --port 8000 \
    --max-model-len 16384 \
    --gpu-memory-utilization 0.9 \
    --reasoning-parser qwen3 \
    > /tmp/vllm.log 2>&1 &

# SSH tunnel to GPU box
ssh -i ~/.ssh/id_ed25519 -p <PORT> -f -N -L 8000:localhost:8000 root@<SSH_HOST>
```

Three prompt templates:
- `user_diagnosis` — PLC data + fault analysis → general diagnosis
- `user_question` — PLC data + fault analysis + specific user question
- `user_describe` — Video-only mode, no PLC data

When the PLC is unreachable, the engine falls back to video-only mode automatically.

---

## Network Map

```
┌─────────────────────────────────────────────────────────────────┐
│                     Tailscale Mesh Network                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  VPS / Jarvis (100.68.120.99)          Discord / Telegram       │
│  ┌──────────────────────┐              ┌──────────────────┐     │
│  │ Clawdbot (Telegram)  │◄────────────►│ Users / Judges   │     │
│  │ Discord Bot          │              │ factorylm.com    │     │
│  │ Queue Manager        │              └──────────────────┘     │
│  │ FactoryLM Matrix     │                                       │
│  └──────────┬───────────┘                                       │
│             │ task dispatch                                     │
│             ▼                                                   │
│  Travel Laptop (100.83.251.23)                                  │
│  ┌──────────────────────┐                                       │
│  │ Jarvis Node :8765    │                                       │
│  │ Dev / Presentation   │                                       │
│  └──────────────────────┘                                       │
│                                                                 │
│  PLC Laptop (100.72.2.99)                                       │
│  ┌──────────────────────┐     ┌──────────────┐     ┌─────────┐ │
│  │ Jarvis Node :8765    │────►│ Micro 820    │────►│ ATO VFD │ │
│  │ Edge Gateway         │     │ 192.168.1.100│     │ RS485   │ │
│  │ Conveyor API         │     │ Modbus TCP   │     │ Motor   │ │
│  │ Factory I/O          │     │ :502         │     │ Belt    │ │
│  └──────────────────────┘     └──────────────┘     └─────────┘ │
│                                                                 │
│  Vast.ai GPU                                                    │
│  ┌──────────────────────┐                                       │
│  │ vLLM + Cosmos R2 8B  │                                       │
│  │ SSH tunnel :8000     │                                       │
│  └──────────────────────┘                                       │
│                                                                 │
│  Raspberry Pi (192.168.1.200) — Optional                        │
│  ┌──────────────────────┐                                       │
│  │ factorylm-edge       │                                       │
│  │ GPIO ↔ Modbus bridge │                                       │
│  └──────────────────────┘                                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Known Discrepancies

These conflicts exist across source files. The canonical truth is this document.

| Issue | File A says | File B says | Resolution |
|-------|------------|------------|------------|
| Register 100 tag | `motor_speed` (factoryio.yaml, edge_gateway.py) | `item_count` (diagnosis_engine.py) | Use `item_count` — aligns with PLC program |
| Coil 0 tag | `motor_running` (factoryio.yaml) | `conveyor_running` (diagnosis_engine.py) | Use `Conveyor` — matches CCW tag name |
| Coils 2-3 | `fault_alarm`, `conveyor_running` (factoryio.yaml) | `SensorStart`, `SensorEnd` (CLAUDE.md, diagnosis_engine.py) | Use `SensorStart`/`SensorEnd` — matches PLC hardware |
| Sensor suffix | `sensor_1_active` (Modbus reads) | `sensor_1` (Matrix API) | Suffix stripped at Matrix boundary — both correct in context |

---

*Built with the Antfarm agentic framework.*
*FactoryLM — Type a command. Move a machine. From anywhere on Earth.*
