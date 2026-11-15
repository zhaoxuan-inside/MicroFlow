"""Reproducible local-runtime baseline; not an HTTP or production capacity test."""
import argparse
import asyncio
import json
import math
import platform
import statistics
import time

from microflow import LocalRuntime, Registry
from microflow.compiler import compile_release


def increment(input, output, context, metrix, debug, log):
    output.set("n", input["n"] + 1)
    return True


def build_runtime(delay_ms):
    registry = Registry()
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    registry.register_schema("bench.integer", schema)
    async def increment_with_io(input, output, context, metrix, debug, log):
        await asyncio.sleep(delay_ms / 1000)
        output.set("n", input["n"] + 1)
        return True
    registry.register_operator(name="bench.increment", version="1",
                               method=increment_with_io if delay_ms else increment,
                               input_schema="bench.integer", output_schema="bench.integer")
    flow = {"id": "bench", "input_schema": "bench.integer", "output_schema": "bench.integer",
            "nodes": {"increment": {"operator": "bench.increment@1",
                       "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
            "outputs": {"n": {"from": "nodes.increment.output.data.n", "required": True}}}
    release = compile_release(registry, [flow], defaults={"durability": "ephemeral",
                                                         "recovery": {"enabled": False}})
    return LocalRuntime(release)


def percentile(values, fraction):
    return values[max(0, math.ceil(len(values) * fraction) - 1)]


async def benchmark(requests, concurrency, delay_ms=0):
    runtime = build_runtime(delay_ms)
    await runtime.run_async("bench", {"n": 0})  # Exclude preflight from measurements.
    durations = []
    failures = 0
    lifecycle_records = 0
    active = 0
    peak_active = 0
    next_request = iter(range(requests))

    async def worker():
        nonlocal failures, active, peak_active, lifecycle_records
        for index in next_request:
            start = time.perf_counter()
            active += 1
            peak_active = max(peak_active, active)
            try:
                result = await runtime.run_async("bench", {"n": index})
                records = result.records
                lifecycle_records += len(records)
                if (result.output["meta"]["status"] != "SUCCEEDED" or result.output["data"]["n"] != index + 1
                        or [r["event"] for r in records] != ["attempt_started", "attempt_finished", "invocation_completed"]
                        or records[1].get("durationMs") is None):
                    failures += 1
            except Exception:
                failures += 1
            finally:
                active -= 1
            durations.append((time.perf_counter() - start) * 1000)

    start = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(min(requests, concurrency))))
    elapsed = time.perf_counter() - start
    durations.sort()
    return {"benchmark": "local-runtime-ephemeral-v1", "python": platform.python_version(),
            "requests": requests, "concurrency": concurrency, "failures": failures,
            "peak_active_requests": peak_active, "simulated_io_ms": delay_ms,
            "lifecycle_records": lifecycle_records,
            "elapsed_seconds": round(elapsed, 6), "requests_per_second": round(requests / elapsed, 2),
            "latency_ms": {"mean": round(statistics.fmean(durations), 3),
                           "p50": round(percentile(durations, .50), 3),
                           "p95": round(percentile(durations, .95), 3),
                           "p99": round(percentile(durations, .99), 3)},
            "scope": "in-process ephemeral execution; simulated I/O is a timer, excludes network, persistence and recovery"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--delay-ms", type=float, default=0,
                        help="Simulated asynchronous I/O delay per operator (0 uses a synchronous operator)")
    args = parser.parse_args()
    if not 1 <= args.requests <= 1_000_000 or not 1 <= args.concurrency <= 100_000:
        parser.error("requests must be 1..1000000 and concurrency 1..100000")
    if not math.isfinite(args.delay_ms) or not 0 <= args.delay_ms <= 60_000:
        parser.error("delay-ms must be finite and between 0 and 60000")
    result = asyncio.run(benchmark(args.requests, args.concurrency, args.delay_ms))
    print(json.dumps(result, sort_keys=True))
    return int(result["failures"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
