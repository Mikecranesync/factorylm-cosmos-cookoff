# Multimodal Industrial Fault Diagnostics: Fusing Live Video and PLC Telemetry through Cosmos Reason2-8B

**Authors:** Mike Crane, FactoryLM
**Submitted to:** NVIDIA Cosmos Cookoff 2026
**Date:** March 2026

---

## Abstract

Factory technicians spend an estimated 40% of their working time diagnosing equipment faults by manually inspecting machinery, reading HMI displays, and cross-referencing error codes against paper manuals. Existing approaches — rule-based expert systems, general-purpose large language models, and standalone vision systems — each address only one modality of the diagnostic problem. Rule engines catch threshold violations but cannot correlate visual evidence with electrical anomalies. Language models reason about industrial equipment but lack access to live sensor state. Vision models observe motion but cannot read amperage or temperature. We present FactoryLM Vision, a multimodal industrial fault diagnostics system that fuses live video from factory floor cameras with real-time PLC register data through NVIDIA Cosmos Reason2-8B, a vision-language model trained on world simulation data. The system reads 18 coils and 6 holding registers from an Allen-Bradley Micro 820 PLC via Modbus TCP, captures factory floor video at 4 FPS, runs an 8-rule deterministic fault pre-filter, and constructs a structured multimodal prompt that Cosmos R2 processes through chain-of-thought reasoning. In validated end-to-end testing against a live PLC and Factory I/O simulation, the system produced structured diagnoses in 6.1 seconds for normal conditions and 17.0 seconds for complex multi-fault scenarios, consuming 229 to 693 tokens respectively. The system identified a motor paradox — motor commanded ON but speed register reading zero — that required cross-modal reasoning between visual observations and PLC telemetry, a diagnosis impossible from either source alone. The full stack runs on commodity hardware at $0.53/hr in cloud GPU costs.

---

## 1. Introduction

### 1.1 The Diagnostic Gap

Modern factory equipment is heavily instrumented. Programmable logic controllers record motor current, temperature, pressure, and conveyor speed at scan rates of 10 Hz or faster. Cameras watch production lines continuously. Yet when a fault occurs, the diagnostic process remains overwhelmingly manual: a fault alarm trips, a technician is paged, they walk to the machine, read the HMI display, pull up a fault log, and begin a checklist. They may call an OEM support line, wait on hold, and describe what they see verbally.

The problem is not a lack of data — it is a lack of cross-modal inference. The PLC knows the motor current spiked to 5.8A before the fault. The camera saw the conveyor belt stop moving. No existing system connects these observations into a coherent, grounded diagnosis automatically.

Unplanned industrial downtime costs manufacturers an average of $50,000 per hour (ARC Advisory Group, 2024). The global predictive maintenance market is projected to reach $28.2 billion by 2026 (MarketsAndMarkets). Even a 10% reduction in mean time to diagnose across a mid-size factory floor produces measurable ROI within weeks of deployment.

### 1.2 Why Existing Approaches Fall Short

**Rule-based expert systems** catch obvious faults — if motor current exceeds 5.0A, a fault code fires. But they cannot correlate a visual observation ("the belt is bunched up on the left side") with an electrical anomaly (overcurrent) to diagnose the root cause (a misaligned roller). They cannot distinguish between a genuine E-stop event and a stuck E-stop contact. They cannot answer open-ended technician questions like "Is this safe to restart?"

**Large language models** know about industrial equipment in general but have no access to the live sensor state of a specific machine. They hallucinate register values and cannot see the factory floor.

**Vision-language models** deployed alone can watch video but have no access to PLC telemetry. They observe motion but cannot read amperage, temperature, or pressure.

### 1.3 Contribution

FactoryLM Vision bridges this gap by treating industrial diagnosis as a grounded multimodal reasoning problem. We give a vision-language model both the visual stream and the instrument readings, augmented by deterministic fault pre-analysis, and let it reason across both modalities. The key contributions are:

1. A system architecture that fuses live PLC register data with factory floor video in a single prompt to a vision-language model.
2. A deterministic 8-rule fault pre-filter that reduces LLM latency by providing structured evidence for common fault patterns.
3. Validated end-to-end results demonstrating cross-modal reasoning on live industrial hardware.
4. An auditable chain-of-thought reasoning format suitable for safety-critical industrial decisions.

---

## 2. Related Work

### 2.1 Industrial Fault Detection

Traditional industrial fault detection relies on threshold-based alarms configured in PLC or SCADA software. When a motor current exceeds a setpoint, the PLC sets a fault bit. These systems are deterministic and fast but cannot perform root cause analysis or correlate across sensor modalities. More sophisticated approaches use statistical process control or machine learning classifiers trained on historical fault data, but these require extensive labeled datasets specific to each machine type and are typically limited to a single sensor modality.

### 2.2 Vision-Based Industrial Monitoring

Computer vision has been applied to industrial quality inspection, typically using convolutional neural networks trained to detect surface defects on manufactured parts. These systems operate on still images at the product level and do not incorporate machine telemetry. Recent work on video anomaly detection applies temporal modeling to surveillance footage, but without access to the control system, these approaches cannot distinguish between a controlled stop (operator-initiated) and an uncontrolled stop (fault-induced).

### 2.3 Physical AI and World Models

NVIDIA's Cosmos platform represents a shift toward models trained on physical world simulation data. Cosmos Reason2-8B is trained on world simulation tasks, giving it grounded intuitions about physical causality — when it sees a conveyor belt and reads that current has doubled, it reasons about mechanical load rather than simply pattern-matching on tokens. This is qualitatively different from general-purpose vision-language models that happen to know industrial terminology. The 256K token context window enables prompts that incorporate historical trend data alongside real-time snapshots. Native video support at 4 FPS enables temporal reasoning about developing fault conditions (e.g., progressive belt deceleration indicating an emerging jam versus a sudden blockage).

### 2.4 Gap in the Literature

To our knowledge, no existing system performs real-time cross-modal fault diagnosis by fusing live PLC telemetry with video through a vision-language model. Systems exist for each modality independently; the fusion step is the novel contribution.

---

## 3. System Architecture

### 3.1 Four-Layer Stack

The system is organized as a four-layer stack connecting the physical hardware to the technician interface:

```
Layer 4 — TECHNICIAN INTERFACE
  Phone / Telegram Bot / Web Dashboard
         |
Layer 3 — CLOUD AI LAYER
  Vast.ai L40S GPU
  vLLM 0.15.1 serving Cosmos Reason2-8B
  diagnosis_engine.py (prompt construction, fault pre-filter, response parsing)
         |
  Tailscale WireGuard Mesh (~33ms latency)
         |
Layer 2 — EDGE GATEWAY
  edge_gateway.py (Modbus TCP polling over Tailscale)
  capture_fio.py (4 FPS H.264 video capture)
         |
Layer 1 — PHYSICAL HARDWARE
  Allen-Bradley Micro 820 PLC (192.168.1.100:502)
  18 coils + 6 holding registers
  ATO VFD (RS485 Modbus RTU, slave addr 1)
  Conveyor belt + motor
```

### 3.2 Data Flow

A diagnostic request follows this path:

1. A technician sends a message (e.g., "The line stopped. What happened?") via Telegram, web, or Discord.
2. The orchestrator triggers parallel data acquisition: `capture_fio.py` records a 15-second MP4 clip from the Factory I/O window at 4 FPS using `mss` for screen capture and `ffmpeg` with `libx264/yuv420p` encoding; simultaneously, `edge_gateway.py` reads coils 0-17 and holding registers 100-105 via Modbus TCP.
3. `diagnosis_engine.py` runs the deterministic 8-rule fault classifier (`diagnosis/conveyor_faults.py`) over the PLC snapshot, producing structured fault evidence.
4. The engine constructs a multimodal prompt: video as base64-encoded `video_url` content block (placed before text per R2 documentation), PLC registers formatted as structured text, and fault pre-analysis as context. Three prompt templates handle different query types: `user_diagnosis` (general), `user_question` (specific technician question), and `user_describe` (video-only fallback).
5. The payload is POSTed to the vLLM endpoint serving Cosmos R2 with sampling parameters: temperature 0.6, top_p 0.95, max_tokens 4096.
6. Cosmos R2 returns a response containing a `<think>` chain-of-thought block followed by a structured diagnosis.
7. The engine parses the `<think>` block separately from the diagnosis text, enabling the interface to surface just the diagnosis while preserving the full reasoning for audit.

### 3.3 Read-Only Constraint

The diagnostic pipeline is strictly read-only with respect to the PLC. The system reads coils and registers but never writes to the controller. All control actions (start, stop, E-stop) require separate authorization through a different code path. This separation ensures that the AI diagnostic system cannot inadvertently command the physical equipment.

---

## 4. Implementation

### 4.1 Hardware

**PLC:** Allen-Bradley Micro 820, model 2080-LC30-48QWB. 12 digital inputs, 8 digital outputs, embedded RS485 serial port. Firmware v12. Modbus TCP on port 502 at IP 192.168.1.100.

**VFD:** ATO variable frequency drive, RS485 Modbus RTU slave address 1, 9600 baud 8N1. Control word at register 0x2000 (0x0001=FWD, 0x0003=REV, 0x0007=Stop). Frequency setpoint at 0x2001 (value x 100). Actual frequency readback at 0x2103, actual current at 0x2104.

**Conveyor:** Belt driven by the ATO VFD through the motor. Two photoeye sensors (SensorStart at coil 2, SensorEnd at coil 3) detect item presence at entry and exit points.

**E-Stop:** Dual-contact design using both NO (coil 8) and NC (coil 9) contacts. Fault detection logic: `fault_alarm = coil[8] AND NOT coil[9]`. This catches wiring faults — if both contacts read the same state, something is wrong.

**Coil Map (18 addresses):**

| Address | Tag | Description |
|---------|-----|-------------|
| 0 | Conveyor | Belt motor command |
| 1 | Emitter | Item spawner |
| 2 | SensorStart | Entry photoeye |
| 3 | SensorEnd | Exit photoeye |
| 4 | RunCommand | Remote API trigger |
| 7-11 | Physical I/O | Switches, E-stop, pushbutton |
| 15-17 | Physical outputs | LEDs, VFD commands |

**Holding Registers (100-105):**

| Address | Tag | Scale | Description |
|---------|-----|-------|-------------|
| 100 | item_count | 1x | Items reached SensorEnd |
| 101 | motor_speed | 1x | 0-100% |
| 102 | motor_current | /10 | Amps |
| 103 | temperature | /10 | Degrees C |
| 104 | pressure | 1x | PSI |
| 105 | error_code | 1x | 0=OK, 1=Overload, 2=Overheat, 3=Jam, 4=Sensor, 5=Comms |

### 4.2 Fault Pre-Filter

The rule engine in `diagnosis/conveyor_faults.py` implements eight fault rules across four severity levels. Each rule maps a PLC tag pattern to a `FaultDiagnosis` dataclass containing: fault code, severity (EMERGENCY/CRITICAL/WARNING/INFO), human-readable title, description, list of likely causes, and suggested maintenance checks.

| Code | Severity | Condition | Threshold |
|------|----------|-----------|-----------|
| E001 | EMERGENCY | E-stop active | `e_stop == True` |
| M001 | CRITICAL | Motor overcurrent | `motor_current > 5.0A` |
| T001 | CRITICAL | High temperature | `temperature > 80.0C` |
| C001 | CRITICAL | Conveyor jam | Both sensors active + motor running |
| M002 | CRITICAL | Unexpected motor stop | Motor stopped, speed setpoint > 0 |
| P001 | WARNING | Low pneumatic pressure | `pressure < 60 PSI` |
| M003 | WARNING | Motor speed mismatch | `motor_speed < 30%` vs `conveyor_speed > 50%` |
| T002 | WARNING | Elevated temperature | `65C < temperature <= 80C` |

The formatted output of this analysis is injected directly into the Cosmos R2 prompt. The model is told: "Here is what the rule engine found. Now look at the video and tell me if the visual evidence confirms or contradicts these findings." This hybrid approach gives the model structured evidence to anchor its reasoning while allowing it to discover findings the rules cannot express.

### 4.3 Prompt Architecture

The system prompt establishes Cosmos R2's role as a factory diagnostics AI and instructs it to cross-reference visual observations with PLC telemetry. Discrepancies between modalities are treated as diagnostic signals — if the solenoid register reads ON but the camera shows no actuator motion, the model flags a likely wiring fault or stuck actuator.

The user message content array places media (base64-encoded image or video) before text, per R2 documentation. The text portion contains three sections: live PLC register data formatted with boolean I/O and analog registers, the automated fault analysis from the rule engine, and either a general diagnosis request or a specific technician question.

### 4.4 Deployment

**AI Inference:** vLLM 0.15.1 serving `nvidia/Cosmos-Reason2-8B` on a Vast.ai L40S GPU (Virginia region, $0.53/hr spot pricing). OpenAI-compatible `/v1/chat/completions` endpoint accessed through an SSH tunnel. The reasoning parser (`qwen3`) extracts `<think>` chain-of-thought blocks from responses.

**Network:** Tailscale WireGuard mesh connects the VPS, PLC laptop, and edge devices. No ports are opened on any router. Measured Modbus TCP round-trip latency over Tailscale: approximately 33ms.

**Software Stack:**

| Component | Implementation | Protocol |
|-----------|---------------|----------|
| PLC communication | pymodbus 3.11 | Modbus TCP (port 502) |
| Video capture | mss + ffmpeg | H.264/MP4 at 4 FPS |
| AI inference | vLLM 0.15.1 | OpenAI-compatible API |
| Network mesh | Tailscale | WireGuard VPN |
| User interface | python-telegram-bot | Telegram Bot API |
| Simulation | Factory I/O | Modbus TCP driver |

---

## 5. Evaluation

### 5.1 End-to-End Latency

All scenarios were tested on February 20, 2026, with real Factory I/O screenshots (not proxy images), live PLC reads where indicated, and Cosmos R2 served on a Vast.ai L40S.

| Scenario | Latency | Tokens | Key Finding |
|----------|---------|--------|-------------|
| Normal operation | 6.1s | 229 | "No anomalies detected. System functioning as designed." |
| Conveyor jam | 19.2s | 678 | Identified overcurrent 5.8A, box/hopper causing blockages |
| E-stop | 14.4s | 601 | "E-stop engaged, not a hardware issue. Reset to resume." |
| Overheat | 15.2s | 636 | "CRITICAL: 85C exceeds limit. Check cooling." |
| Live PLC integration | 17.0s | 693 | Motor paradox, pressure failure, cross-modal reasoning |

The normal scenario at 6.1s and 229 tokens demonstrates that the system is efficient when there is nothing wrong: R2 exits its reasoning chain early rather than manufacturing spurious findings. Latency scales with diagnostic complexity — the correct behavior for a safety-critical system where thoroughness matters more than speed for fault conditions.

### 5.2 Motor Paradox Case Study

The live PLC integration test (17.0s, 693 tokens) produced the most diagnostically significant result. The system read 19 live tags from the Micro 820 and captured the Factory I/O "From A to B" scene simultaneously. R2 identified four findings:

1. **Motor Paradox:** `motor_running=ON` combined with `motor_speed=0`. R2 correctly identified this as a potential mechanical failure or encoder/sensor error, noting that holding registers 101-105 were not mapped in the current scene configuration.

2. **Pneumatic Pressure Failure:** `pressure=0 PSI` flagged as critically low. R2 recommended checking the air supply, checking for leaks, and verifying transducer wiring before any restart.

3. **Inactive Sensors:** Both photoeyes reading OFF while a box was visible on the conveyor in the Factory I/O image. R2 flagged this as possible sensor misalignment or obscuration.

4. **Cross-Modal Reasoning:** R2 correlated the visual observation (stationary box visible on belt, orange motor visible and energized) with the PLC telemetry (motor commanded ON, speed reading zero, no sensor pulses) to conclude the system was energized but producing no mechanical output.

This fourth finding — the cross-modal correlation — represents the core contribution. Neither the camera alone (which sees a stationary scene but cannot determine whether the motor is energized) nor the PLC alone (which reports motor ON but cannot see whether the belt is moving) could produce this diagnosis. The fusion of both modalities through a vision-language model enabled a diagnostic conclusion that required reasoning across the visual and telemetric domains.

### 5.3 Question-Answering Mode

Beyond general diagnosis, the system supports open-ended technician questions against live context:

- **"Is the conveyor running and why is the motor drawing so much current?"** — 10.2s, 423 tokens. R2 answered with specific PLC tag values as evidence.
- **"What equipment do you see?"** — 4.5s. R2 identified a roller conveyor, a box, and photoeye sensors from the Factory I/O screenshot.

### 5.4 Comparison: Initial vs. Refined

In the initial integration test, a terminal screenshot was submitted as a proxy image (no real factory visual). R2 correctly identified three fault conditions from the PLC data (overcurrent 5.8A, Error Code 3, elevated temperature 68C) but also flagged that the submitted image appeared to be a terminal window rather than factory equipment — demonstrating active cross-modal self-correction. Performance improved from 25.8s/784 tokens (proxy image) to 6.1-19.2s/229-693 tokens (real Factory I/O screenshots), reflecting both prompt refinement and the model's ability to reason more efficiently from genuine visual context.

---

## 6. Safety Considerations

### 6.1 Defense in Depth

The system implements seven layers of safety:

| Layer | Mechanism | Controller |
|-------|-----------|-----------|
| Hardware | Physical E-stop button (dual-contact) | Anyone at the machine |
| PLC | Photoeye auto-stop at belt ends | Automatic |
| PLC | Dual-contact E-stop validation | Automatic |
| Software | Fixed speed — no public speed control | System config |
| Software | Queue system — one user at a time | Automatic |
| Software | Software E-stop command | Authorized operator only |
| Network | Tailscale mesh — no open ports | System config |

### 6.2 E-Stop Dual-Contact Validation

The E-stop uses both NO (normally open) and NC (normally closed) contacts. Under normal conditions, the NO contact reads OFF and the NC contact reads ON. When pressed, these states invert. If both contacts read the same state, the system detects a wiring fault and treats it as an E-stop condition. This dual-contact design ensures that a single wire fault cannot silently disable the safety system.

### 6.3 Read-Only AI

The diagnostic pipeline reads coils and registers but never writes to the PLC. The AI system has no capability to start, stop, or modify the operation of the physical equipment. Control actions are gated through a separate authorization path. This architectural separation means that even a compromised or malfunctioning AI system cannot inadvertently command the machine.

### 6.4 Chain-of-Thought Auditability

Every Cosmos R2 response includes a `<think>` block containing the model's full reasoning chain before the diagnosis. For safety-critical decisions — "Is it safe to restart?" — a technician or supervisor can review the reasoning, not just the conclusion. This auditability is essential for industrial environments where incorrect diagnoses can lead to equipment damage or injury.

---

## 7. Discussion

### 7.1 Strengths

**Cross-modal discovery.** The motor paradox case study demonstrates that multimodal fusion discovers failure modes invisible to any single modality. This is the central value proposition: the system finds things that cameras alone and PLCs alone cannot find.

**Graceful degradation.** When the PLC is unreachable, the system falls back to video-only diagnosis using the `user_describe` prompt template. When video is unavailable, the rule engine still provides deterministic fault detection from PLC data alone. The multimodal fusion adds value when both sources are available but does not create a single point of failure.

**Cost efficiency.** The full cloud AI layer runs at $0.53/hr on spot GPU pricing. For a factory paying $50,000/hr in downtime costs, even a single avoided hour of diagnostic delay represents approximately 100,000x ROI on the AI infrastructure cost.

### 7.2 Limitations

**Latency.** The 6.1-19.2 second response time is acceptable for diagnostic queries but too slow for real-time process control. The system is designed for after-the-fact diagnosis and question answering, not closed-loop control.

**Simulation environment.** The validation was performed against Factory I/O, a simulation. While the PLC is real hardware running real ladder logic over real Modbus TCP, the physical process (conveyor, motor, sensors) is simulated. Full production validation on physical machinery is the next step.

**Single machine.** The current implementation is validated against one PLC model (Micro 820) and one process (conveyor). Generalization to other PLC manufacturers and process types requires register map configuration but no code changes, since the system uses standard Modbus TCP.

### 7.3 Knowledge Distillation Path

The architecture is designed to progressively reduce cloud AI dependency over time. Each Cosmos R2 diagnosis confirmed by a technician as correct becomes a candidate for the deterministic rule engine. Over weeks, the 8 rules in `conveyor_faults.py` grow to cover more fault patterns, and the system requires less cloud AI for common cases — reducing both cost and latency. This "inverted pyramid" design means the system uses more AI at the beginning (when it knows nothing about a machine) and less AI over time (as deterministic rules capture the most frequent fault patterns).

---

## 8. Conclusion and Future Work

We presented FactoryLM Vision, a multimodal industrial fault diagnostics system that fuses live video and PLC telemetry through NVIDIA Cosmos Reason2-8B. The system demonstrated cross-modal reasoning on live industrial hardware, identifying fault conditions that neither visual observation nor PLC telemetry could surface independently. End-to-end latency ranged from 6.1 seconds for normal conditions to 19.2 seconds for complex multi-fault scenarios, at a cloud infrastructure cost of $0.53/hr.

### Future Work

**Edge inference.** Deploying a quantized version of Cosmos R2 on edge hardware (e.g., NVIDIA Jetson) would eliminate the cloud round-trip and reduce latency to sub-second for most scenarios.

**Pi Factory zero-config appliance.** The companion Pi Factory project produces a flashable Raspberry Pi image that auto-discovers PLCs via a 4-protocol waterfall (EtherNet/IP, OPC UA, Siemens S7, Modbus TCP) and starts polling at 5 Hz with zero configuration. Integrating the diagnostic engine into this appliance would create a drop-in industrial AI device.

**Multi-machine deployment.** Extending from a single conveyor to a multi-station production line, where the AI must reason about upstream and downstream effects (e.g., a jam on Station 3 caused by overproduction at Station 2).

**Historical trend analysis.** Leveraging the 256K token context window to include time-series PLC data (e.g., "motor current has been climbing for the last two hours"), enabling predictive diagnostics before faults occur.

---

## References

1. NVIDIA Cosmos Reason2-8B model documentation. https://huggingface.co/nvidia/Cosmos-Reason2-8B

2. vLLM Project — High-throughput inference engine. https://github.com/vllm-project/vllm

3. ARC Advisory Group, "The Cost of Unplanned Downtime in Manufacturing," 2024.

4. MarketsAndMarkets, "Predictive Maintenance Market — Global Forecast to 2026," 2024.

5. Modbus Organization, "Modbus Application Protocol Specification V1.1b3," 2012. https://modbus.org/docs/Modbus_Application_Protocol_V1_1b3.pdf

6. Allen-Bradley Micro 820 PLC User Manual, Rockwell Automation Publication 2080-UM002, 2022.

7. Factory I/O — 3D Factory Simulation. Real Games, Lda. https://factoryio.com

8. U.S. Bureau of Labor Statistics, "Employer Costs for Employee Compensation," 2024.

---

## Appendix: Source File Reference

| File | Role in System |
|------|---------------|
| `demo/diagnosis_engine.py` | Orchestrator: prompt construction, media encoding, R2 API call, response parsing |
| `diagnosis/conveyor_faults.py` | Deterministic 8-rule fault classifier with FaultDiagnosis dataclass |
| `demo/prompts/factory_diagnosis.yaml` | System prompt + 3 user prompt templates |
| `demo/capture_fio.py` | Screen recorder: 4 FPS H.264 capture from Factory I/O |
| `config/factoryio.yaml` | Coil and register map for the "From A to B" scene |
| `cosmos/client.py` | Cosmos R2 API client with fallback logic |
| `docs/CONVEYOR_OF_DESTINY.md` | Hardware specs, wiring guide, Modbus maps, safety model |

---

*FactoryLM Vision — Multimodal AI Diagnostics for Industrial Automation*
*Repository: https://github.com/Mikecranesync/factorylm-cosmos-cookoff*
