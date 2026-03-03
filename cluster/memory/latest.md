# FactoryLM Cluster — Latest State

**Last updated:** 2026-03-03
**Updated by:** CHARLIE

## Current Version: v1.5.0
- **Repo:** factorylm-cosmos-cookoff
- **Commit:** 96823fd
- **Tag:** v1.5.0 (GitHub Release: Latest)
- **Rollback:** `rollback/v1.5.0` branch (locked)
- **Tests:** 94/94 passing

## What v1.5.0 Added
- Belt speed tracker (vision-based, orange tape marker)
- AI video diagnosis via Cosmos R2
- 3 new endpoints: `/api/belt/status`, `/api/belt/diagnose`, `/api/belt/stream`
- Fully backwards-compatible with v1.0/v1.1

## Anybus CompactCom 40 Evaluation (2026-03-03)
- Full re-evaluation completed against 6 HMS reference sources
- **Key correction:** Anybus is COMPLEMENTARY to ModbusTagSource (parallel, not alternative)
- **Key correction:** `hms-abcc40` is REST metadata only, NOT a process data bridge
- ADI mapping defined: 14 ADIs, 22 bytes total (10 read Pi→PLC, 4 write PLC→Pi)
- Protocol: Modbus TCP first (AB6603-E), EtherNet/IP later
- Bridge: Unix domain socket (`/run/abcc/process_data.sock`, JSON lines)
- Full reference: `cluster/memory/anybus_reference.md`
- Gap report: 12 items, all MISSING (clean slate — no wrong code to undo)

## Key Files (v1.5)
- `cosmos/belt_tachometer.py` — tachometer core
- `cosmos/reasoner.py` — belt video AI diagnosis
- `simulate.py` — main entry point
- `tests/test_belt_tachometer.py` — 22 belt tests

## Known Issues
- Python 3.9.6 on CHARLIE — use `Optional[X]` not `X | None` for type hints
- Alpha offline — cluster SMB not mounted, local dirs created at `/Users/Shared/cluster/`
