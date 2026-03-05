# FactoryLM Research Abstracts Portfolio

**10 Papers from the FactoryLM Industrial AI Platform**
**March 2026**

Each abstract represents a distinct, publishable contribution backed by working code, real hardware, and measured results in the FactoryLM codebase.

---

## Paper 1: Multimodal Industrial Fault Diagnostics — Fusing Live Video and PLC Telemetry through Cosmos Reason2-8B

**Key Claim:** Cross-modal fusion of video and PLC data through a vision-language model discovers fault conditions invisible to either modality alone.

**Primary Evidence:** `demo/diagnosis_engine.py`, `demo/WHITEPAPER.md`

Factory technicians spend an estimated 40% of their working time diagnosing equipment faults through manual inspection, HMI displays, and paper manuals. Rule-based expert systems catch threshold violations but cannot correlate visual evidence with electrical anomalies. Vision models observe motion but cannot read amperage or temperature. We present FactoryLM Vision, a system that fuses live video from factory floor cameras with real-time PLC register data through NVIDIA Cosmos Reason2-8B. The system reads 18 coils and 6 holding registers from an Allen-Bradley Micro 820 PLC via Modbus TCP, captures video at 4 FPS, runs an 8-rule deterministic fault pre-filter, and constructs a multimodal prompt with chain-of-thought reasoning. In validated testing against a live PLC and Factory I/O simulation, the system produced structured diagnoses in 6.1 seconds for normal conditions and 17.0 seconds for complex multi-fault scenarios, consuming 229 to 693 tokens. The system identified a motor paradox — motor commanded ON but speed register reading zero — by correlating a visual observation (stationary box on belt, motor visibly energized) with PLC telemetry (motor coil ON, speed zero, no sensor pulses). This cross-modal diagnosis was impossible from either source alone. The full stack runs on commodity hardware at $0.53/hr in cloud GPU costs, with graceful degradation to video-only or rule-only modes when a data source is unavailable.

---

## Paper 2: Inverted Pyramid Intelligence — A Progressive Distillation Architecture for Industrial AI

**Key Claim:** Industrial AI systems should use less AI over time, not more, by converting confirmed cloud inference into deterministic edge rules.

**Primary Evidence:** `diagnosis/conveyor_faults.py`, `demo/WHITEPAPER.md` (Section 6.5)

The dominant paradigm in industrial AI assumes that more model capacity and more cloud inference yield better outcomes. We propose an inversion: the Inverted Pyramid, a four-layer intelligence architecture where Layer 3 (cloud vision-language models) is the starting point, not the steady state. Layer 3 deploys Cosmos Reason2-8B on cloud GPUs ($0.53/hr) for initial diagnostics on unfamiliar machines. Layer 2 implements a rule-based fault engine with 8 deterministic fault codes (E001 through T002), each defined by specific PLC tag thresholds — motor overcurrent above 5.0A, temperature above 80C, both photoeyes active simultaneously. Layer 1 runs on a Raspberry Pi edge device, polling PLC registers via Modbus TCP and applying Layer 2 rules locally with zero cloud dependency. Layer 0 is the target state: every Cosmos R2 diagnosis confirmed by a technician becomes a candidate for the rule engine, progressively distilling cloud intelligence into deterministic code. The architecture inverts the AI cost curve — a new machine starts at high cost (cloud inference for every query) and converges toward zero cost (local rules handle all common faults). We describe the distillation pipeline, present the current 8-rule implementation with measured thresholds from a live Allen-Bradley Micro 820 conveyor cell, and project the cost reduction trajectory as the rule base grows. The key insight is that industrial faults are highly repetitive: a small number of deterministic rules eventually covers the majority of failure modes for any given machine.

---

## Paper 3: Zero-Trust Factory Access — Securing Industrial Control Systems via Tailscale Mesh Networking

**Key Claim:** A WireGuard-based mesh overlay provides authenticated, encrypted access to PLC registers at 33ms round-trip latency with zero open ports.

**Primary Evidence:** `docs/CONVEYOR_OF_DESTINY.md` (Section 6, Section 10)

Industrial control systems face a fundamental connectivity dilemma: remote access enables AI-driven diagnostics, fleet management, and faster support response, but every open port on a factory network represents an attack surface for increasingly sophisticated threats to operational technology. Traditional VPN concentrators introduce single points of failure and require static IP configuration that conflicts with DHCP-managed plant networks. We present a zero-trust factory access architecture using Tailscale's WireGuard-based mesh overlay. The system connects a VPS-hosted diagnostic engine to an Allen-Bradley Micro 820 PLC (192.168.1.100:502) through a Tailscale mesh with no ports opened on any router. Measured Modbus TCP round-trip latency over the mesh is approximately 33ms, with health check acceptance criteria of under 100ms on local networks and under 50ms over Tailscale. The diagnostic pipeline enforces a read-only constraint: the AI system reads 18 coils and 6 holding registers but never writes to the controller. Write operations (motor start/stop, E-stop) require separate authorization through a distinct code path gated to a single authorized operator. Seven defense-in-depth layers span hardware (dual-contact E-stop), PLC logic (photoeye auto-stop), software (fixed speed, queue system, software E-stop), and network (Tailscale mesh). We describe the architecture, measure the latency overhead versus direct Modbus TCP, and analyze the security properties of the mesh overlay for industrial control applications.

---

## Paper 4: Boss-Agent Delegation Architecture for Industrial AI Orchestration

**Key Claim:** A hub-and-spoke delegation pattern with a central data bus eliminates O(n^2) coupling between industrial AI processes.

**Primary Evidence:** `demo/MATRIX_WHITEPAPER.md`, `demo/diagnosis_engine.py`

Industrial AI systems that fuse PLC telemetry, video, and machine learning insights face a structural problem before they face a modeling problem: where does the data live? Without centralized coordination, a system with n components requires up to n(n-1)/2 integration paths, making the system brittle, hard to test, and impossible to demo on a laptop. We present the Matrix architecture, a single FastAPI + SQLite REST API that serves as the central data bus for a multimodal industrial AI system. Eight independent processes — PLC bridge, video ingester, Cosmos R2 watcher, video analyzer, fault detector, dashboard, Telegram adapter, and Discord adapter — coordinate through 13 REST endpoints backed by 5 relational tables. No component communicates directly with any other. The orchestrator pattern is enforced architecturally: `diagnosis_engine.py` acts as the boss agent, accepting a diagnostic request, dispatching parallel data acquisition (PLC read + video capture), running the fault pre-filter, constructing the multimodal prompt, calling Cosmos R2, parsing the response, and returning the structured result. Matrix's most consequential design decision is the "smart write" pattern: when the PLC bridge POSTs a tag snapshot with a fault alarm active, Matrix auto-creates an incident record as a write side-effect. This eliminates the need for a separate fault detection service. The entire system starts with a single `uvicorn` command, requires zero configuration, and survives a laptop restart with data intact.

---

## Paper 5: Hardware-Agnostic PLC Discovery via Priority Waterfall Protocol Scanning

**Key Claim:** A 4-protocol waterfall scan (EtherNet/IP, OPC UA, Siemens S7, Modbus TCP) auto-discovers PLCs and extracts tags with zero manual configuration.

**Primary Evidence:** `net/drivers/tag_extractor.py`, `pi-factory/PI_FACTORY_GUIDE.md`

Connecting an industrial monitoring system to a PLC traditionally requires knowing the PLC's IP address, communication protocol, and tag/register map in advance. This manual configuration step is the primary barrier to deploying AI diagnostics on factory floors, where a single facility may contain PLCs from multiple manufacturers using incompatible protocols. We present a priority waterfall scanner that auto-discovers PLCs and extracts their tag databases without manual configuration. The `TagExtractor` in `net/drivers/tag_extractor.py` scans a subnet using asyncio with a concurrency limit of 50 simultaneous connections and a 0.3-second timeout per attempt. For each discovered IP, it attempts four industrial protocols in strict priority order: EtherNet/IP (port 44818), OPC UA (port 4840), Siemens S7 (port 102), and Modbus TCP (port 502). The scanner returns on the first protocol that successfully extracts tags, avoiding unnecessary probes. Each protocol handler returns a standardized `ExtractionResult` containing tag name, address, type, value, and writability — normalizing the heterogeneous tag formats across EtherNet/IP symbolic tags, OPC UA node hierarchies, S7 data blocks, and Modbus register ranges into a single schema. The scanner is integrated into the Pi Factory setup wizard, where Screen 3 runs the waterfall automatically after subnet scanning discovers PLC candidates. The result is a zero-configuration experience: plug the Pi into the PLC subnet, and the wizard presents the discovered tags for human-readable naming within 30 seconds.

---

## Paper 6: Defense-in-Depth Safety Architecture for Internet-Connected Industrial Equipment

**Key Claim:** Eight independent safety layers ensure that no single failure — hardware, software, or network — can result in uncontrolled machine operation.

**Primary Evidence:** `docs/CONVEYOR_OF_DESTINY.md` (Section 10), `diagnosis/conveyor_faults.py`

Connecting factory equipment to the internet for remote diagnostics and crowd-sourced interaction creates safety challenges that no single mechanism can address. We present a defense-in-depth safety architecture implemented on a live Allen-Bradley Micro 820 PLC controlling a VFD-driven conveyor belt accessible from the public internet. The architecture implements eight independent safety layers: (1) a physical E-stop button with dual-contact validation using NO and NC contacts — `fault_alarm = coil[8] AND NOT coil[9]` — that catches wiring faults by detecting when both contacts read the same state; (2) PLC-level photoeye auto-stop that halts the belt when SensorStart (coil 2) or SensorEnd (coil 3) trips, running as ladder logic independent of any software stack; (3) dual-contact E-stop validation in PLC logic ensuring a single wire fault cannot silently disable the safety system; (4) fixed VFD speed — the frequency setpoint is locked in the PLC program at approximately 10 Hz (~300 RPM), and public users cannot modify it; (5) a queue system enforcing one user at a time with 10-second timeouts, preventing command flooding; (6) a software E-stop command restricted to a single authorized operator; (7) a read-only diagnostic AI pipeline that reads PLC registers but architecturally cannot write to the controller; and (8) a Tailscale mesh network with zero open ports, ensuring the PLC is never directly reachable from the public internet. We analyze the failure modes each layer addresses and demonstrate that the system degrades safely under any single-layer failure.

---

## Paper 7: Zero-Config Industrial Edge Appliance — From Stock Raspberry Pi to PLC Monitor in 10 Minutes

**Key Claim:** A flashable Raspberry Pi image with a WiFi captive portal wizard transforms a stock Pi into a PLC monitoring appliance requiring zero manual configuration.

**Primary Evidence:** `pi-factory/setup.sh`, `pi-factory/PI_FACTORY_GUIDE.md`, `.github/workflows/build-image.yml`

Deploying industrial monitoring on the factory floor typically requires a systems integrator to configure network settings, install middleware, set up PLC drivers, and write custom polling logic. We present Pi Factory, a zero-configuration edge appliance that transforms a stock Raspberry Pi (3B+, 4, 5, or Zero 2W) into an industrial PLC monitor in 10 minutes. The system is installed with three commands on Raspberry Pi OS Bookworm. The `setup.sh` script executes 9 automated steps: system dependencies, directory structure, Python virtual environment with pymodbus/pycomm3/opcua, application deployment, WiFi captive portal (`PiFactory-Connect` on 192.168.4.1), systemd services with watchdog, unique gateway ID generation, hostname branding, and launch verification. On first boot, a technician connects their phone to the WiFi hotspot. A browser-based wizard guides them through 6 screens: welcome, subnet scanning for PLCs, automatic tag extraction via a 4-protocol waterfall (EtherNet/IP, OPC UA, Siemens S7, Modbus TCP), tag selection with human-readable naming, a live data panel showing PLC values flowing at 5 Hz, and WiFi uplink configuration for cloud connectivity. The GitHub Actions CI pipeline (`build-image.yml`) uses `pi-gen` to produce a flashable `.img.xz` artifact on every semver tag, with 70 pytest tests across 9 test files and 12 pre-flight checks. The release manifest is compatible with Raspberry Pi Imager's custom image URL feature, enabling one-click flashing.

---

## Paper 8: Declarative Industrial Workflow Orchestration via the Matrix Data Bus

**Key Claim:** A single FastAPI + SQLite REST API replaces Kafka, Redis, and dedicated message brokers for industrial AI coordination, starting with one command and zero configuration.

**Primary Evidence:** `demo/MATRIX_WHITEPAPER.md`, `services/matrix/app.py`

Industrial AI deployments typically require a complex middleware stack — Kafka for event streaming, Redis for caching, TimescaleDB for time-series, and a dedicated message broker for inter-service communication. This infrastructure obscures the AI contribution and makes demos, testing, and single-machine deployment impractical. We present Matrix, a declarative data bus implemented as a single FastAPI application backed by SQLite. Matrix serves 13 REST endpoints organized around 5 relational tables: tag snapshots, incidents, video clips, Cosmos R2 analyses, and system configuration. Eight independent processes — PLC bridge, video ingester, Cosmos watcher, video analyzer, fault detector, dashboard, Telegram adapter, and Discord adapter — coordinate exclusively through Matrix's REST API. The key design pattern is "smart writes": when the PLC bridge POSTs a tag snapshot containing a fault alarm or E-stop condition, Matrix auto-creates an incident record as a write side-effect, eliminating the need for a separate event detection service. Downstream consumers simply poll for open incidents. The entire system starts with `uvicorn services.matrix.app:app`, requires zero environment variables for local operation, and persists all data through SQLite WAL mode for crash recovery. For production deployment, the architecture specifies a migration path to TimescaleDB (automatic partitioning, continuous aggregates, sub-millisecond range queries) while keeping the REST API surface identical. We measured the system running eight concurrent processes on a single laptop with sub-second end-to-end latency from PLC tag write to dashboard render.

---

## Paper 9: Internet-Controlled Industrial Equipment — The Conveyor of Destiny

**Key Claim:** A turn-based crowd-control architecture enables safe public internet control of real industrial equipment through Discord, web, and Telegram interfaces.

**Primary Evidence:** `docs/CONVEYOR_OF_DESTINY.md` (Section 7), `demo/WHITEPAPER.md`

We present the Conveyor of Destiny, a live demonstration in which anyone on the internet types a command — `left` or `right` — in Discord, on a web page, or via Telegram, and a real Allen-Bradley Micro 820 PLC drives a real ATO VFD-powered conveyor belt in Lake Wales, Florida. The command traverses a VPS (100.68.120.99) dispatching via Tailscale to an edge gateway, through Modbus TCP at approximately 33ms latency to the PLC at 192.168.1.100:502, which sends RS485 Modbus RTU commands to the VFD. The belt moves in the commanded direction until a photoeye sensor trips (SensorStart at coil 2 or SensorEnd at coil 3), at which point PLC ladder logic stops the motor and the turn ends. A turn-based queue system enforces sequential access: FIFO ordering, one user at a time, 10-second timeout before automatic skip. After each turn, Cosmos Reason2-8B narrates the result with real telemetry: direction, distance, duration, motor frequency, and current draw. The system implements seven defense-in-depth safety layers from hardware E-stop to Tailscale mesh networking. Every turn generates a labeled data point (direction, duration, motor current, frequency, timestamp, username, platform), building a real industrial motor event dataset from public interaction. The demonstration proves the FactoryLM thesis in miniature: natural language commands can safely control real industrial equipment from anywhere on Earth, mediated by a queue, secured by layered defenses, and narrated by AI.

---

## Paper 10: Structured Fault Taxonomy for Industrial Technicians — 8 Codes from E001 to T002

**Key Claim:** A compact, deterministic fault taxonomy with 4 severity levels and 8 codes provides instant technician-actionable diagnostics before any LLM invocation.

**Primary Evidence:** `diagnosis/conveyor_faults.py`

Industrial fault classification systems tend toward one of two extremes: vendor-specific fault code databases with hundreds of opaque numeric codes, or AI-generated natural language descriptions that lack deterministic reproducibility. We present a structured fault taxonomy designed as the deterministic foundation layer of a multimodal AI diagnostic system. The taxonomy defines 8 fault codes across 4 severity levels (EMERGENCY, CRITICAL, WARNING, INFO) for a conveyor cell built on an Allen-Bradley Micro 820 PLC. Each code maps a specific PLC tag pattern to a `FaultDiagnosis` data structure containing: fault code identifier, severity level, human-readable title, plain-language description, list of likely root causes, ordered suggested maintenance checks, affected PLC tags, and boolean flags for `requires_maintenance` and `requires_safety_review`. The codes are: E001 (EMERGENCY, E-stop active), M001 (CRITICAL, motor overcurrent above 5.0A), T001 (CRITICAL, temperature above 80C), C001 (CRITICAL, conveyor jam with both photoeyes active), M002 (CRITICAL, unexpected motor stop with nonzero speed setpoint), P001 (WARNING, pneumatic pressure below 60 PSI), M003 (WARNING, motor speed below 30% with conveyor setpoint above 50%), and T002 (WARNING, elevated temperature between 65C and 80C). The classifier runs in under 1 millisecond on any hardware, produces deterministic output for identical inputs, and serves two roles in the FactoryLM architecture: standalone instant diagnosis for known fault patterns, and structured evidence injection into Cosmos R2 prompts to anchor the model's chain-of-thought reasoning on verified PLC data.

---

*FactoryLM — Build the dataset and reasoning layer that every industrial maintenance robot will need.*
*Repository: https://github.com/Mikecranesync/factorylm-cosmos-cookoff*
