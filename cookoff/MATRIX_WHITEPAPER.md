# Matrix API: A Central Data Bus for Multimodal Industrial AI

**NVIDIA Cosmos Cookoff 2026 — Supplementary Architecture Paper**
**Model: NVIDIA Cosmos Reason2-8B (via vLLM 0.15.1)**
**Last Updated: February 21, 2026**

---

## Executive Summary

Industrial AI systems that fuse PLC telemetry, video, and machine learning insights face a
structural problem before they face a modeling problem: where does the data live? In a typical
integration, the PLC historian holds register values, the NVR holds video, the AI service holds
inference results, and the incident tracker holds fault records. Each component must know how to
reach every other, producing O(n^2) coupling that makes the system brittle, hard to test, and
impossible to run on a laptop for a demo.

Matrix is the FactoryLM answer to this problem. It is a single FastAPI + SQLite REST API that
serves as the central data bus for the entire Cosmos Cookoff entry. Every producer (the PLC
bridge, the video ingester) writes to Matrix. Every consumer (the Cosmos watcher, the video
analyzer, the embedded dashboards) reads from Matrix. No component communicates directly with
any other. The result is a system where eight independent processes coordinate through thirteen
REST endpoints backed by five relational tables — and the whole thing starts with a single
`uvicorn` command.

Matrix's most consequential design decision is the "smart write" pattern: when the PLC bridge
POSTs a tag snapshot with a fault alarm or e-stop active, Matrix auto-creates an incident record
as a write side-effect. This eliminates the need for a separate fault detection service. The
incident exists the moment the data arrives. Downstream consumers — the Cosmos watcher that
triggers AI analysis, the dashboard that renders fault status — simply poll for open incidents.
The write path does the detection; the read path does the reaction.

This document describes Matrix's architecture, data model, API surface, and the consumer
ecosystem it enables.

---

## 1. Problem: Data Fragmentation in Industrial AI Systems

### 1.1 The Silo Problem

A modern factory floor produces data in at least four distinct formats from four distinct
systems:

- **PLC telemetry**: Motor current, temperature, pressure, conveyor speed — sampled at 2-10 Hz,
  stored in proprietary historians (Rockwell FactoryTalk, Siemens WinCC).
- **Video**: IP camera streams stored on NVRs or edge recorders, typically as H.264/H.265 in
  proprietary containers.
- **AI inference results**: Model outputs — diagnoses, anomaly scores, chain-of-thought
  reasoning — stored in application databases or log files.
- **Incident records**: Fault events, operator actions, maintenance tickets — stored in CMMS
  platforms (SAP PM, Maximo) or spreadsheets.

Each silo has its own query interface, its own time representation, and its own access control.
Answering the question "what happened at 14:32?" requires joining data across four systems
manually.

### 1.2 The Coupling Problem

Without a central store, each component that needs data from another must establish a direct
connection. A system with n components requires up to n(n-1)/2 integration paths. Adding a new
consumer — say, a mobile dashboard — requires wiring it to every producer individually.

Traditional SCADA historians solve this partially for telemetry but are read-only archives
optimized for trend queries, not real-time data buses that support write-side-effects like
automatic incident creation.

### 1.3 The Demo Problem

Competition entries and customer demos must run reliably on constrained hardware — often a
single laptop. Systems that depend on Kafka, TimescaleDB, Redis, and a message broker require
infrastructure that obscures the AI contribution. Matrix's design constraint was: the entire
data layer must start with one command, require zero configuration, and survive a laptop
restart with data intact.

---

## 2. Architecture: Matrix as the Central Data Bus

### 2.1 System Topology

```
                            +--------------------------+
                            |      Matrix API          |
                            |  FastAPI + SQLite        |
                            |  services/matrix/app.py  |
                            |  Port 8000               |
                            +-----+----------+---------+
                                  |          |
              +-------------------+          +--------------------+
              |                                                   |
      PRODUCERS (write)                                  CONSUMERS (read)
              |                                                   |
  +-----------+----------+                          +-------------+-----------+
  |                      |                          |             |           |
  v                      v                          v             v           v
+------------------+ +------------------+  +---------------+ +----------+ +----------+
| factoryio_bridge | | video/ingester   |  | cosmos/watcher| | cosmos/  | | video/   |
| sim/factoryio_   | | video/ingester.py|  | cosmos/       | | agent.py | | cosmos_  |
| bridge.py        | |                  |  | watcher.py    | |          | | analyzer |
|                  | |                  |  |               | |          | | .py      |
| POST /api/tags   | | POST /api/video/ |  | GET /api/     | | GET /api/| | GET+POST |
|                  | | clips            |  | incidents     | | tags     | | /api/    |
|                  | |                  |  | POST /api/    | |          | | video/*  |
|                  | |                  |  | insights      | |          | |          |
+------------------+ +------------------+  +---------------+ +----------+ +----------+
                                                                            |
                                                              +-------------+----------+
                                                              |            |           |
                                                              v            v           v
                                                         +----------+ +----------+ +------+
                                                         | video/   | | video/   | | HMI  |
                                                         | highlight| | short_   | | Dash |
                                                         | _selector| | builder  | | /    |
                                                         | .py      | | .py      | | /video
                                                         +----------+ +----------+ +------+
```

### 2.2 Design Principles

**REST over HTTP.** Every interaction is a standard HTTP request. No WebSockets, no message
queues, no pub/sub. Consumers poll at their own cadence. This makes the system trivially
debuggable with `curl` and eliminates connection state management.

**SQLite for demo simplicity.** A single `matrix.db` file holds all state. No database server
to install, no connection pooling to configure. WAL mode (`PRAGMA journal_mode=WAL`) enables
concurrent readers without blocking the writer. The file survives process restarts and can be
inspected with any SQLite browser.

**Stateless clients.** Every consumer is a loop: poll Matrix, process results, post back. No
client holds state that cannot be reconstructed from the database. This means any component can
crash and restart without data loss or coordination.

**The smart write pattern.** `POST /api/tags` is not a passive data sink. When the incoming
payload has `fault_alarm=True` and a nonzero `error_code`, or when `e_stop=True`, the endpoint
checks for an existing open incident with the same `node_id` and error code. If none exists, it
creates one — atomically, in the same transaction as the tag insert. The caller receives both
the `tag_id` and the `incident_id` (if created) in the response. This design means fault
detection happens at write time with zero additional latency, zero additional services, and zero
risk of a race condition between detection and recording.

---

## 3. Data Model

### 3.1 Table Schemas

Matrix defines five tables, initialized at startup in `init_db()`:

**tag_snapshots** — PLC telemetry at a point in time.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment row ID |
| timestamp | TEXT | ISO-8601 capture time |
| node_id | TEXT | Source identifier (e.g. `factoryio-127.0.0.1`) |
| motor_running | INTEGER | Boolean: motor energized |
| motor_speed | INTEGER | 0-100% speed setpoint |
| motor_current | REAL | Amps (scaled by bridge: raw / 10) |
| temperature | REAL | Degrees C (scaled: raw / 10) |
| pressure | INTEGER | PSI |
| conveyor_running | INTEGER | Boolean: belt moving |
| conveyor_speed | INTEGER | 0-100% belt speed |
| sensor_1 | INTEGER | Boolean: entry photoeye |
| sensor_2 | INTEGER | Boolean: exit photoeye |
| fault_alarm | INTEGER | Boolean: any fault active |
| e_stop | INTEGER | Boolean: emergency stop engaged |
| error_code | INTEGER | 0=OK, 1=Overload, 2=Overheat, 3=Jam, 4=Sensor, 5=Comms |
| error_message | TEXT | Human-readable error description |

**incidents** — Fault events, auto-created by `POST /api/tags`.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment incident ID |
| timestamp | TEXT | ISO-8601 detection time |
| node_id | TEXT | Source identifier |
| error_code | INTEGER | Fault code (-1 for e-stop) |
| error_message | TEXT | Description |
| status | TEXT | `open` or `analyzed` |
| trigger_tag_id | INTEGER | FK to tag_snapshots.id that triggered creation |
| tags_json | TEXT | JSON snapshot of the triggering tag payload |

**cosmos_insights** — AI analysis results produced by Cosmos Reason 2.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment insight ID |
| incident_id | INTEGER FK | References incidents.id |
| timestamp | TEXT | ISO-8601 analysis completion time |
| summary | TEXT | One-line fault summary |
| root_cause | TEXT | Identified root cause |
| confidence | REAL | Model confidence 0.0-1.0 |
| reasoning | TEXT | Chain-of-thought reasoning trace |
| suggested_checks_json | TEXT | JSON array of maintenance actions |
| video_url | TEXT | Associated video evidence URL |
| cosmos_model | TEXT | Model identifier used for analysis |

**video_clips** — Registered video segments.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment clip ID |
| timestamp | TEXT | ISO-8601 registration time (auto-set) |
| video_id | TEXT | Source video batch identifier |
| source_file | TEXT | Original recording file path |
| chunk_file | TEXT | Chunked clip file path |
| start_time | REAL | Start offset in source (seconds) |
| end_time | REAL | End offset in source (seconds) |
| duration | REAL | Clip length (seconds) |
| source_camera | TEXT | Camera identifier (default: `default`) |
| status | TEXT | `pending_analysis`, `analyzed`, or `highlight` |
| incident_id | INTEGER FK | Optional reference to incidents.id |

**video_analyses** — Cosmos video analysis results.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment analysis ID |
| clip_id | INTEGER FK | References video_clips.id |
| timestamp | TEXT | ISO-8601 analysis time (auto-set) |
| caption | TEXT | Natural-language scene description |
| key_events_json | TEXT | JSON array of {timestamp, action} objects |
| interesting_score | INTEGER | 0-100 relevance score |
| cosmos_model | TEXT | Model identifier |

### 3.2 Data Lifecycle

**Telemetry lifecycle:** The bridge posts tag snapshots continuously at 2-5 Hz. Each snapshot
is a row in `tag_snapshots`. When a fault condition appears (fault alarm + error code, or
e-stop), the tag insert atomically creates an incident with `status='open'`. The triggering
tag's ID is stored as `trigger_tag_id` and the full payload as `tags_json`, preserving the
exact state at fault detection.

**Incident lifecycle:** An incident begins as `open`. The Cosmos watcher polls
`GET /api/incidents?status=open`, picks up the incident, fetches tag history via
`GET /api/tags?node_id=X&seconds=60`, sends the bundle to Cosmos Reason 2, and posts the
resulting insight via `POST /api/insights`. The insight creation handler atomically sets the
incident status to `analyzed`. An incident never reopens — a new fault creates a new incident.

**Video lifecycle:** The ingester watches a directory for new recordings, chunks them with
ffmpeg, and registers each chunk via `POST /api/video/clips` with status `pending_analysis`.
The video analyzer polls for pending clips, sends each to Cosmos Reason 2 via
`CosmosClient.analyze_video()`, posts the analysis via `POST /api/video/analyses`, and patches
the clip status to `analyzed` or `highlight` (if `interesting_score >= threshold`). The
highlight selector queries for clips with `status=highlight`, ranks by score, and the short
builder concatenates selected clips into demo videos.

---

## 4. API Surface

### 4.1 Endpoint Reference

| Method | Path | Query Params | Purpose | Primary Callers |
|--------|------|-------------|---------|-----------------|
| GET | `/api/health` | — | Liveness check | ops tooling |
| POST | `/api/tags` | — | Ingest tag snapshot; auto-create incident on fault | `factoryio_bridge.py` |
| GET | `/api/tags` | `limit`, `node_id`, `seconds` | List recent tags with optional time-window filter | `cosmos/agent.py`, `demo_ui.py`, HMI dashboard |
| GET | `/api/incidents` | `status`, `limit` | List incidents, optionally filtered by status | `cosmos/watcher.py`, HMI dashboard |
| GET | `/api/incidents/{id}` | — | Get single incident with attached cosmos insight | HMI dashboard |
| POST | `/api/insights` | — | Store Cosmos R2 analysis for an incident; sets incident status to `analyzed` | `cosmos/watcher.py` |
| GET | `/api/insights` | `limit` | List recent insights | HMI dashboard |
| POST | `/api/video/clips` | — | Register a new video clip | `video/ingester.py` |
| GET | `/api/video/clips` | `status`, `limit` | List clips, optionally by status | `video/cosmos_analyzer.py`, `video/highlight_selector.py` |
| GET | `/api/video/clips/{id}` | — | Get single clip metadata | `video/short_builder.py` |
| PATCH | `/api/video/clips/{id}` | — | Update clip status | `video/cosmos_analyzer.py` |
| POST | `/api/video/analyses` | — | Store video analysis result | `video/cosmos_analyzer.py` |
| GET | `/api/video/analyses` | `clip_id`, `limit` | List analyses, optionally by clip | `video/highlight_selector.py`, Video Log HMI |

Additionally, two HTML endpoints serve embedded dashboards directly from the API process:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Live HMI dashboard — tag values, incident list, insight detail |
| GET | `/video` | Video Log — clip table with scores, captions, key event detail |

### 4.2 Resource Groups

The thirteen API endpoints organize into four resource groups:

1. **Tags** (2 endpoints): The write path for telemetry and the read path for trend queries.
   The `seconds` query parameter on `GET /api/tags` enables time-window filtering — the
   foundation for injecting trend context into Cosmos R2 prompts.

2. **Incidents** (3 endpoints): The read path for fault events. `GET /api/incidents/{id}`
   joins the incident with its cosmos insight in a single response, eliminating a client-side
   join.

3. **Insights** (2 endpoints): The write path for AI analysis results and the read path for
   dashboard display. The `POST` handler enforces referential integrity — it verifies the
   incident exists before accepting the insight.

4. **Video** (5 endpoints): Full CRUD lifecycle for video clips and their analyses. The
   `PATCH` endpoint enables the status machine (`pending_analysis` -> `analyzed` -> `highlight`)
   that drives the video pipeline.

---

## 5. What Matrix Unlocks

### 5.1 Trend-Based AI Reasoning

Cosmos Reason 2 produces better diagnoses when it sees trend data, not just a single snapshot.
The `CosmosAgent.on_incident()` method in `cosmos/agent.py` fetches recent tag history via
`GET /api/tags?node_id=X&seconds=60` and injects it as JSON context into the R2 prompt. This
allows R2 to observe patterns like "motor current has been climbing for the last 90 seconds" —
a signal invisible in a point-in-time snapshot. Matrix makes this possible by storing every tag
snapshot at ingestion frequency (2-5 Hz) and exposing a time-window query interface.

### 5.2 Decoupled Pipelines

The PLC bridge does not know the Cosmos watcher exists. The video ingester does not know the
video analyzer exists. Each component polls Matrix at its own interval and processes what it
finds. This means:

- Components can be started, stopped, and restarted independently.
- The system degrades gracefully: if the Cosmos watcher crashes, incidents accumulate as `open`
  and are analyzed when the watcher restarts.
- New consumers can be added without modifying any producer. The demo dashboard, for example,
  was built by reading the same endpoints the watcher uses — zero code changes to any existing
  component.

### 5.3 Auto-Incident Creation

The `POST /api/tags` handler in `services/matrix/app.py` implements fault detection as a write
side-effect. When `fault_alarm=True` and `error_code > 0`, or when `e_stop=True`, the handler
checks for an existing open incident with the same `node_id` and effective error code. If none
exists, it creates one in the same database transaction. This design has three advantages:

1. **Zero detection latency.** The incident exists at the moment the fault data is written. No
   polling delay, no queue latency.
2. **No separate detection service.** Fault detection logic lives in three lines of SQL, not in
   a dedicated process that must be deployed, monitored, and kept running.
3. **Deduplication by default.** The check for an existing open incident with the same node and
   error code prevents duplicate incidents during sustained fault conditions, where the bridge
   continues posting tag snapshots every 200ms.

### 5.4 Multimodal Correlation

The `video_clips` table includes an optional `incident_id` foreign key. This enables a future
query path where a dashboard can show: for incident #47 (conveyor jam at 14:32), here is the
video clip from the factory floor camera covering that time window. The relational link between
telemetry-derived incidents and video evidence is the structural foundation for multimodal
correlation — connecting what the instruments reported with what the camera saw.

### 5.5 Live Observability

Matrix serves two embedded HMI dashboards as inline HTML responses — no static file server, no
build step, no frontend framework. The main dashboard at `/` polls `GET /api/tags?limit=1` and
`GET /api/incidents?limit=10` every 2 seconds, rendering live tag values with color-coded fault
thresholds and a clickable incident list that expands to show the Cosmos R2 insight. The video
log at `/video` polls `GET /api/video/clips` every 5 seconds with score-based ranking and
expandable key event timelines.

These dashboards exist because Matrix is an HTTP server that already knows all the data. Adding
a dashboard is adding two GET handlers that return HTML strings — not deploying a separate
frontend application.

### 5.6 Audit Trail

Every tag snapshot, incident, and insight is persisted with an ISO-8601 timestamp. The
`trigger_tag_id` on each incident links back to the exact tag snapshot that triggered it. The
`tags_json` field preserves the full payload at detection time. The `cosmos_insights` table
records the model identifier, confidence score, and full reasoning trace for every AI analysis.
This creates a complete audit chain: from the PLC register values that caused the fault, through
the detection event, to the AI's structured diagnosis and recommended actions.

---

## 6. Consumer Ecosystem

Every component in the FactoryLM Cosmos Cookoff entry communicates exclusively through Matrix.
The following table maps each consumer to the endpoints it calls and its role in the system.

| File | Endpoints Called | Direction | Purpose |
|------|-----------------|-----------|---------|
| `sim/factoryio_bridge.py` | `POST /api/tags` | Write | PLC tag ingestion at 2-5 Hz via Modbus TCP |
| `cosmos/watcher.py` | `GET /api/incidents`, `POST /api/insights` | Read + Write | Poll for open incidents, post Cosmos R2 analysis |
| `cosmos/agent.py` | `GET /api/tags` | Read | Fetch tag history for trend context injection |
| `video/ingester.py` | `POST /api/video/clips` | Write | Register chunked video clips |
| `video/cosmos_analyzer.py` | `GET /api/video/clips`, `POST /api/video/analyses`, `PATCH /api/video/clips/{id}` | Read + Write | Analyze pending clips, store results, promote highlights |
| `video/highlight_selector.py` | `GET /api/video/clips`, `GET /api/video/analyses` | Read | Query and rank highlight clips |
| `video/short_builder.py` | `GET /api/video/clips/{id}` | Read | Fetch clip file paths for video assembly |
| `services/matrix/demo_ui.py` | `GET /api/tags` | Read | Fault diagnosis dashboard (proxies Matrix tags) |
| Embedded HMI `/` | `GET /api/tags`, `GET /api/incidents`, `GET /api/incidents/{id}` | Read | Live tag display + incident drill-down |
| Embedded HMI `/video` | `GET /api/video/clips`, `GET /api/video/analyses` | Read | Video clip log with scores and captions |

All consumers discover Matrix through a single configuration value: `matrix_url` in their
respective YAML config files (`config/factoryio.yaml`, `config/cosmos.yaml`) or the
`MATRIX_URL` environment variable. Changing the Matrix deployment location requires updating
one value — not rewiring inter-component connections.

---

## 7. Production Path

### 7.1 SQLite to TimescaleDB

Matrix is built on SQLite for demo portability. The production migration path replaces SQLite
with TimescaleDB, a PostgreSQL extension optimized for time-series workloads:

| Capability | SQLite (current) | TimescaleDB (production) |
|-----------|------------------|--------------------------|
| Tag ingestion rate | ~50 writes/sec (WAL mode) | 100K+ writes/sec (hypertables) |
| Time-range queries | Full table scan with WHERE | Automatic chunk exclusion |
| Retention policy | Manual DELETE | Continuous aggregates + drop_chunks |
| Concurrent writers | Single writer (WAL) | Full MVCC concurrency |
| Downsampling | Application-level | Built-in continuous aggregates |

The critical point: **the API contract stays identical.** `GET /api/tags?seconds=60` returns
the same JSON whether the backend is SQLite or TimescaleDB. Every consumer continues to work
without modification. The migration is a storage engine swap behind a stable REST interface.

### 7.2 Horizontal Scaling

Matrix's stateless REST design supports horizontal scaling through standard patterns:

- **Read replicas.** Multiple Matrix instances can serve read traffic from TimescaleDB read
  replicas. Write traffic routes to a single primary.
- **Load balancing.** An nginx or HAProxy frontend distributes requests across Matrix instances.
  No sticky sessions required — every request is independent.
- **Partitioned writes.** High-frequency tag ingestion can be partitioned by `node_id` across
  dedicated writer instances, each targeting a separate hypertable partition.

---

## 8. Reproducibility

Matrix requires no proprietary dependencies and no specialized infrastructure:

| Component | Implementation | Version |
|-----------|---------------|---------|
| API framework | FastAPI | 0.100+ |
| Database | SQLite (stdlib) | Python 3.11+ built-in |
| Data validation | Pydantic | v2 (via FastAPI) |
| HTTP server | uvicorn | 0.24+ |
| CORS | FastAPI CORSMiddleware | built-in |

**Starting Matrix:**

```bash
# From repository root
uvicorn services.matrix.app:app --host 0.0.0.0 --port 8000 --reload
```

The database file (`matrix.db`) is created automatically on first startup. No schema migrations,
no seed data, no configuration files required. All consumers connect via `MATRIX_URL`
environment variable or their respective YAML configs.

**Verifying the API:**

```bash
# Health check
curl http://localhost:8000/api/health

# Post a tag snapshot
curl -X POST http://localhost:8000/api/tags \
  -H "Content-Type: application/json" \
  -d '{"timestamp": "2026-02-21T12:00:00Z", "node_id": "test",
       "motor_running": true, "fault_alarm": true, "error_code": 3,
       "error_message": "Conveyor jam"}'

# Check auto-created incident
curl http://localhost:8000/api/incidents?status=open

# Query tag history (last 60 seconds)
curl http://localhost:8000/api/tags?seconds=60
```

---

## References

1. FactoryLM Vision Whitepaper — NVIDIA Cosmos Cookoff 2026 entry.
   `cookoff/WHITEPAPER.md`

2. FastAPI — Modern, fast web framework for building APIs with Python 3.7+.
   https://fastapi.tiangolo.com

3. SQLite — Self-contained, serverless SQL database engine.
   https://sqlite.org

4. TimescaleDB — Time-series database built on PostgreSQL.
   https://www.timescale.com

5. NVIDIA Cosmos Reason2-8B — Physical world reasoning model.
   https://huggingface.co/nvidia/Cosmos-Reason2-8B

---

## Appendix: File Reference

| File | Purpose |
|------|---------|
| `services/matrix/app.py` | Matrix API — all endpoints, schemas, auto-incident logic, embedded dashboards |
| `services/matrix/demo_ui.py` | Fault diagnosis dashboard — proxies Matrix tags, runs rule engine + Cosmos R2 |
| `sim/factoryio_bridge.py` | PLC bridge — Modbus TCP reader, posts tag snapshots to Matrix at 2-5 Hz |
| `cosmos/watcher.py` | Incident watcher — polls for open incidents, triggers Cosmos R2 analysis |
| `cosmos/agent.py` | Cosmos agent — fetches tag history from Matrix, sends context to R2 |
| `cosmos/client.py` | Cosmos R2 API client — NVIDIA API integration with Llama fallback |
| `video/ingester.py` | Video ingester — chunks recordings, registers clips in Matrix |
| `video/cosmos_analyzer.py` | Video analyzer — sends pending clips to R2, stores analyses |
| `video/highlight_selector.py` | Highlight selector — ranks analyzed clips by score |
| `video/short_builder.py` | Short builder — concatenates highlight clips into demo videos |
| `config/cosmos.yaml` | Cosmos R2 configuration — model, API URL, matrix_url, tag history window |
| `config/factoryio.yaml` | Factory I/O bridge configuration — Modbus addresses, matrix_url, poll interval |

---

*FactoryLM Matrix API — NVIDIA Cosmos Cookoff 2026*
*Repository: https://github.com/Mikecranesync/factorylm*
*Date: February 2026*
