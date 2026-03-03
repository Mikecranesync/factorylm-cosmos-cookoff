# LESSON LOG — 2026-03-03

## Session: Anybus CompactCom 40 Re-Evaluation
**Node:** CHARLIE (192.168.1.12)
**Duration:** Single session
**Repo:** factorylm-cosmos-cookoff

---

## What Was Done (with proof)

### Research — 6 HMS reference sources evaluated

1. **abcc-example-raspberrypi** (GitHub) — Full read of README, main.c, hardware abstraction, driver config, network data parameters, callback functions, .gitmodules
2. **hms-abcc40** (GitHub) — Full read of Python package: __init__.py, setup.py
3. **HMS Tech Support KB 22794171326994** — SPI configuration for Pi + CompactCom 40
4. **Software Design Guide** — ADI structure, process data mapping, state machine, data types
5. **Modbus TCP Network Guide** — Register mapping, process data capacity (1536B read/write)
6. **EtherNet/IP Network Guide** — Assembly objects, max 1448B, CIP Parameter Object

### Deliverables

1. **anybus_reference.md** written to `/Users/Shared/cluster/betterclaw/memory/`
   - SPI config, GPIO pinout, software stack, ADI mapping (14 ADIs, 22B total)
   - Protocol recommendation (Modbus TCP first), architecture diagram
   - Bridge layer design (Unix domain socket, JSON lines)
   - Gap report with priorities

2. **This lesson log** written to `/Users/Shared/cluster/betterclaw/logs/`

3. **Exhaustive codebase search** confirmed: ZERO Anybus code exists in repo
   - No `pifactory/anybus/` directory, no `AnybusTagSource` class
   - No SPI code, no GPIO code, no CompactCom references
   - No `ANYBUS_HARDWARE` env var, no anybus in requirements.txt
   - Clean slate — this is good (no wrong code to undo)

### Proof

- Reference files committed to cluster memory and repo `cluster/` directory
- All 6 HMS sources cross-referenced in anybus_reference.md
- Gap report identifies 12 items across P1/P2/P3 priorities

---

## Human Mistakes This Session

- None observed. Requested evaluation before writing code — correct approach.

---

## AI Mistakes This Session

1. **V2.1 PRD conceptual error (caught during evaluation)**
   - The V2.1 PRD designed `_init_source` to treat Anybus as Priority 2 alternative to PLC_HOST
   - **WRONG:** Anybus and ModbusTagSource are COMPLEMENTARY and run in PARALLEL
   - ModbusTagSource: Pi reads PLC tags (PLC → Pi)
   - Anybus: Pi publishes processed data TO the PLC (Pi → PLC) and receives commands (PLC → Pi)
   - They serve opposite directions — one does not replace the other
   - **Impact:** Would have built wrong architecture if not caught

2. **hms-abcc40 mischaracterization (caught during evaluation)**
   - Previously assumed `hms-abcc40` was a process data bridge between C host app and Python
   - **WRONG:** It's a REST metadata reader (module_name, serial, firmware version, uptime, etc.)
   - Uses Python 2 `urllib2` — won't even run on Python 3 without patching
   - Does NOT read/write process data, does NOT communicate with C host app
   - **Impact:** Would have wasted time trying to use it as a bridge layer

3. **No code was written based on wrong assumptions**
   - Clean slate confirmed — all Anybus implementation starts fresh
   - This is the correct outcome: evaluate FIRST, code SECOND

---

## Fine-Tuning Candidates

1. **ADI direction naming is confusing**
   - PD_READ = "network reads from host" = Pi → PLC (host PUBLISHES)
   - PD_WRITE = "network writes to host" = PLC → Pi (host RECEIVES)
   - The perspective is from the NETWORK, not the host application
   - Training example: explicitly annotate direction in every ADI mapping comment

2. **CompactCom is a network slave**
   - It does not initiate communication — the PLC (or network master) polls it
   - Common misconception: thinking CompactCom "sends" data to PLC
   - Correct model: CompactCom makes data AVAILABLE, PLC reads when it wants

3. **hms-abcc40 uses Python 2 urllib2**
   - Would need porting: `urllib2` → `urllib.request`, `print` statements → functions
   - But it's only useful for diagnostics (module alive check), not process data
   - Training example: always check `setup.py` for Python version constraints before planning integration

4. **"Alternative" vs "complementary" pattern in system design**
   - Two components that handle different directions of the same data flow are complementary
   - Priority-based fallback (`try A, else B`) only applies when A and B serve the SAME function
   - Training example: the ModbusTagSource / AnybusTagSource distinction

---

## Cluster Status

- **Alpha (192.168.1.10):** Status unknown
- **CHARLIE (this node):** Operational. Writing to local cluster dirs at `/Users/Shared/cluster/`
- **Action:** Reference material now available in cluster memory for any node
