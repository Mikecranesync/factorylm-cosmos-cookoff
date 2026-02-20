# FactoryLM Vision — Demo Video Script (2:55)

## COLD OPEN — The Problem [0:00–0:20]

**[SCREEN: Factory I/O "From A to B" scene running normally]**

> "Factory technicians spend 40% of their time diagnosing equipment faults. They walk to the machine, read the HMI, flip through a manual, maybe call the OEM and wait on hold. The data to solve the problem already exists — in the PLC registers, in the camera feeds. Nobody's connected them."

---

## THE PITCH — One Sentence [0:20–0:30]

**[SCREEN: Cut to phone showing Telegram chat with Clawdbot]**

> "FactoryLM Vision lets a technician text their factory from their phone — and the AI tells them what's wrong. In seventeen seconds."

---

## ARCHITECTURE — How It Works [0:30–0:55]

**[SCREEN: Show the architecture diagram from the README, or a clean slide version]**

> "Here's how it works. A technician sends a question to a Telegram bot. The system captures a live frame from the factory floor and reads the PLC registers over Modbus TCP — that's a real Allen-Bradley Micro 820. Both get packed into a multimodal prompt and sent to NVIDIA Cosmos Reason2-8B, self-hosted on an L40S GPU via vLLM. The model reasons across *both* modalities and returns a structured diagnosis."

---

## LIVE DEMO — Normal State [0:55–1:15]

**[SCREEN: Factory I/O running, conveyor moving boxes normally]**

> "Let me show you. Here's our conveyor running normally in Factory I/O, connected to the Micro 820 over Modbus TCP."

**[SCREEN: Run `test_session.py` with the `normal` scenario — show the terminal output]**

> "We ask: 'What's the status?' Six seconds later — 'No anomalies detected. System functioning as designed.' It doesn't manufacture problems when there aren't any."

---

## LIVE DEMO — Jam Fault [1:15–1:55]

**[SCREEN: Factory I/O scene with a jammed conveyor — box stuck, belt stopped]**

> "Now let's break something. I've triggered a conveyor jam. The motor's drawing 5.8 amps — that's 16% over the safe limit. Error code 3, both photoeyes blocked."

**[SCREEN: Run diagnosis with `jam` scenario — show the terminal output streaming in]**

> "I ask: 'The line stopped. What happened?' Watch the response."

**[SCREEN: Highlight the key output — overcurrent, jam detected, cross-modal reasoning]**

> "Nineteen seconds. It found the overcurrent, identified the jam from both the PLC data *and* the video, and told the technician exactly what to check first. Neither the camera alone nor the registers alone could have given that full picture."

---

## THE KEY FINDING — Motor Paradox [1:55–2:25]

**[SCREEN: Show the live PLC test output — motor_running: True, motor_speed: 0]**

> "Here's the result that made this real for us. When we connected the live Micro 820, Cosmos found what we call the motor paradox — the PLC says the motor is energized, but the speed register reads zero. The camera shows a stationary box on a belt with an orange motor that looks powered."

> "The model correlated both sources and concluded: the system is energized but producing no mechanical output. That's a diagnosis that's *impossible* from either modality alone. That's the whole point of multimodal fusion."

---

## WHY COSMOS REASON2-8B [2:25–2:40]

**[SCREEN: Slide — Cosmos R2 logo + three bullet points]**

> "We chose Cosmos Reason2-8B because it's trained on physical world simulation data — it understands causality, not just tokens. The chain-of-thought reasoning is auditable, which matters when a technician is deciding whether to restart a motor. And the 256K context window lets us include full shift histories, not just snapshots."

---

## RESULTS + CLOSE [2:40–2:55]

**[SCREEN: Results table — 6-19s latency, 19 PLC tags, $0.53/hr GPU cost]**

> "Six to nineteen seconds per diagnosis. Nineteen live PLC tags. Fifty-three cents an hour in GPU cost. Real hardware, real PLC, real model."

> "Factory technicians shouldn't have to be detectives. FactoryLM Vision lets them just ask."

**[SCREEN: GitHub URL + FactoryLM logo]**

> "FactoryLM Vision. Open source. Link in the description."

---

## Recording Tips

- **Screen record** Factory I/O + terminal side-by-side using OBS or similar
- **Voiceover** can be recorded separately and layered on top — easier to get clean audio
- For the Telegram shot, just show a real conversation on your phone (screenshot or screen record)
- The `test_session.py` terminal output is the most compelling visual — let it stream in real-time, don't cut it short
- Total target: **2:50–2:55** to leave a few seconds of buffer under the 3-minute limit
