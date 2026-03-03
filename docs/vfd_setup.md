# ATO GS10 VFD — Modbus TCP Setup Guide

## What This Does

Connects the ATO GS10 VFD to Pi-Factory over Modbus TCP so the system
can read real-time frequency, current, temperature, and fault codes.
This data feeds into the AI diagnosis engine and gets published to the
PLC via the CompactCom bridge.

## Hardware Setup

### Wiring

The ATO GS10 has an RJ45 Ethernet port on the front panel for Modbus TCP.
Connect it to the same network switch as the Pi and PLC.

```
Network Switch
  |--- Pi (192.168.1.12)
  |--- PLC (192.168.1.100)
  |--- VFD (192.168.1.101)  <-- ATO GS10 Ethernet port
```

Use a standard Cat5e/Cat6 Ethernet cable (straight-through, not crossover).

## VFD Parameter Configuration

Access parameters using the VFD keypad:
1. Press MENU to enter parameter mode
2. Use UP/DOWN to navigate to the parameter group
3. Press ENTER to edit a parameter
4. Use UP/DOWN to change the value
5. Press ENTER to save

### Required Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| P14.00 | 1 | Communication enable (0=off, 1=on) |
| P14.01 | 2 | Protocol: Modbus TCP (0=none, 1=RTU, 2=TCP) |
| P14.02 | 1 | Station address / Modbus slave ID |
| P14.03 | 5 | Baud rate (irrelevant for TCP, keep default) |
| P14.04 | 0 | Data format: 8N1 (irrelevant for TCP) |
| P14.05 | 1000 | Communication timeout in ms (1000 = 1s) |

### IP Address Configuration

The ATO GS10 may use DHCP by default. To set a static IP:

| Parameter | Value | Description |
|-----------|-------|-------------|
| P14.10 | 0 | IP mode: 0=static, 1=DHCP |
| P14.11 | 192 | IP byte 1 |
| P14.12 | 168 | IP byte 2 |
| P14.13 | 1 | IP byte 3 |
| P14.14 | 101 | IP byte 4 |
| P14.15 | 255 | Subnet mask byte 1 |
| P14.16 | 255 | Subnet mask byte 2 |
| P14.17 | 255 | Subnet mask byte 3 |
| P14.18 | 0 | Subnet mask byte 4 |

After changing IP parameters, power-cycle the VFD for changes to take effect.

## Pi-Factory Configuration

Set these environment variables before starting Pi-Factory:

```bash
export VFD_HOST=192.168.1.101   # VFD IP address
export VFD_PORT=502              # Modbus TCP port (default)
export VFD_SLAVE=1               # Modbus slave ID (matches P14.02)
```

Or in the startup command:

```bash
VFD_HOST=192.168.1.101 VFD_SLAVE=1 python3 server.py --port 8081
```

## Register Map

Pi-Factory reads these VFD registers:

### Writable Registers (Control)

| Address | Name | Scale | Description |
|---------|------|-------|-------------|
| 0x2000 | control_word | 1x | 0x0001=FWD, 0x0003=REV, 0x0007=Stop |
| 0x2001 | setpoint_hz | /100 | Frequency target (3000 = 30.00 Hz) |

### Read-Only Status Registers

| Address | Name | Scale | Description |
|---------|------|-------|-------------|
| 0x2100 | status_word | 1x | Drive status bits |
| 0x2101 | output_hz | /100 | Output frequency |
| 0x2102 | output_amps | /10 | Output current |
| 0x2103 | actual_freq | /100 | Actual measured frequency |
| 0x2104 | actual_current | /10 | Actual measured current |
| 0x2105 | dc_bus_volts | /10 | DC bus voltage |
| 0x2106 | motor_rpm | 1x | Motor RPM |
| 0x2107 | torque_pct | /10 | Torque percentage |
| 0x2108 | drive_temp_c | /10 | Drive temperature |
| 0x2109 | fault_code | 1x | Active fault (see table below) |
| 0x210A | warning_code | 1x | Active warning |
| 0x210B | run_hours | 1x | Total run hours |

### Fault Codes

| Code | Description |
|------|-------------|
| 0 | No fault |
| 1 | Overcurrent during acceleration |
| 2 | Overcurrent during deceleration |
| 3 | Overcurrent at constant speed |
| 4 | Overvoltage during acceleration |
| 5 | Overvoltage during deceleration |
| 6 | Overvoltage at constant speed |
| 7 | DC bus undervoltage |
| 8 | Drive overtemperature |
| 9 | Motor overload |
| 10 | Input phase loss |
| 11 | Output phase loss |
| 12 | External fault |
| 13 | Communication loss |

## Verification

### Step 1: Ping the VFD

```bash
ping 192.168.1.101
```

If this fails, check:
- Ethernet cable connected to VFD's RJ45 port
- P14.10 = 0 (static IP mode)
- IP address matches P14.11-P14.14
- VFD and Pi are on the same subnet

### Step 2: Run the VFD Probe Tool

```bash
python3 tools/probe_vfd.py --host 192.168.1.101
```

This will try all slave IDs and read all register banks.

### Step 3: Check the API

```bash
curl -s http://localhost:8081/api/vfd/status | python3 -m json.tool
```

Expected output when connected:
```json
{
    "vfd_connected": true,
    "vfd_control_word": 1,
    "vfd_setpoint_hz": 30.0,
    "vfd_output_hz": 29.95,
    "vfd_output_amps": 4.2,
    "vfd_motor_rpm": 1748,
    "vfd_drive_temp_c": 38.5,
    "vfd_fault_code": 0,
    "vfd_fault_description": "No fault"
}
```

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Ping fails | Wrong IP or cable | Check P14.11-P14.14, try different cable |
| "Connection refused" | Modbus TCP not enabled | Set P14.00=1, P14.01=2, power cycle |
| Connected but no data | Wrong slave ID | Run probe tool, try slave IDs 1-10 |
| Connects then drops | Timeout too short | Increase P14.05 to 5000 (5s) |
| "vfd_connected: false" | VFD_HOST not set | Set `VFD_HOST=192.168.1.101` env var |
| Freq reads 0 but motor runs | Wrong register bank | Verify with probe tool, check register offsets |
| Intermittent errors | Network congestion | Check cable, avoid daisy-chain, use switch |

## RS485 RTU Alternative

If the VFD only supports RS485 Modbus RTU (no Ethernet port), you need
a Modbus RTU-to-TCP gateway. The PLC can bridge this:

```
VFD (RS485 RTU) --> PLC Micro820 (RS485 port) --> Pi (Modbus TCP)
```

In this case:
- Set P14.01=1 (Modbus RTU, not TCP)
- Wire RS485 A/B to the PLC's serial port
- Configure the PLC as a Modbus gateway
- Point Pi-Factory at the PLC IP with the VFD's slave ID
