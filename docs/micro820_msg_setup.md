# Micro820 MSG Instruction — Read from Pi-Factory

## What This Does

The Micro820 uses a MSG (Message) instruction to read 10 holding registers
from the Pi's Modbus TCP server at port 5020. This gives the PLC direct
access to belt RPM, AI diagnosis status, VFD data, and a watchdog heartbeat.

The PLC can also write 4 command registers back to the Pi for remote
run/stop, speed control, mode selection, and fault reset.

## Requirements

- Pi-Factory running with `PI_COMPACTCOM_PORT=5020`
- Pi IP: 192.168.1.12 (CHARLIE node) or wherever the Pi is on the network
- Micro820 and Pi on the same subnet (192.168.1.x)
- Connected Components Workbench (CCW) installed on the PLC laptop

## Network Diagram

```
Micro820 PLC (192.168.1.100:502)
     |
     |  MSG instruction, Modbus TCP client
     |  Function Code 03 (Read) / 16 (Write)
     |
     v
Pi-Factory (192.168.1.12:5020)
     |
     |  pymodbus TCP server
     |  200 holding registers
     |
     v
Published: regs 0-9 (belt RPM, VFD Hz, AI fault, heartbeat)
Commands:  regs 100-103 (run, speed, mode, fault reset)
```

## CCW Configuration Steps

### Step 1: Create PLC Tags

In CCW, create the following tags in your Global Variables:

```
Pi_Data       INT[10]    -- Received data from Pi
Pi_Cmd        INT[4]     -- Commands to send to Pi
Pi_HB_Prev    INT        -- Previous heartbeat for watchdog
Pi_Comms_OK   BOOL       -- Pi communication healthy
Pi_Comms_Lost BOOL       -- Pi communication lost
Pi_MSG_Done   BOOL       -- MSG instruction complete
Pi_MSG_Error  BOOL       -- MSG instruction error
Pi_Read_EN    BOOL       -- Enable periodic read
Pi_Write_EN   BOOL       -- Enable periodic write
```

### Step 2: Add MSG Read Instruction

In your main ladder program, add a rung for the MSG read:

```
|--[Pi_Read_EN]--[MSG READ]--|
                    |
                    +-- Message Type: Modbus TCP
                    +-- Service: Read
                    +-- Remote IP: 192.168.1.12
                    +-- Remote Port: 5020
                    +-- Function Code: 03 (Read Holding Registers)
                    +-- Start Register: 0
                    +-- Number of Registers: 10
                    +-- Destination: Pi_Data[0]
                    +-- Done Bit: Pi_MSG_Done
                    +-- Error Bit: Pi_MSG_Error
```

### Step 3: Configure MSG Parameters in CCW

1. Open your Micro820 project in CCW
2. Double-click the MSG instruction to open its configuration
3. Set these fields:

| Parameter | Value |
|-----------|-------|
| Message Type | CIP Generic |
| Service Type | Modbus TCP Client |
| Protocol | Modbus TCP |
| Remote IP Address | 192.168.1.12 |
| Remote Port | 5020 |
| Function Code | 03 - Read Holding Registers |
| Start Address | 0 |
| Length | 10 |
| Local Tag | Pi_Data[0] |

### Step 4: Add Periodic Timer

Create a 200ms periodic timer to trigger the MSG read:

```
|--[TON Timer1, 200ms]--[Timer1.DN]--+--[Pi_Read_EN SET]--|
                                     +--[Timer1 Reset]----|
```

This reads the Pi every 200ms (5Hz), matching the Publisher update rate.

### Step 5: Decode Received Values

After MSG completes (`Pi_MSG_Done = 1`), decode the received registers:

```
Pi_BeltRPM      := Pi_Data[0] / 10.0    -- Belt RPM (30.5 RPM = 305)
Pi_BeltSpeed    := Pi_Data[1] / 10.0    -- Belt speed % (50.0% = 500)
Pi_BeltStatus   := Pi_Data[2]           -- 0=calibrating, 1=stopped, 2=normal, 3=slow, 4=mistrack
Pi_BeltOffset   := Pi_Data[3] - 32768   -- Signed pixel offset (-50 = 32718)
Pi_VFD_Hz       := Pi_Data[4] / 100.0   -- VFD frequency (30.00 Hz = 3000)
Pi_VFD_Amps     := Pi_Data[5] / 10.0    -- VFD current (4.5 A = 45)
Pi_VFD_Fault    := Pi_Data[6]           -- VFD fault code (0 = no fault)
Pi_AI_Fault     := Pi_Data[7]           -- AI fault code (0 = no fault)
Pi_AI_Conf      := Pi_Data[8]           -- AI confidence 0-100%
Pi_Heartbeat    := Pi_Data[9]           -- Must change each scan
```

### Step 6: Belt Status Enum Reference

| Value | Status | Meaning |
|-------|--------|---------|
| 0 | CALIBRATING | Tachometer initializing |
| 1 | STOPPED | Belt not moving |
| 2 | NORMAL | Running within tolerance |
| 3 | SLOW | Speed below threshold |
| 4 | MISTRACK | Belt lateral drift detected |

### Step 7: Watchdog Ladder Logic

The heartbeat register (Pi_Data[9]) increments every 200ms. Use it to
detect if the Pi stops communicating:

```
|--[Pi_MSG_Done]--[NEQ Pi_Data[9] Pi_HB_Prev]--[MOV Pi_Data[9] Pi_HB_Prev]--|
                                                [TON WD_Timer Reset]---------|

|--[TON WD_Timer, 2000ms]--[WD_Timer.DN]--[Pi_Comms_Lost SET]--|
                                          [Pi_Comms_OK RESET]--|

|--[Pi_MSG_Done]--[NEQ Pi_Data[9] Pi_HB_Prev]--[Pi_Comms_OK SET]--|
                                               [Pi_Comms_Lost RESET]--|
```

Logic:
1. Every time MSG completes, compare heartbeat to previous value
2. If different, reset the watchdog timer (Pi is alive)
3. If the watchdog reaches 2 seconds without a heartbeat change, set `Pi_Comms_Lost`
4. When `Pi_Comms_Lost = 1`, the PLC should take safe action (e.g., stop belt)

## Write Commands Back to Pi (Optional)

To send run/stop/speed commands from the PLC to the Pi, add a second
MSG instruction:

```
|--[Pi_Write_EN]--[MSG WRITE]--|
                     |
                     +-- Function Code: 16 (Write Multiple Registers)
                     +-- Remote IP: 192.168.1.12
                     +-- Remote Port: 5020
                     +-- Start Register: 100
                     +-- Number of Registers: 4
                     +-- Source: Pi_Cmd[0]
```

Command register format:

| Pi_Cmd Index | Register | Encoding |
|--------------|----------|----------|
| Pi_Cmd[0] | 100 - cmd_run | 0=stop, 1=run |
| Pi_Cmd[1] | 101 - cmd_speed_pct | x10 (600 = 60.0%) |
| Pi_Cmd[2] | 102 - cmd_mode | 0=manual, 1=auto, 2=maintenance |
| Pi_Cmd[3] | 103 - cmd_reset_fault | 1=reset (auto-clears) |

Example: to command the belt at 60% speed in auto mode:
```
Pi_Cmd[0] := 1     -- RUN
Pi_Cmd[1] := 600   -- 60.0%
Pi_Cmd[2] := 1     -- auto mode
Pi_Cmd[3] := 0     -- no fault reset
```

## Verification Checklist

After configuring the MSG instruction:

- [ ] `Pi_MSG_Done` goes TRUE after each scan
- [ ] `Pi_MSG_Error` stays FALSE
- [ ] `Pi_Data[9]` (heartbeat) increments every scan
- [ ] `Pi_Comms_OK` = TRUE
- [ ] Change belt speed on the machine, verify `Pi_Data[0]` changes
- [ ] Write `Pi_Cmd[0] = 1` (RUN), check Pi API: `curl localhost:8081/api/compactcom/commands`

## Troubleshooting

| Symptom | Check |
|---------|-------|
| MSG errors | Verify Pi IP, port 5020 open: `telnet 192.168.1.12 5020` |
| Heartbeat stuck | Pi Publisher may be crashed — check Pi-Factory logs |
| All zeros | Pi is running but no belt camera or VFD connected |
| Comms lost after minutes | Check Pi network stability, Tailscale timeout |
| Can read but not write | Verify MSG write uses FC16, start register 100 |
