# Field Test Checklist — Conveyor of Destiny

> Zero-shot test procedure. No clarifying questions needed.
> Run top-to-bottom. Every check has a pass/fail criterion.
> Cross-referenced with `/cluster/betterclaw/memory/physical-layer.md`

**Date:** _______________
**Technician:** _______________
**PLC Model on bench:** _______________

---

## 1. Pre-Flight

Power on all hardware. Verify network connectivity before touching Modbus.

| # | Check | Command / Action | Pass Criterion | Result |
|---|-------|-----------------|----------------|--------|
| 1.1 | 24VDC PSU on | Measure at terminal strip | 23.5-24.5 VDC | [ ] |
| 1.2 | PLC powered | RUN LED solid green on Micro 820 | LED green | [ ] |
| 1.3 | VFD powered | Keypad displays frequency | Display lit | [ ] |
| 1.4 | E-stop released | Twist to release, verify DI_02 (NC) = HIGH | LED off | [ ] |
| 1.5 | Network switch on | TP-Link TL-SG605 LEDs for ports 1-3 | Link lights on | [ ] |
| 1.6 | Ping PLC | `ping 192.168.1.100` | Reply < 5ms | [ ] |
| 1.7 | Ping Pi/Charlie | `ping 192.168.1.12` | Reply < 5ms | [ ] |
| 1.8 | Ping Tailscale VPS | `ping 100.68.120.99` | Reply < 100ms | [ ] |

---

## 2. VFD Manual Test (Before PLC Integration)

Test the VFD in standalone mode first. If the motor doesn't spin here, nothing else matters.

| # | Check | Action | Pass Criterion | Result |
|---|-------|--------|----------------|--------|
| 2.1 | Set keypad control | Set P00.21 = **0** (keypad control) | Parameter saved | [ ] |
| 2.2 | Set frequency | Set P09 = **10** (10 Hz ~ 300 RPM) | Display shows 10.0 | [ ] |
| 2.3 | Forward run | Press **RUN** on VFD keypad | Motor spins, correct direction | [ ] |
| 2.4 | Stop | Press **STOP** on VFD keypad | Motor decels to stop in ~3s | [ ] |
| 2.5 | Verify accel/decel | P05=3, P06=3 | Ramp matches ~3 seconds | [ ] |
| 2.6 | Restore terminal control | Set P00.21 = **1** (terminal control) | Parameter saved | [ ] |

---

## 3. PLC I/O Verification

Open CCW, connect to Micro 820, go to Monitor > I/O tab. Force each I/O point and verify with multimeter.

| # | Check | Action | Expected | Result |
|---|-------|--------|----------|--------|
| 3.1 | E-stop NC (DI_00, addr 7) | Release E-stop | HIGH (TRUE) | [ ] |
| 3.2 | E-stop NC (DI_00, addr 7) | Press E-stop | LOW (FALSE) | [ ] |
| 3.3 | E-stop NO (DI_01, addr 8) | Press E-stop | HIGH (TRUE) | [ ] |
| 3.4 | E-stop NO (DI_01, addr 8) | Release E-stop | LOW (FALSE) | [ ] |
| 3.5 | Green btn (DI_04, addr 11) | Hold button | HIGH | [ ] |
| 3.6 | Green btn (DI_04, addr 11) | Release button | LOW | [ ] |
| 3.7 | Selector CENTER (DI_00, addr 7) | Turn to center | HIGH | [ ] |
| 3.8 | Selector RIGHT (DI_03, addr 10) | Turn to right | HIGH | [ ] |
| 3.9 | Force DO_00 (addr 15) ON | Force in CCW | 24V at VFD FWD terminal | [ ] |
| 3.10 | Force DO_01 (addr 16) ON | Force in CCW | 24V at VFD REV terminal | [ ] |
| 3.11 | Remove forces | Remove all forces in CCW | All outputs OFF | [ ] |

---

## 4. Modbus TCP from Laptop/Pi

Read coils and registers directly from PLC to verify Modbus TCP works.

### Read all 18 coils

```bash
python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('192.168.1.100', port=502, timeout=3)
c.connect()
r = c.read_coils(0, 18)
bits = [int(b) for b in r.bits[:18]]
labels = ['Conveyor','Emitter','SensorStart','SensorEnd','RunCommand',
          'res5','res6','SwCenter','EstopNO','EstopNC','SwRight',
          'GreenBtn','DI05','DI06','DI07','DO00_FWD','DO01_REV','DO03']
for i, (b, l) in enumerate(zip(bits, labels)):
    print(f'  Coil {i:2d}: {b}  ({l})')
c.close()
"
```

| # | Check | Pass Criterion | Result |
|---|-------|----------------|--------|
| 4.1 | Coils read without error | No exception, 18 values returned | [ ] |
| 4.2 | E-stop released state | Coil 8=0, Coil 9=1 | [ ] |
| 4.3 | Conveyor off | Coil 0=0 | [ ] |

### Read 6 holding registers

```bash
python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('192.168.1.100', port=502, timeout=3)
c.connect()
r = c.read_holding_registers(100, 6)
labels = ['item_count(1x)','motor_speed(1x)','motor_current(/10)','temperature(/10)','pressure(1x)','error_code(1x)']
for i, (v, l) in enumerate(zip(r.registers, labels)):
    print(f'  Reg {100+i}: {v}  ({l})')
c.close()
"
```

| # | Check | Pass Criterion | Result |
|---|-------|----------------|--------|
| 4.4 | Registers read without error | No exception, 6 values returned | [ ] |
| 4.5 | Error code = 0 | Reg 105 = 0 (no fault) | [ ] |

---

## 5. VFD Register Probe

Use probe_vfd.py to read VFD registers and verify which addresses contain what data.

```bash
python3 tools/probe_vfd.py --host 192.168.1.101 --slave 1
```

If probe_vfd.py is not available, use this one-liner:

```bash
python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('192.168.1.101', port=502, timeout=3)
c.connect()
# Read status block 0x2100-0x210F (16 registers)
r = c.read_holding_registers(0x2100, 16, slave=1)
if not r.isError():
    addrs = [
        (0x2100,'Status Word',1), (0x2101,'Output Hz',100),
        (0x2102,'Output Amps',10), (0x2103,'Actual Freq',100),
        (0x2104,'Actual Current',100), (0x2105,'DC Bus V',10),
        (0x2106,'???RPM_or_Volt',1), (0x2107,'Torque%',10),
        (0x2108,'???Temp_or_???',10), (0x2109,'Fault Code',1),
        (0x210A,'Warning Code',1), (0x210B,'Run Hours',1),
        (0x210C,'unknown_0C',1), (0x210D,'???Motor_RPM',1),
        (0x210E,'unknown_0E',1), (0x210F,'???Drive_Temp',10),
    ]
    for i, (addr, name, scale) in enumerate(addrs):
        raw = r.registers[i]
        scaled = raw / scale if scale > 1 else raw
        print(f'  0x{addr:04X} ({addr:5d}): raw={raw:6d}  scaled={scaled:8.2f}  ({name})')
else:
    print('Read error:', r)
c.close()
"
```

**Run this with the motor spinning at a known speed (e.g., 10 Hz / ~300 RPM) and compare values to the VFD keypad display.**

| # | Check | Read value | Keypad shows | Match? | Result |
|---|-------|-----------|-------------|--------|--------|
| 5.1 | 0x2103 = Actual Freq | _____ / 100 = _____ Hz | _____ Hz | [ ] | [ ] |
| 5.2 | 0x2106 = ??? | raw=_____ | Compare to RPM and Voltage display | — | [ ] |
| 5.3 | 0x210D = Motor RPM? | raw=_____ | _____ RPM on keypad | [ ] | [ ] |
| 5.4 | 0x2104 = Current (scale?) | raw=_____ / 100 = _____ A | _____ A (clamp meter) | [ ] | [ ] |
| 5.5 | 0x2104 = Current (scale?) | raw=_____ / 10 = _____ A | _____ A (clamp meter) | [ ] | [ ] |
| 5.6 | 0x2108 = ??? | raw=_____ / 10 = _____ | Compare to temp display | — | [ ] |
| 5.7 | 0x210F = Drive Temp? | raw=_____ / 10 = _____ C | _____ C on keypad | [ ] | [ ] |

**After completing this section, update `physical-layer.md` Section 1C with verified values and update `vfd_reader.py` if needed.**

---

## 6. Pi-Factory Full Stack

Start server.py with all peripherals connected and verify the API reports all subsystems.

```bash
PLC_HOST=192.168.1.100 \
VFD_HOST=192.168.1.101 \
VIDEO_SOURCE=0 \
PI_COMPACTCOM_PORT=5020 \
python server.py --port 8081
```

| # | Check | Command | Pass Criterion | Result |
|---|-------|---------|----------------|--------|
| 6.1 | Server starts | Check stdout | "Listening on 0.0.0.0:8081" | [ ] |
| 6.2 | PLC connected | `curl localhost:8081/api/status` | `plc_connected: true` | [ ] |
| 6.3 | VFD connected | `curl localhost:8081/api/status` | `vfd_connected: true` | [ ] |
| 6.4 | Camera connected | `curl localhost:8081/api/status` | `camera_connected: true` | [ ] |
| 6.5 | CompactCom listening | `telnet localhost 5020` | Connection accepted | [ ] |
| 6.6 | Tags updating | `curl localhost:8081/api/tags` | motor_speed, temperature populated | [ ] |
| 6.7 | VFD data flowing | `curl localhost:8081/api/vfd` | vfd_actual_freq > 0 (if running) | [ ] |

---

## 7. CompactCom MSG Test (PLC reads 21 registers from Pi)

The PLC reads the Pi's CompactCom server (port 5020) using a MSG instruction. Verify all 21 registers transfer correctly.

### From the Pi/laptop, verify CompactCom is publishing:

```bash
python3 -c "
from pymodbus.client import ModbusTcpClient
c = ModbusTcpClient('192.168.1.12', port=5020, timeout=3)
c.connect()
r = c.read_holding_registers(0, 21)
labels = ['belt_rpm(/10)','belt_speed_pct(/10)','belt_status','belt_offset(+32768)',
          'vfd_hz(/100)','vfd_amps(/10)','vfd_fault','motor_running','motor_speed',
          'motor_current(/10)','conveyor_running','temperature(/10)','pressure',
          'sensor_1','sensor_2','e_stop','fault_alarm','error_code',
          'ai_confidence','pi_heartbeat','source_flags']
for i, (v, l) in enumerate(zip(r.registers, labels)):
    print(f'  Reg {i:2d}: {v:6d}  ({l})')
c.close()
"
```

| # | Check | Pass Criterion | Result |
|---|-------|----------------|--------|
| 7.1 | Read 21 registers | No error, 21 values returned | [ ] |
| 7.2 | Heartbeat (reg 19) | Increments on each read (0.2s interval) | [ ] |
| 7.3 | Source flags (reg 20) | Bit 0 set if PLC connected, bit 1 if VFD, bit 2 if camera | [ ] |
| 7.4 | PLC side | In CCW, check Pi_Data[0..20] populating | [ ] |
| 7.5 | Watchdog | Pi_Data[19] changes every scan | [ ] |

---

## 8. VFD Register Verification Matrix

Summary table for recording verified register contents. Fill in during Section 5.

| Register | Hex | Code currently maps as | Gist says | Verified value | Correct mapping |
|----------|-----|----------------------|-----------|---------------|----------------|
| 8452 | 0x2104 | vfd_actual_current /10 | /100 | _____________ | _____________ |
| 8454 | 0x2106 | vfd_motor_rpm 1x | output_voltage /10 | _____________ | _____________ |
| 8456 | 0x2108 | vfd_drive_temp_c /10 | (not listed here) | _____________ | _____________ |
| 8461 | 0x210D | (not read) | motor_rpm 1x | _____________ | _____________ |
| 8463 | 0x210F | (not read) | drive_temp /10 | _____________ | _____________ |

**Action after verification:** Update `net/drivers/vfd_reader.py` _STATUS_REGS table with correct mappings. Commit with this checklist as evidence.

---

## 9. Safety Interlock Test

Test every safety path. Motor must not run if any safety condition is violated.

| # | Test | Action | Expected Result | Result |
|---|------|--------|----------------|--------|
| 9.1 | E-stop stops motor | Motor running, press E-stop | Motor stops immediately | [ ] |
| 9.2 | E-stop prevents start | E-stop pressed, try to run | Motor does NOT start | [ ] |
| 9.3 | Fault alarm asserts | Press E-stop | Coil 8=1, Coil 9=0, fault_alarm=TRUE | [ ] |
| 9.4 | Fault alarm clears | Release E-stop | Coil 8=0, Coil 9=1, fault_alarm=FALSE | [ ] |
| 9.5 | Dead-man (green btn) | Release green button while running | Motor stops | [ ] |
| 9.6 | Dead-man prevents start | Green button NOT held, try to run | Motor does NOT start | [ ] |
| 9.7 | FWD/REV interlock | Selector in FWD, force DO_01 | DO_01 does NOT energize | [ ] |
| 9.8 | Wiring fault detection | Simulate both DI_01=1 AND DI_02=1 | System recognizes wiring fault, not E-stop | [ ] |
| 9.9 | Software E-stop | Send API stop command | Motor stops, conveyor coil = 0 | [ ] |

---

## 10. Sign-Off

All sections must pass before the system is declared field-ready.

| Section | Status | Notes |
|---------|--------|-------|
| 1. Pre-Flight | [ ] PASS / [ ] FAIL | |
| 2. VFD Manual | [ ] PASS / [ ] FAIL | |
| 3. PLC I/O | [ ] PASS / [ ] FAIL | |
| 4. Modbus TCP | [ ] PASS / [ ] FAIL | |
| 5. VFD Probe | [ ] PASS / [ ] FAIL | |
| 6. Full Stack | [ ] PASS / [ ] FAIL | |
| 7. CompactCom | [ ] PASS / [ ] FAIL | |
| 8. VFD Verification | [ ] PASS / [ ] FAIL | |
| 9. Safety Interlocks | [ ] PASS / [ ] FAIL | |

**VFD Register Resolution:**
- 0x2106 is: _____________ (record here)
- 0x210D is: _____________ (record here)
- 0x210F is: _____________ (record here)
- 0x2104 scaling: _____________ (record here)
- Code changes needed: [ ] YES / [ ] NO
- If YES, commit hash of fix: _____________

**Signed off by:** _______________
**Date:** _______________

---

*FactoryLM Conveyor of Destiny — Field Test Checklist v1.0*
*Cross-referenced with: physical-layer.md, CLAUDE.md, WIRING_GUIDE.md, publisher.py, pi_compactcom.py*
