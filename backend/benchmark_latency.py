"""Reproducible CPU/wall benchmarks; excludes startup and external network I/O."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import random
import statistics
import time
from unittest.mock import patch

import httpx

import backend.main as server
import backend.routes.diagnose as routes
from backend.services.anomaly_detector import EdgeAnomalyDetector
from backend.services.astronaut_sim import AstronautSimulationEngine
from backend.services.rag_engine import LocalMedicalRAGEngine


def clinical_digest(value):
    """Hash all outputs except clocks and cache/timing instrumentation."""
    value = json.loads(json.dumps(value))
    pending = [value]
    ignored = {"timestamp", "execution_time_ms", "retrieval_latency_ms",
               "total_pipeline_latency_ms", "cache_hit"}
    for _ in range(100000):
        if not pending:
            break
        node = pending.pop()
        if isinstance(node, dict):
            for key in ignored:
                node.pop(key, None)
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    else:
        raise ValueError("Benchmark snapshot exceeds its node bound")
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def summary(wall, cpu):
    return {"calls": len(wall), "mean_wall_ms": statistics.mean(wall),
            "p95_wall_ms": sorted(wall)[int(.95 * (len(wall) - 1))],
            "mean_cpu_ms": statistics.mean(cpu)}


def measure(call, wall, cpu):
    start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
    result = call()
    cpu.append((time.process_time_ns() - cpu_start) / 1e6)
    wall.append((time.perf_counter_ns() - start) / 1e6)
    return result


def benchmark_ticks():
    random.seed(1729)
    wall, cpu, outputs = [], [], []
    with patch.object(server, "astronaut_sim", AstronautSimulationEngine()), patch.object(
        server, "anomaly_detector", EdgeAnomalyDetector()
    ), patch.object(server, "rag_engine", LocalMedicalRAGEngine()), patch.object(
        server, "latest_telemetry", None
    ), patch.object(server.donki_service, "get_space_weather", server.donki_service._get_cache_fallback):
        for tick in range(100):
            if tick in (0, 40, 80):
                scenario = {0: "hypercapnia", 40: "solar_flare", 80: "heat_strain"}[tick]
                server.run_simulation_command("trigger_scenario", {"scenario": scenario})
            if tick in (20, 60):
                server.astronaut_sim.cure_scenario()
            outputs.append(measure(server.advance_telemetry, wall, cpu))
    return dict(summary(wall, cpu), clinical_digest=clinical_digest(outputs))


async def benchmark_requests():
    """50 cold ASGI POSTs: clear runtime caches before every measured call."""
    wall, cpu, outputs = [], [], []
    engine = LocalMedicalRAGEngine()
    examples = list(server.SWAGGER_DIAGNOSE_EXAMPLES.values())
    with patch.object(routes, "rag_engine", engine), patch.object(routes, "anomaly_detector", EdgeAnomalyDetector()):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://benchmark") as client:
            await client.get("/health")
            for i in range(50):
                for name in ("diagnosis_cache", "_evidence_cache", "_treatment_options_cache"):
                    getattr(engine, name, {}).clear()
                start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
                response = await client.post("/api/diagnose", json=examples[i % len(examples)]["value"])
                cpu.append((time.process_time_ns() - cpu_start) / 1e6)
                wall.append((time.perf_counter_ns() - start) / 1e6)
                response.raise_for_status()
                outputs.append(response.json())
    return dict(summary(wall, cpu), clinical_digest=clinical_digest(outputs))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {"method": "Seed 1729; 100 mixed crisis/recovery ticks; 50 cold ASGI POSTs; startup excluded; local weather",
              "ticks": benchmark_ticks(), "cold_diagnose": asyncio.run(benchmark_requests())}
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
