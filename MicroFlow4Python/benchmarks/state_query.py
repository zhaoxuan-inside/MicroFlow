"""Compare targeted and full-snapshot reads using the in-memory protocol double."""
import argparse
import json
import statistics
import time

from local_runtime import build_runtime, percentile
from microflow.coordinator import Coordinator
from microflow.persistence import StateBatch, StorageBinding
from microflow.scheduling import ExecutionCommands
from microflow.testing import MemoryStateStore
from microflow.values import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=500)
    parser.add_argument("--queries", type=int, default=500)
    args = parser.parse_args()
    if not 1 <= args.records <= 10_000 or not 1 <= args.queries <= 100_000:
        parser.error("records must be 1..10000 and queries 1..100000")
    store = MemoryStateStore(max_records=args.records + 100)
    coordinator = Coordinator(store)
    binding = StorageBinding("benchmark", "state", "benchmark", coordinator.view().binding_revision, digest({}))
    commands = ExecutionCommands(coordinator, build_runtime(0).release, binding=binding, protocol_test=True)
    accepted = commands.accept("bench", {"n": 1}, request_id="benchmark")
    filler = {f"history/{i}": {"value": i} for i in range(args.records)}
    coordinator.transact(lambda _: (StateBatch(filler), None))
    targeted = store.load_record_view

    def measure():
        samples = []
        for _ in range(args.queries):
            started = time.perf_counter()
            result = commands.query(accepted["execution_id"])
            if result["status"] != "ACCEPTED":
                raise RuntimeError("Unexpected execution state")
            samples.append((time.perf_counter() - started) * 1000)
        samples.sort()
        return {"mean_ms": round(statistics.fmean(samples), 3),
                "p95_ms": round(percentile(samples, .95), 3)}

    try:
        fast = measure()
        store.load_record_view = None
        full = measure()
        store.load_record_view = targeted
        print(json.dumps({"benchmark": "memory-state-query-v1", "history_records": args.records,
                          "queries": args.queries, "targeted": fast, "full_snapshot": full,
                          "scope": "in-memory protocol double; not production storage or network"}, sort_keys=True))
    finally:
        coordinator.close()


if __name__ == "__main__":
    main()
