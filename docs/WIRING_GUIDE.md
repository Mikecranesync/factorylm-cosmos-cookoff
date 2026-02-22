# FactoryLM Wiring Guide — Micro 820 + GS10 VFD + Factory I/O

> **One PLC, two worlds:** Physical conveyor with VFD drive **and** Factory I/O
> simulation — both running on the same Allen-Bradley Micro 820.

```
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                     SYSTEM OVERVIEW                                     │
 │                                                                         │
 │   ┌─────────────┐         ┌─────────────────────┐                       │
 │   │ Pushbutton  │  24VDC  │   Micro 820 PLC     │                       │
 │   │ Station     ├────────►│  2080-LC30-48QWB    │                       │
 │   │             │  DI0-3  │                     │                       │
 │   │ ● E-Stop    │         │  Physical I/O ──────┼───► GS10 VFD ──► Motor│
 │   │ ● Green Btn │         │  (DO0, DO1, C2)     │    (FWD/REV)         │
 │   │ ● Selector  │         │                     │                       │
 │   └─────────────┘         │  Modbus TCP ────────┼───► Factory I/O      │
 │                           │  (Coils 0-6)        │    (Simulation)      │
 │                           │  (Regs 100-105)     │                       │
 │                           └─────────┬───────────┘                       │
 │                                     │ Modbus TCP                        │
 │                                     ▼                                   │
 │                           ┌─────────────────────┐                       │
 │                           │  factoryio_bridge.py │                       │
 │                           │  ──► Matrix API     │                       │
 │                           │  ──► Dashboard      │                       │
 │                           │  ──► Diagnosis      │                       │
 │                           └─────────────────────┘                       │
 └──────────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: I/O Budget

### Micro 820 (2080-LC30-48QWB) Total Capacity

| Resource           | Total | VFD Conveyor | Factory I/O | Available |
|--------------------|-------|-------------|-------------|-----------|
| Digital Inputs     | 12    | 4 (DI0-DI3) | 0 (Modbus)  | 8         |
| Digital Outputs    | 8     | 2 (DO0-DO1) | 0 (Modbus)  | 6         |
| Modbus Coils       | 256+  | 4 (7-10)    | 7 (0-6)     | 245+      |
| Holding Registers  | 256+  | 0           | 6 (100-105) | 250+      |

**How they coexist:** The physical VFD conveyor uses hardwired I/O terminals
(DI_00 through DI_03, DO_00, DO_01). Factory I/O communicates over Modbus TCP
on port 502 using coils 0–6 and registers 100–105. The PLC's ladder logic
copies physical I/O states to Modbus coils 7–17 so the software stack can read
everything through a single Modbus connection.

---

## Part 2: Physical VFD Conveyor Wiring

### Step-by-Step Human Wiring Checklist

#### Step 1 — Panel Layout

Mount devices on DIN rail or panel in this order (left to right):
1. 24VDC power supply
2. Micro 820 PLC
3. Terminal strip (common rail)
4. GS10 VFD (separate — needs ventilation)

Pushbutton station mounts on enclosure door or external panel.

#### Step 2 — 24VDC Power Distribution

```
 ┌──────────────┐
 │  24VDC PSU   │
 │              │
 │  +24V ───────┼──► PLC V1 terminal
 │              │          │
 │              │          ▼
 │              │    ┌───────────┐
 │              │    │Common Rail│──► All button commons
 │              │    └───────────┘
 │  0V ─────────┼──► PLC C1 terminal (input common)
 └──────────────┘
```

Wire 9: PLC **V1** ──► Common rail (Red, 24VDC supply to buttons)
Wire 8: Common rail ──► PLC **C1** (Blue, input common return)

#### Step 3 — E-Stop Wiring (Dual-Contact Logic)

The E-stop uses **two contacts** for fault validation:
- **DI_01** (NO contact): Goes HIGH when E-stop is pressed
- **DI_02** (NC contact): Goes HIGH when E-stop is released (normal)

```
 ┌──────────────────┐
 │   E-STOP (HB2)   │
 │                   │
 │  ┌─────────┐     │
 │  │ 1  NC 2 │     │     ┌──────────────────┐
 │  └──┬────┬─┘     │     │   Micro 820 PLC  │
 │     │    │       │     │                  │
 │     │    └───────┼────►│ I/0 (DI_00)      │  Wire 1 (Blue)
 │     │            │     │                  │
 │     └────────────┼────►│ Common rail       │  Wire 2 (Blue)
 │                   │     │                  │
 │  ┌─────────┐     │     │                  │
 │  │ 3  NO 4 │     │     │                  │
 │  └──┬────┬─┘     │     │                  │
 │     │    │       │     │                  │
 │     │    └───────┼────►│ I/1 (DI_01)      │  (NO contact)
 │     │            │     │                  │
 │     └────────────┼────►│ Common rail       │
 │                   │     └──────────────────┘
 └──────────────────┘
```

**E-Stop Truth Table:**

| E-Stop State     | DI_01 (addr 8) | DI_02 (addr 9) | DO_01 (addr 16) |
|------------------|----------------|----------------|-----------------|
| Released (normal)| OFF            | ON             | OFF             |
| Pressed (fault)  | ON             | OFF            | ON              |

**Fault detection:** `fault_alarm = e_stop_active AND NOT e_stop_nc`
This distinguishes a real E-stop press from a wiring fault (both contacts
reading the same state).

#### Step 4 — Green Pushbutton Wiring (Dead-Man Logic)

```
 ┌──────────────────────┐
 │  Green Btn (LA155A)  │
 │                       │
 │  ┌──────────┐        │     ┌──────────────────┐
 │  │ .3  NO .4│        │     │   Micro 820 PLC  │
 │  └──┬─────┬─┘        │     │                  │
 │     │     │          │     │                  │
 │     │     └──────────┼────►│ Common rail       │  Wire 4 (Blue)
 │     │                │     │                  │
 │     └────────────────┼────►│ I/1 (DI_01)      │  Wire 3 (Blue)
 │                       │     └──────────────────┘
 └──────────────────────┘
```

Motor runs ONLY while button is held (dead-man switch). Release = stop.

#### Step 5 — Selector Switch Wiring (FWD / REV)

```
 ┌────────────────────────────┐
 │    Selector Switch         │
 │                             │
 │  ┌────────┐  ┌────────┐   │     ┌──────────────────┐
 │  │ FWD NO │  │ REV NO │   │     │   Micro 820 PLC  │
 │  └──┬───┬─┘  └──┬───┬─┘   │     │                  │
 │     │   │       │   │     │     │                  │
 │     │   └───────┼───┼─────┼────►│ Common rail       │  Wire 7 (Blue)
 │     │           │   │     │     │                  │
 │     └───────────┼───┼─────┼────►│ I/2 (DI_02) FWD  │  Wire 5 (Blue)
 │                 │   │     │     │                  │
 │                 └───┼─────┼────►│ I/3 (DI_03) REV  │  Wire 6 (Blue)
 │                     │     │     └──────────────────┘
 └────────────────────────────┘
```

**3-Position Switch Truth Table:**

| Switch Position | DI_00 (addr 7) | DI_03 (addr 10) | DO_00 (addr 15) |
|-----------------|----------------|-----------------|-----------------|
| LEFT            | OFF            | OFF             | OFF             |
| CENTER          | ON             | OFF             | ON              |
| RIGHT           | ON             | ON              | ON              |

#### Step 6 — PLC Output to VFD

```
 ┌──────────────────┐              ┌──────────────────────────────┐
 │  Micro 820 PLC   │              │  GS10 VFD Control Terminals  │
 │                   │              │                              │
 │  O/0 (DO_00) ────┼── Wire 10 ──┼──► FWD  (Run Forward)        │
 │                   │  (White)     │                              │
 │  O/1 (DO_01) ────┼── Wire 11 ──┼──► REV  (Run Reverse)        │
 │                   │  (White)     │                              │
 │  C2  (OUT COM) ──┼── Wire 12 ──┼──► DCM  (Digital Common)     │
 │                   │  (Black)     │                              │
 └──────────────────┘              └──────────────────────────────┘
```

### Complete Wire List

| Wire # | From                  | To              | Color | Notes                    |
|--------|-----------------------|-----------------|-------|--------------------------|
| 1      | E-Stop term **1**     | PLC **I/0**     | Blue  | NC contact signal        |
| 2      | E-Stop term **2**     | Common rail     | Blue  | NC common                |
| 3      | Green Btn term **.3** | PLC **I/1**     | Blue  | NO contact signal        |
| 4      | Green Btn term **.4** | Common rail     | Blue  | NO common                |
| 5      | Selector FWD output   | PLC **I/2**     | Blue  | FWD position signal      |
| 6      | Selector REV output   | PLC **I/3**     | Blue  | REV position signal      |
| 7      | Selector common       | Common rail     | Blue  | Selector common          |
| 8      | Common rail           | PLC **C1**      | Blue  | Input common             |
| 9      | PLC **V1**            | Common rail     | Red   | 24VDC to buttons         |
| 10     | PLC **O/0**           | VFD **FWD**     | White | Forward command          |
| 11     | PLC **O/1**           | VFD **REV**     | White | Reverse command          |
| 12     | PLC **C2**            | VFD **DCM**     | Black | Digital common           |

### GS10 VFD Parameter Table

#### Parameter Access
1. Press **MENU** on VFD keypad
2. Use **▲/▼** to scroll to parameter group
3. Press **ENTER** to edit value
4. Use **▲/▼** to change value
5. Press **ENTER** to save

#### Required Parameters

| Param    | Name            | Set To          | Description                        |
|----------|-----------------|-----------------|------------------------------------|
| **P01.00** | Motor HP      | **0.5** or **1.0** | Match motor nameplate           |
| **P01.01** | Motor Voltage | **230**         | For 230V motor                     |
| **P01.02** | Motor Amps    | *(nameplate)*   | Check motor nameplate FLA          |
| P03      | Base Frequency  | **60**          | 60 Hz (US standard)               |
| P04      | Max Frequency   | **60**          | Limit to 60 Hz                     |
| P05      | Accel Time      | **3**           | 3 seconds ramp up                  |
| P06      | Decel Time      | **3**           | 3 seconds ramp down                |
| **P00.21** | Source Select | **1**           | External terminal control          |
| **P02.00** | Run Mode     | **1**           | Two-wire: FWD/STOP, REV/STOP       |
| **P00.20** | Freq Command | **0**           | Keypad (fixed speed)               |
| **P09**  | Keypad Freq     | **10**          | 10 Hz ≈ 300 RPM                   |

#### Speed Calculation
- Motor nameplate: 1725 RPM @ 60 Hz
- Target: ~300 RPM
- Formula: (Target RPM / Motor RPM) × 60 Hz
- 300 / 1725 × 60 = **10.4 Hz** → Set P09 = **10**

### VFD Terminal Diagram

```
┌─────────────────────────────────────────────────────┐
│  GS10 VFD CONTROL TERMINALS                         │
│                                                     │
│  ┌───┬───┬───┬───┬───┬───┬───┬───┬───┐             │
│  │DCM│FWD│REV│DF1│DF2│AFM│AVI│ACI│ACM│             │
│  └─┬─┴─┬─┴─┬─┴───┴───┴───┴───┴───┴─┬─┘             │
│    │   │   │                       │               │
│    │   │   │                       │               │
│    ▼   ▼   ▼                       ▼               │
│   COM  FWD REV                    A-COM            │
│   from from from                  (for 0-10V       │
│   PLC  PLC  PLC                   speed ref —      │
│   C2   O/0  O/1                   not used)        │
└─────────────────────────────────────────────────────┘

Terminal Functions:
┌──────────┬────────────────────────┬───────────────────┐
│ Terminal │ Function               │ Connection        │
├──────────┼────────────────────────┼───────────────────┤
│ DCM      │ Digital Common         │ PLC C2            │
│ FWD      │ Run Forward            │ PLC O/0 (DO_00)   │
│ REV      │ Run Reverse            │ PLC O/1 (DO_01)   │
│ DF1      │ Multi-function input 1 │ (not used)        │
│ DF2      │ Multi-function input 2 │ (not used)        │
│ AFM      │ Frequency meter output │ (not used)        │
│ AVI      │ 0-10V speed reference  │ (not used)        │
│ ACI      │ 4-20mA speed reference │ (not used)        │
│ ACM      │ Analog common          │ (not used)        │
└──────────┴────────────────────────┴───────────────────┘
```

---

## Part 3: Factory I/O Scene Wiring (Modbus Coils 0–6)

### Factory I/O Modbus TCP Driver Configuration

1. Open Factory I/O → **File → Drivers → Modbus TCP/IP Server**
2. Click **Configuration** to map I/O points to Modbus addresses
3. Match addresses below to your Factory I/O scene mapping

**Connection:** `127.0.0.1:502` (local) or `192.168.1.100:502` (real PLC)
**Poll interval:** 200 ms (5 Hz)
**Scene:** "From A to B" or "Sorting by Height"

### Coil Map (Addresses 0–6)

| Address | Tag Name         | Direction  | Description             |
|---------|------------------|------------|-------------------------|
| 0       | `conveyor_running` | PLC → FIO | Belt motor command      |
| 1       | `emitter_active`   | PLC → FIO | Item spawner            |
| 2       | `sensor_1_active`  | FIO → PLC | SensorStart (entry photoeye) |
| 3       | `sensor_2_active`  | FIO → PLC | SensorEnd (exit photoeye)    |
| 4       | `run_command`      | Remote     | API/Telegram trigger    |
| 5       | *(reserved)*       | —          | —                       |
| 6       | *(reserved)*       | —          | —                       |

### Register Map (Addresses 100–105)

| Address | Tag Name         | Scale  | Description                              |
|---------|------------------|--------|------------------------------------------|
| 100     | `item_count`     | 1×     | Items counted                            |
| 101     | `motor_speed`    | 1×     | Speed 0–100%                             |
| 102     | `motor_current`  | ÷ 10   | Amps (raw value / 10)                    |
| 103     | `temperature`    | ÷ 10   | Degrees C (raw value / 10)               |
| 104     | `pressure`       | 1×     | PSI                                      |
| 105     | `error_code`     | 1×     | 0=OK, 1=Overload, 2=Overheat, 3=Jam, 4=Sensor, 5=Comms |

### How These Map to Matrix API via `factoryio_bridge.py`

The bridge reads Modbus, applies scale factors, then POSTs to Matrix API:

| Modbus Tag           | Scale | Matrix API Field   |
|----------------------|-------|--------------------|
| `motor_running`      | —     | `motor_running`    |
| `motor_stopped`      | —     | `motor_stopped`    |
| `motor_speed`        | 1×    | `motor_speed`      |
| `motor_current`      | 0.1×  | `motor_current`    |
| `temperature`        | 0.1×  | `temperature`      |
| `pressure`           | 1×    | `pressure`         |
| `conveyor_running`   | —     | `conveyor_running` |
| `conveyor_speed`     | 1×    | `conveyor_speed`   |
| `sensor_1_active`    | —     | `sensor_1`         |
| `sensor_2_active`    | —     | `sensor_2`         |
| `fault_alarm`        | —     | `fault_alarm`      |
| `e_stop_active`      | —     | `e_stop`           |
| `error_code`         | 1×    | `error_code`       |

---

## Part 4: Full Modbus Address Map (Combined)

### Master Coil Table (Addresses 0–17)

```
┌─────────┬──────────────────┬───────────┬──────────────────────────────────┐
│ Address │ CCW Variable     │ Direction │ Description                      │
├─────────┼──────────────────┼───────────┼──────────────────────────────────┤
│       0 │ Conveyor         │ PLC→FIO   │ Belt motor command               │
│       1 │ Emitter          │ PLC→FIO   │ Item spawner                     │
│       2 │ SensorStart      │ FIO→PLC   │ Entry photoeye                   │
│       3 │ SensorEnd        │ FIO→PLC   │ Exit photoeye                    │
│       4 │ RunCommand       │ Remote    │ API/Telegram trigger             │
│       5 │ (reserved)       │ —         │                                  │
│       6 │ (reserved)       │ —         │                                  │
├─────────┼──────────────────┼───────────┼──────────────────────────────────┤
│       7 │ _IO_EM_DI_00     │ Physical  │ 3-position switch CENTER         │
│       8 │ _IO_EM_DI_01     │ Physical  │ E-stop NO contact                │
│       9 │ _IO_EM_DI_02     │ Physical  │ E-stop NC contact                │
│      10 │ _IO_EM_DI_03     │ Physical  │ 3-position switch RIGHT          │
│      11 │ _IO_EM_DI_04     │ Physical  │ Left pushbutton                  │
│      12 │ _IO_EM_DI_05     │ Physical  │ (available)                      │
│      13 │ _IO_EM_DI_06     │ Physical  │ (available)                      │
│      14 │ _IO_EM_DI_07     │ Physical  │ (available)                      │
├─────────┼──────────────────┼───────────┼──────────────────────────────────┤
│      15 │ _IO_EM_DO_00     │ Physical  │ Indicator LED                    │
│      16 │ _IO_EM_DO_01     │ Physical  │ E-stop LED                       │
│      17 │ _IO_EM_DO_03     │ Physical  │ (available)                      │
└─────────┴──────────────────┴───────────┴──────────────────────────────────┘
```

### Master Register Table (Addresses 100–105)

```
┌─────────┬──────────────────┬────────┬──────────────────────────────────┐
│ Address │ Tag              │ Scale  │ Description                      │
├─────────┼──────────────────┼────────┼──────────────────────────────────┤
│     100 │ item_count       │ 1×     │ Items counted by sensors         │
│     101 │ motor_speed      │ 1×     │ Speed 0–100%                     │
│     102 │ motor_current    │ ÷ 10   │ Amps (raw / 10)                  │
│     103 │ temperature      │ ÷ 10   │ Degrees C (raw / 10)             │
│     104 │ pressure         │ 1×     │ PSI                              │
│     105 │ error_code       │ 1×     │ 0=OK, 1=Overload, 2=Overheat,   │
│         │                  │        │ 3=Jam, 4=Sensor, 5=Comms         │
└─────────┴──────────────────┴────────┴──────────────────────────────────┘
```

---

## Part 5: Ladder Logic

### VFD Control Rungs (Physical Conveyor)

```
RUNG 0: E-Stop Check
──────┤ DI_00 ├──────────────────────────────────────────( System_Ready )
       (NC: TRUE when E-stop released)

RUNG 1: Dead-Man Permission
──────┤ System_Ready ├────┤ DI_01 ├──────────────────────( Run_Permitted )
                          (Green button held)

RUNG 2: Forward Output (with reverse interlock)
──────┤ Run_Permitted ├────┤ DI_02 ├────┤/ DO_01 ├──────( DO_00 )
                           (FWD pos)    (REV not on)     (VFD FWD)

RUNG 3: Reverse Output (with forward interlock)
──────┤ Run_Permitted ├────┤ DI_03 ├────┤/ DO_00 ├──────( DO_01 )
                           (REV pos)    (FWD not on)     (VFD REV)
```

### Factory I/O Scene Control Rungs

```
RUNG 4: Conveyor Coil (driven by RunCommand or physical button)
──────┤ RunCommand ├─────────────────────────────────────( Conveyor )
                                                         (Coil 0)

RUNG 5: Emitter Coil (items spawn when conveyor runs)
──────┤ Conveyor ├───────────────────────────────────────( Emitter )
                                                         (Coil 1)
```

### E-Stop Dual-Contact Validation

```
RUNG 6: Fault Detection
──────┤ DI_01 ├────┤/ DI_02 ├────────────────────────────( fault_alarm )
      (NO: ON      (NC: OFF                              (ALARM)
       when         when
       pressed)     pressed)

      If DI_01=ON AND DI_02=OFF → genuine E-stop press
      If DI_01=ON AND DI_02=ON  → wiring fault (both stuck)
```

### CCW Tag Definitions

| Tag Name        | Type     | Address        | Description                    |
|-----------------|----------|----------------|--------------------------------|
| System_Ready    | BOOL     | Internal       | E-stop OK latch                |
| Run_Permitted   | BOOL     | Internal       | Safety + button confirmed      |
| DI_00           | BOOL     | _IO_EM_DI_00   | E-stop NC contact              |
| DI_01           | BOOL     | _IO_EM_DI_01   | Green button / E-stop NO       |
| DI_02           | BOOL     | _IO_EM_DI_02   | Selector FWD / E-stop NC       |
| DI_03           | BOOL     | _IO_EM_DI_03   | Selector REV                   |
| DO_00           | BOOL     | _IO_EM_DO_00   | VFD Forward                    |
| DO_01           | BOOL     | _IO_EM_DO_01   | VFD Reverse                    |
| Conveyor        | BOOL     | Coil 0         | Factory I/O belt motor         |
| Emitter         | BOOL     | Coil 1         | Factory I/O item spawner       |
| SensorStart     | BOOL     | Coil 2         | Factory I/O entry photoeye     |
| SensorEnd       | BOOL     | Coil 3         | Factory I/O exit photoeye      |
| RunCommand      | BOOL     | Coil 4         | Remote run trigger             |
| fault_alarm     | BOOL     | Internal       | DI_01 AND NOT DI_02            |

### Operation Table

| E-Stop  | Green Btn | Selector | Motor           |
|---------|-----------|----------|-----------------|
| PRESSED | Any       | Any      | **STOP**        |
| UP      | Released  | Any      | **STOP**        |
| UP      | HELD      | FWD      | **FORWARD @ 300 RPM** |
| UP      | HELD      | REV      | **REVERSE @ 300 RPM** |
| UP      | HELD      | Neutral  | **STOP**        |

---

## Part 6: Software Chain (Factory I/O → Matrix → Cosmos R2)

### Data Flow

```
┌──────────────┐     Modbus TCP      ┌──────────────────┐
│  Factory I/O │ ◄──────────────────► │   Micro 820 PLC  │
│  (Scene)     │     port 502        │                  │
└──────────────┘                     └────────┬─────────┘
                                              │ Modbus TCP
                                              ▼
                                    ┌──────────────────┐
                                    │factoryio_bridge.py│
                                    │                  │
                                    │ 1. Read 18 coils │
                                    │ 2. Read 6 regs   │
                                    │ 3. Apply scaling  │
                                    │ 4. POST to Matrix │
                                    └────────┬─────────┘
                                              │ HTTP POST
                                              ▼
                                    ┌──────────────────┐
                                    │   Matrix API     │
                                    │  localhost:8000  │
                                    │                  │
                                    │ Stores tag values │
                                    │ Serves dashboard  │
                                    └────────┬─────────┘
                                              │
                                    ┌─────────┴────────┐
                                    ▼                  ▼
                          ┌──────────────┐   ┌──────────────┐
                          │  Dashboard   │   │  Diagnosis   │
                          │  (HMI)       │   │  Engine      │
                          │  :8000/dash  │   │              │
                          └──────────────┘   └──────────────┘
```

### How `factoryio_bridge.py` Works

1. **Reads** Modbus coils 0–6 and registers 100–105 per `config/factoryio.yaml`
2. **Applies** scale factors: `motor_current × 0.1`, `temperature × 0.1`
3. **Maps** tag names (e.g., `sensor_1_active` → `sensor_1` in Matrix)
4. **POSTs** JSON to Matrix API at `http://localhost:8000`

### How `diagnosis_engine.py` Reads the Full Map

The `read_live_plc()` function reads all 18 coils (0–17) plus 6 registers
(100–105) directly via Modbus TCP, bypassing the bridge entirely. This gives
the diagnosis engine access to physical I/O states (coils 7–17) that the
bridge doesn't normally read.

### Tag Name Mapping Table

| Modbus Addr | Bridge Tag (YAML)  | diagnosis_engine Tag | Matrix API Field |
|-------------|--------------------|-----------------------|------------------|
| Coil 0      | `motor_running`    | `conveyor_running`    | `motor_running`  |
| Coil 1      | `motor_stopped`    | `emitter_active`      | `motor_stopped`  |
| Coil 2      | `fault_alarm`      | `sensor_1_active`     | `sensor_1`       |
| Coil 3      | `conveyor_running` | `sensor_2_active`     | `sensor_2`       |
| Coil 4      | `sensor_1_active`  | `run_command`         | `sensor_1`       |
| Coil 5      | `sensor_2_active`  | *(not read)*          | `sensor_2`       |
| Coil 6      | `e_stop_active`    | *(not read)*          | `e_stop`         |
| Coil 7      | *(not in YAML)*    | `switch_center`       | —                |
| Coil 8      | *(not in YAML)*    | `e_stop_active`       | —                |
| Coil 9      | *(not in YAML)*    | `e_stop_nc`           | —                |
| Coil 10     | *(not in YAML)*    | `switch_right`        | —                |
| Coil 11     | *(not in YAML)*    | `pushbutton`          | —                |
| Reg 100     | `motor_speed`      | `item_count`          | `motor_speed`    |
| Reg 101     | `motor_current`    | `motor_speed`         | `motor_current`  |
| Reg 102     | `temperature`      | `motor_current`       | `temperature`    |
| Reg 103     | `pressure`         | `temperature`         | `pressure`       |
| Reg 104     | `conveyor_speed`   | `pressure`            | `conveyor_speed` |
| Reg 105     | `error_code`       | `error_code`          | `error_code`     |

### Known Discrepancies to Fix

1. **Register order mismatch:** `factoryio.yaml` and `factoryio_bridge.py` map
   register 100 → `motor_speed`, but `diagnosis_engine.py` maps register 100 →
   `item_count`. The bridge and YAML are aligned; the diagnosis engine has a
   different mapping. **Resolution:** Align `diagnosis_engine.py` register
   mapping to match `factoryio.yaml`, or document that the diagnosis engine
   intentionally includes `item_count` as an additional field.

2. **Coil semantic mismatch:** `factoryio.yaml` maps coil 0 → `motor_running`
   and coil 3 → `conveyor_running`, while `diagnosis_engine.py` maps coil 0 →
   `conveyor_running` with no coil 3 equivalent. The WHITEPAPER coil table
   (coil 0 = "Conveyor" = belt motor command) aligns with the diagnosis engine.
   **Resolution:** The YAML coil map should be updated to match the WHITEPAPER
   and diagnosis engine (coil 0 = `conveyor_running`).

3. **Sensor tag name:** `factoryio_bridge.py` maps `sensor_1_active` →
   Matrix field `sensor_1`, dropping the `_active` suffix. The fault engine
   in `diagnosis_engine.py` uses `sensor_1_active`. Code that reads from
   Matrix needs to use `sensor_1`; code reading directly from Modbus uses
   `sensor_1_active`.

---

## Part 7: Test & Verification Checklist

### 1. VFD Manual Test (Before PLC Integration)

- [ ] Verify VFD powers up and displays frequency on keypad
- [ ] Set P00.21 = 0 (keypad control) temporarily
- [ ] Press RUN on VFD keypad — motor should spin
- [ ] Press STOP — motor should stop
- [ ] Verify direction matches expected rotation
- [ ] Set P00.21 = 1 (terminal control) when done

### 2. PLC I/O Test (Force Each Input in CCW)

- [ ] Open Connected Components Workbench, connect to Micro 820
- [ ] Go to **Monitor** → **I/O** tab
- [ ] Press E-stop → verify DI_00 goes FALSE (NC contact opens)
- [ ] Release E-stop → verify DI_00 goes TRUE
- [ ] Press E-stop → verify DI_01 goes TRUE (NO contact closes)
- [ ] Hold green button → verify DI_01 goes TRUE
- [ ] Release green button → verify DI_01 goes FALSE
- [ ] Turn selector to FWD → verify DI_02 goes TRUE
- [ ] Turn selector to REV → verify DI_03 goes TRUE
- [ ] Force DO_00 ON → verify 24V at VFD FWD terminal
- [ ] Force DO_01 ON → verify 24V at VFD REV terminal

### 3. VFD Under PLC Control (Full Sequence)

- [ ] Download ladder program to Micro 820
- [ ] Release E-stop (System_Ready = TRUE)
- [ ] Hold green button + selector FWD → motor runs forward
- [ ] Release green button → motor stops (dead-man)
- [ ] Hold green button + selector REV → motor runs reverse
- [ ] Press E-stop → motor stops immediately
- [ ] Verify interlock: cannot run FWD and REV simultaneously

### 4. Factory I/O Modbus Connection

- [ ] Start Factory I/O with "From A to B" scene
- [ ] Configure Modbus TCP/IP Server driver
- [ ] In CCW, verify coils 0–6 reflect scene state
- [ ] Toggle Conveyor coil (0) → belt should move in scene
- [ ] Place item at SensorStart → coil 2 should go TRUE
- [ ] Move item past SensorEnd → coil 3 should go TRUE

### 5. Bridge → Matrix → Dashboard

- [ ] Start `factoryio_bridge.py` with `--config config/factoryio.yaml`
- [ ] Start Matrix API server on port 8000
- [ ] Open dashboard at `http://localhost:8000`
- [ ] Verify tags appear: motor_running, temperature, pressure, etc.
- [ ] Toggle conveyor in Factory I/O → verify `motor_running` updates in dashboard
- [ ] Check scale factors: motor_current shows Amps (not raw), temperature shows °C

### 6. Full Cosmos R2 Diagnosis

- [ ] Start diagnosis engine
- [ ] Trigger a fault condition (e.g., press E-stop, block sensor)
- [ ] Verify `fault_alarm` goes TRUE in diagnosis engine output
- [ ] Verify diagnosis insight is created with correct fault description
- [ ] Send Telegram message asking "what's wrong with the factory?"
- [ ] Verify response includes E-stop / fault information

---

*FactoryLM Cosmos Cookoff | Micro 820 + GS10 VFD + Factory I/O*
*Cross-referenced against: diagnosis_engine.py, factoryio_bridge.py, factoryio.yaml, WHITEPAPER.md, USER_MANUAL.md*
*Generated 2026-02-21*
