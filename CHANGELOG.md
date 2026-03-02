# Changelog

All notable changes to Pi Factory are documented in this file.

## [1.0.0] — 2026-03-02

### Added

- **Setup Wizard** — 6-screen browser-based first-run experience: gateway ID generation, PLC discovery, tag extraction, live preview, WiFi configuration
- **PLC Auto-Discovery** — scans subnet for Modbus TCP devices, identifies brand/model, extracts tags automatically
- **Live Polling** — background poller reads PLC tags at 5 Hz, writes history to SQLite at 1 Hz
- **Fault Engine** — 8 real-time fault codes (E001 E-Stop, M001 Overcurrent, T001/T002 Temperature, C001 Jam, M002 Motor Stopped, P001 Low Pressure, M003 Speed Mismatch)
- **Matrix Dashboard** — tag ingestion, incident tracking, Cosmos AI insight storage
- **Pi Image Build** — pi-gen pipeline produces flashable .img.xz with WiFi AP, systemd services, and auto-setup
- **DIY Installer** — `pi-factory/setup.sh` for existing Pi OS installations
- **WiFi Access Point** — PiFactory-Connect SSID with WPA2 security, captive portal at 192.168.4.1
- **First Boot** — auto-generates unique gateway ID, configures hostname, enables all services
- **CI Pipeline** — GitHub Actions: pytest (58 tests), endpoint smoke tests, shell syntax checks, py_compile lint
- **Image Build Pipeline** — GitHub Actions: tag-triggered pi-gen build, artifact upload, GitHub Release with install notes

### Fixed

- API endpoints return structured JSON errors instead of 500 crashes (WiFi scan, connect, all unhandled exceptions)
- Global exception handlers on Net API and Matrix API catch and log all uncaught errors
- Poller thread survives transient read errors with exponential backoff (10 consecutive errors → 10s pause)
- SQLite WAL mode for concurrent read/write safety
- Tests use unique temp directories (no shared /tmp DB conflicts)

### Changed

- Rebranded from "FactoryLM Cosmos Cookoff" to "Pi Factory" across all UI, services, and docs
- pi-gen config: hostname `factorylm-connect` → `pi-factory`, image name `FactoryLM-Connect` → `Pi-Factory`
- WiFi AP secured with WPA2-PSK (was open network)
- README rewritten with install instructions, architecture diagram, and API reference

### Internal

- Environment variables (`FACTORYLM_NET_MODE`, `FACTORYLM_NET_DB`, `MATRIX_DB_PATH`) intentionally unchanged to avoid breaking deployments
- Gateway ID prefix `flm-` preserved for backwards compatibility
- 70 pytest tests across 9 test files covering all critical paths
- Build pipeline validated with 12 pre-flight checks

---

## [0.1.0] — 2026-02-20

### Added

- Initial Cosmos Cookoff submission
- Diagnosis engine: frame capture + PLC tags → Cosmos Reason2-8B prompt
- Modbus TCP reader for Allen-Bradley Micro 820
- Factory I/O simulation bridge
- Matrix API with tag snapshots and incident tracking
- Conveyor of Destiny playbook and wiring guide
