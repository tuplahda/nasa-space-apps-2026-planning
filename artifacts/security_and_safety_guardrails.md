# Security, Architecture & NASA Class-A Biotelemetry Guardrails

This document defines the mandatory security, engineering, and safety-critical biotelemetry standards for **A.R.E.S. Med** (*Autonomous Real-time Extraterrestrial Survival & Medical System*).

---

## Part 1: Security & Architecture Guardrails (MANDATORY)

1. **SECRETS:** Never hardcode API keys, passwords, JWT secrets, or connection strings. Always read from environment variables and validate their existence at startup. Never expose secrets to client-side bundles.
2. **AUTHORIZATION:** Every endpoint that accesses or mutates data MUST verify both authentication AND resource ownership (check that the resource belongs to the current user ID extracted from the server-side JWT/session, never from request parameters).
3. **INPUT VALIDATION:** Validate and sanitize all inputs at the API boundary using strict schemas (e.g., Pydantic, DTOs with DataAnnotations/FluentValidation, or Zod). Reject unexpected fields (prevent mass assignment / over-posting).
4. **DATABASE:** Use parameterized queries or ORM methods exclusively. Never concatenate or interpolate user input into SQL or vector search queries.
5. **ERROR HANDLING:** Never return raw stack traces, database error messages, or internal paths to the client. Log detailed errors server-side and return generic, structured problem details (RFC 7807) to the client.
6. **DEPENDENCIES:** Do not introduce new third-party libraries if native language/framework features suffice. Before adding a dependency, state why it is needed.
7. **CORS & HEADERS:** Never use wildcard (`*`) CORS in production configurations. Always configure explicit allowed origins, HTTP-only/Secure cookies, and strict Content-Security-Policy headers.

---

## Part 2: NASA Class-A / Safety-Critical Biotelemetry Guardrails (MANDATORY)

1. **DETERMINISM (JPL POWER OF TEN):**
   - NEVER use direct or indirect recursion.
   - ALL loops must have a hard, statically verifiable upper bound (e.g., `MAX_ITERATIONS`) to prevent runaway execution freezes.
   - For high-frequency biosignals (ECG, $\text{SpO}_2$, EEG), use fixed-size pre-allocated ring buffers. Do not dynamically allocate unbounded arrays in telemetry ingestion handlers.
   - Keep functions under 60 lines of code with a single responsibility.

2. **TELEMETRY INTEGRITY & FAULT TOLERANCE:**
   - Treat all sensor inputs as potentially corrupted by radiation (Single Event Upsets / SEU), noise, or spoofing.
   - Every telemetry packet must validate:
     1. Schema & data types
     2. Cryptographic signature / CRC checksum
     3. Monotonic sequence timestamp
     4. Physiological plausibility bounds
     5. Rate-of-change (slew rate) limits
   - Never reject an out-of-range reading silently; flag it as `SENSOR_FAULT` or `ANOMALY` and log the raw frame separately from validated clinical metrics.

3. **STALE DATA & DEAD-MAN SWITCH:**
   - Never display cached telemetry as "live." Every metric must track `lastUpdatedTimestamp`. If `now - lastUpdatedTimestamp` exceeds the sensor's heartbeat threshold (e.g., `2000ms`), immediately flag the state as `TELEMETRY_STALE`.

4. **ZERO EXTERNAL / CLOUD DEPENDENCIES (AIR-GAPPED OPERATION):**
   - The application must run 100% offline in an isolated spacecraft or ground-control subnet.
   - Never reference external CDNs, Google Fonts, external analytics, or unpinned third-party packages.
   - Note for NASA DONKI API: Use a cached local snapshot / store-and-forward sync buffer so that when Earth comms drop (`COMMS_BLACKOUT`), the system operates seamlessly with zero network calls.

5. **MEDICAL DATA SECURITY & AUDITABILITY:**
   - Enforce strict Role-Based Access Control (RBAC):
     - `ASTRONAUT_SELF`: Full access to own clinical telemetry, symptom logs, and prescribed countermeasures.
     - `FLIGHT_SURGEON`: Full clinical access across crew members, diagnostic overrides, and threshold updates.
     - `BIOMED_ENGINEER (BME)`: Sensor health, CRC/SEU fault logs, calibration, and telemetry pipeline diagnostics.
     - `FLIGHT_DIRECTOR`: High-level readiness/status summary only (`NOMINAL`, `CAUTION`, `WARNING`, `EMERGENCY`)—no raw clinical PII/PHI.
   - Every threshold change, alarm acknowledgement, or manual override must write an immutable, cryptographically signed audit log entry (`who`, `when`, `old_value`, `new_value`, `reason`).

---

## Part 3: Recommended Additional Guardrails for A.R.E.S. Med (AI / Multi-Agent & Clinical Safety)

1. **AI / RAG CLINICAL SAFETY & ANTI-HALLUCINATION ("GROUNDED OR SILENT"):**
   - **Strict Citation Enforcement:** The RAG Medical Assistant must NEVER invent medication dosages, procedures, or diagnoses. Every clinical output must map to a verified `protocol_id` and source citation in the NASA Space Medicine Knowledge Base.
   - **Deterministic Fallback Mode:** If the LLM / RAG inference times out (e.g., exceeds `3000ms`), fails schema validation, or returns a low retrieval confidence score below threshold, the system must automatically fall back to a **Deterministic Rule-Based Protocol Lookup** from [`rag_protocols_8_scenarios.json`](../data/rag_protocols_8_scenarios.json).
   - **Contraindication & Dosage Ceiling Check:** Before displaying any AI-recommended countermeasure (e.g., Acetazolamide, Modafinil, O₂ flow rate), pass the recommendation through a deterministic hard-coded safety filter that verifies upper dosage limits and crew allergy/contraindication flags.

2. **PROMPT INJECTION & AGENT-TO-AGENT ISOLATION:**
   - **Symptom Log Sanitization:** Astronaut free-text symptom logs and voice transcripts are untrusted inputs. Never concatenate raw symptom text directly into system instructions—wrap them in delimited data blocks and strip control tokens so a corrupted or adversarial log cannot hijack the RAG Medical Officer's instructions.
   - **Read-Only Knowledge Base:** The RAG agent and Astronaut agents must have read-only (`SELECT`) access to the NASA medical protocols collection. No agent can mutate clinical reference protocols at runtime.

3. **ALARM FATIGUE & HYSTERESIS (NASA-STD-3001 COMPLIANCE):**
   - **Debounce & Persistence Window:** Do not trigger a clinical alarm on a single transient spike (1 tick). Require $N$-of-$M$ consecutive anomalous samples (e.g., 3 out of 5 seconds) or hysteresis deadbands before escalating state, while immediately logging single-tick spikes as `SEU_CANDIDATE` or `TRANSIENT_NOISE`.
   - **Alarm Priority Hierarchy:** Strictly classify alerts into NASA standard levels (`EMERGENCY - Class 1 Red`, `WARNING - Class 2 Amber`, `CAUTION - Class 3 Yellow`, `ADVISORY - Blue`) so critical life-support events (e.g., Hypercapnia $\text{CO}_2 > 15\text{ mmHg}$) cannot be masked by low-priority advisories.

4. **STORE-AND-FORWARD EARTH SYNC & TIME STANDARDIZATION (MET / UTC):**
   - **Monotonic Mission Elapsed Time (MET) + UTC ISO-8601:** All telemetry packets and audit logs must record both system monotonic tick counters (immune to NTP/clock jumps) and UTC timestamps.
   - **Comms-Blackout Queue:** During the 20-minute Mars one-way radio delay or solar conjunction blackout, queue compressed clinical summaries and signed audit logs in a bounded store-and-forward buffer for deterministic synchronization once Earth link is restored.
