# Conveyor of Destiny — Complete Integration Plan

> Everything you need to wire, program, and have running under PLC control
> with Modbus feedback tonight.

## What You're Getting

This covers all 9 layers of your system in one document, built directly from
your notebook page, your I/O photos, and your existing BOM/architecture docs.

---

## 1. Wiring (Hour 1)

The exact terminal-to-terminal map matches what you've already started on the
Micro820 I/O strips.

**Input strip** (photos confirm wires landed on I-00 through I-04 with COM0):

| Terminal | Signal | Description |
|----------|--------|-------------|
| I-00     | 3-pos switch REV | Selector reverse position |
| I-01     | E-Stop NO | NO contact (TRUE when pressed) |
| I-02     | E-Stop NC | NC contact (TRUE when released) |
| I-03     | 3-pos switch FWD | Selector forward position |
| I-04     | Green pushbutton | Momentary start (dead-man) |
| COM0     | Common | Input common rail |

**Output strip** (photos confirm O-00 through O-06 with two output common
groups +CM0/-CM0 and +CM1/-CM1):

| Terminal | Signal | Description |
|----------|--------|-------------|
| O-00     | Pendant LED 1 | Status indicator |
| O-01     | Pendant LED 2 | Status indicator |
| O-02     | Pendant LED 3 | Status indicator |
| O-03     | Pendant LED 4 | Status indicator |
| +CM0/-CM0 | Output common group 1 | LED power |
| +CM1/-CM1 | Output common group 2 | LED power |

### Critical New Wire: RS485 to VFD

```
┌──────────────────────┐              ┌──────────────────────┐
│  Micro 820 PLC       │              │  ATO VFD             │
│  Embedded Serial Port│              │  RS485 Terminals     │
│                      │  Shielded    │                      │
│  Pin 1 (485+) ───────┼──twisted─────┼──► 485+              │
│  Pin 2 (485-) ───────┼──pair────────┼──► 485-              │
│  Shield ─────────────┼──ground──┐   │                      │
│                      │          │   │                      │
└──────────────────────┘          ▼   └──────────────────────┘
                              GND at
                             PLC end
                              ONLY
```

**Use shielded twisted pair.** Ground the shield at the PLC end only — do NOT
ground at the VFD end (prevents ground loops).

---

## 2. VFD Parameters (15 Minutes on the Keypad)

The ATO VFD needs exactly 8 parameters set before the PLC can talk to it:

| Param | Name | Set To | Description |
|-------|------|--------|-------------|
| **P0.01** | Frequency source | **4** | Serial/Modbus control |
| **P0.03** | Run command source | **2** | Serial/Modbus control |
| **P0.04** | Max frequency | **30.00** | 30 Hz limit (per notebook spec) |
| **P0.05** | Accel time | **3.0** | 3 seconds ramp up |
| **P0.06** | Decel time | **3.0** | 3 seconds ramp down |
| **P3.09** | Comm protocol | **163** | 9600 baud, 8N1, Modbus RTU |
| **P3.10** | Slave address | **1** | Modbus address 1 |
| **P3.11** | Response delay | **2** | 2 ms response delay |

### Motor Nameplate Parameters
Set these to match your motor:
- P1.00 = Motor rated voltage
- P1.01 = Motor rated current
- P1.02 = Motor rated frequency

---

## 3. Modbus Register Map (ATO VFD)

The ATO VFD uses Modbus RTU with these registers:

### Write Registers

| Register | Function | Values |
|----------|----------|--------|
| **0x2000** | Control word | `0x0001` = Run FWD, `0x0003` = Run REV, `0x0007` = Stop |
| **0x2001** | Frequency setpoint | Value × 100 (1500 = 15.00 Hz, 3000 = 30.00 Hz) |

### Read Registers

| Register | Function | Scale |
|----------|----------|-------|
| **0x2103** | Actual output frequency | Value ÷ 100 = Hz |
| **0x2104** | Actual output current | Value ÷ 10 = Amps |

### Examples
```
Write 0x2001 = 1500  → VFD runs at 15.00 Hz
Write 0x2001 = 3000  → VFD runs at 30.00 Hz (max per P0.04)
Read  0x2103 = 1500  → Motor actually running at 15.00 Hz
Read  0x2104 = 42    → Motor drawing 4.2 Amps
```

---

## 4. PLC Program (Structured Text)

### CCW Serial Port Setup (DO THIS FIRST)

1. Open Connected Components Workbench
2. Go to **Controller Properties → Serial Port**
3. **Delete** the default CIP Serial driver
4. Re-add the port and select **Modbus RTU** from the dropdown
5. Configure: **9600 baud, 8N1, Master mode**

### Control Logic

The ST program implements the exact control scheme:

- E-Stop overrides everything:
  - NC contact on I-02 must be closed (TRUE)
  - AND NO contact on I-01 must be open (FALSE)
- 3-position switch selects direction (I-00 REV, I-03 FWD)
- Green pushbutton (I-04) starts motor (dead-man — release = stop)
- Center position = stop

### VFD Communication

Every scan cycle:
1. Build control word based on switch/button state
2. Write control word to VFD register 0x2000
3. Write frequency setpoint to VFD register 0x2001
4. Read actual frequency from VFD register 0x2103
5. Read actual current from VFD register 0x2104

---

## 5. Modbus MSG Block Timing

**Do NOT fire the read and write MSG blocks simultaneously** — they share the
single RS485 bus.

```
┌───────────┐     done     ┌───────────┐     done     ┌───────────┐
│  WRITE    ├─────────────►│   READ    ├─────────────►│  WRITE    │
│  MSG      │              │   MSG     │              │  MSG      │
│ (0x2000,  │              │ (0x2103,  │              │ (next     │
│  0x2001)  │              │  0x2104)  │              │  cycle)   │
└───────────┘              └───────────┘              └───────────┘
```

Interlock pattern:
1. Write MSG fires first
2. When `write_done` goes TRUE → Read MSG fires
3. When `read_done` goes TRUE → Write MSG fires again
4. Clean alternating poll cycle, no bus collisions

---

## 6. AI Layer Connection (Post-Commissioning)

Once the conveyor is running under PLC control:

1. Enable the Micro820's built-in **Modbus TCP server** through CCW's
   Ethernet settings
2. Map internal tags to Modbus TCP holding registers:

| Holding Register | Internal Tag | Description |
|-----------------|--------------|-------------|
| 40001 | VFD_ActualFreq | Motor frequency (Hz × 100) |
| 40002 | VFD_ActualCurrent | Motor current (A × 10) |
| 40003 | ConveyorRunning | Run status (BOOL) |
| 40004 | ConveyorDirection | 0=Stop, 1=FWD, 2=REV |
| 40005 | EStopActive | E-stop fault (BOOL) |
| 40006 | FaultCode | Error code |

3. Python pymodbus script reads these registers over Tailscale mesh at
   2 Hz polling

```python
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient("100.72.2.99", port=502)  # PLC via Tailscale
client.connect()

# Read 6 registers starting at 40001
result = client.read_holding_registers(address=0, count=6)
freq = result.registers[0] / 100.0      # Hz
current = result.registers[1] / 10.0    # Amps
running = bool(result.registers[2])
direction = result.registers[3]         # 0/1/2
estop = bool(result.registers[4])
fault = result.registers[5]
```

This gives the AI telemetry layer live conveyor data — frequency, current
draw, run status, direction — at 2 Hz polling.

### Claude Code Pump Prompt

Section 6 context: paste into Claude Code on your PLC laptop with
`--dangerously-skip-permissions` to generate all 6 project files:
1. ST program (structured text for Micro820)
2. Ladder rungs (backup representation)
3. pymodbus reader (Python telemetry script)
4. CLAUDE.md (project context)
5. Wiring test script (I/O validation)
6. Factory I/O tag mapping (simulation bridge)

---

## 7. Three-Hour Timeline

| Hour | What | Done When |
|------|------|-----------|
| **1** | Wire all I/O + RS485 + VFD power | Meter shows no shorts, 24V present at all input commons |
| **2** | VFD params + CCW program + download | PLC online, input LEDs match switch positions |
| **3** | Functional test all modes + Modbus readback | Motor runs FWD/REV, frequency/current reads back in CCW |

---

## References

- [Micro820 User Manual (Rockwell)](https://sonicautomation.co.th/wp-content/uploads/2019/12/RA_Micro820-User-Manual.pdf) — Serial port pinout, I/O terminal layout
- [ATO VFD RS485 Control Guide](https://www.ato.com/how-to-control-vfd-via-rs485-interface) — Modbus register map, parameter settings
- [CCW Modbus RTU Setup (YouTube)](https://www.youtube.com/watch?v=ARg2QHn3IB0) — Serial port driver configuration
- [Micro820 Modbus TCP Server (YouTube)](https://www.youtube.com/watch?v=pQpaucElHeQ) — Enabling TCP server for AI layer
- [Reddit: Modbus RTU VFD Control](https://www.reddit.com/r/PLC/comments/1lytogp/modbus_rtu_control_of_vfd/) — MSG block timing/interlock pattern

---

*Conveyor of Destiny — FactoryLM Cosmos Cookoff*
*Generated 2026-02-21*
