# Backend cache and concurrency optimization benchmark

Baseline: `53014f6`. Measured on the same Windows host and Python virtual environment on 2026-11-14.

Five separate baseline/optimized process pairs were measured, alternating their execution order. Each process measured exactly 100 `advance_telemetry()` calls and 50 cold `POST /api/diagnose` calls. The table reports the median of the five per-run means or p95s; all raw runs are in [backend_latency_benchmark.json](backend_latency_benchmark.json). A positive percentage means lower time.

| Workload per run | Metric | Before (ms) | After (ms) | Reduction |
| --- | --- | ---: | ---: | ---: |
| 100 telemetry ticks | Mean wall latency | 1.331631 | 0.855089 | +35.79% |
| 100 telemetry ticks | p95 wall latency | 2.631500 | 1.935300 | +26.46% |
| 100 telemetry ticks | Mean process CPU time | 1.406250 | 0.781250 | +44.44% |
| 50 cold ASGI diagnosis calls | Mean wall latency | 2.809826 | 2.795258 | +0.52% |
| 50 cold ASGI diagnosis calls | p95 wall latency | 3.791000 | 3.727800 | +1.67% |
| 50 cold ASGI diagnosis calls | Mean process CPU time | 2.500000 | 2.812500 | -12.50% |

Tick latency improved consistently. Cold-request wall latency is effectively unchanged within observed run-to-run variation. Cold-request CPU time did not improve in these samples. Windows process CPU timing has coarse resolution; these local measurements are not production throughput guarantees.

## Method

- Run `python -m backend.benchmark_latency --output scratch/latency.json` from each version, using the identical benchmark module. For the baseline, execute that module with the working directory/import path set to the clean `53014f6` checkout.
- Startup, knowledge loading, and external network I/O are excluded. The scenario noise seed is 1729. Weather uses the deterministic local fallback.
- The 100 ticks cover hypercapnia, radiation, heat strain, recovery, and return to nominal. Diagnosis requests rotate the four existing documented presets.
- Diagnosis requests use httpx's in-process ASGI transport, exercising request validation, routing, clinical evaluation, and response serialization. TCP/network latency is excluded.
- Clear diagnosis, evidence, and treatment-option runtime caches before every cold request. Static indices and startup-parsed medication data remain loaded.
- All normalized clinical JSON output hashes match across all ten processes. Only timestamp, execution/retrieval/pipeline timing, and cache-hit instrumentation are excluded from those hashes. The raw report includes both workload hashes.

## Changes verified

- Diagnosis responses are deeply isolated on cache storage and cache hits. Bounded LRU eviction preserves the most recent 256 entries.
- Medication parsing and canonical-name patterns are prepared at startup/reload. Treatment names are memoized by condition and current blocked-medication policy; returned collections are isolated.
- Document-type indices preserve retrieval scores and deterministic result order. Repeated Mode A evidence lookups use a bounded LRU of immutable tuples.
- Knowledge reloads invalidate all three caches and rebuild medication/vector indices under a reentrant lock.
- Recovery uses copy-on-write for fields it changes, evaluates current safety policy once, and refreshes countermeasures only when the condition, knowledge revision, or lockout policy changes.
- Schedule fallback reuses a stateless detector and shallow packet copy. FastAPI warms the first frame before serving; telemetry JSON serialization is skipped when there are no subscribers.
- Shared simulation operations use a reentrant lock; socket writes and async waits remain outside it. Stdlib diagnosis evaluations also synchronize with the telemetry worker.
- Identity, scenario-label clearing, stateful/stateless semantics, clinical thresholds, reference content, and medication/activity lockouts remain unchanged.

## Verification

- `python -m pytest backend/tests -v`: 84 passed.
- `python "Autonomous agent(dheer)/test_agent.py"`: 13 passed.
- `python -m backend.evaluate_blind_seeds`: 54/54; decision accuracy, Mode A precision, Mode B abstention accuracy, and local citation/formulary validity all 1.0; live replay 30/30.
- `python -m backend.test_demo`: passed.
- Real Uvicorn HTTP/WebSocket checks: startup, documented diagnosis presets, four recovery loops, treatment acceptance/rejection, command acknowledgements, and stdlib JSON validation responses passed.
