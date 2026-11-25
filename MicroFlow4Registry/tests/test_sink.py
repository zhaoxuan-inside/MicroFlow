"""Acceptance A21-A24: the sink never blocks business code and never lies about loss."""
import tempfile
import time
import unittest
from pathlib import Path

from microflow_registry.push import resolve_config
from microflow_registry.sink import RecordStream
from microflow_registry.store import Store

from .http_stub import dispatch_stub


class SinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def stream(self, endpoint, *, capacity=100, flush_size=10, interval=5.0):
        return RecordStream(namespace="demo", group="dev",
                            config=resolve_config(endpoint=endpoint, token="secret"),
                            store=Store(self.root / "store"), capacity=capacity,
                            flush_size=flush_size, flush_interval=interval, retries=0)

    def payloads(self, server):
        return [request["body"]["payload"] for request in server.requests]

    # A21
    def test_accept_is_bounded_and_never_raises_when_full(self):
        stream = self.stream("http://127.0.0.1:9/x", capacity=2, flush_size=1)
        self.assertTrue(stream.accept({"executionId": "e1", "n": 1}))
        self.assertTrue(stream.accept({"executionId": "e1", "n": 2}))
        self.assertFalse(stream.accept({"executionId": "e1", "n": 3}))
        stats = stream.stats()
        self.assertEqual(stats["accepted"], 2)
        self.assertEqual(stats["dropped"], 1)
        self.assertEqual(stats["queued"], 2)

    # A22
    def test_sequence_is_monotonic_per_aggregate(self):
        with dispatch_stub() as server:
            stream = self.stream(server.endpoint, flush_size=5)
            for name in ("e1", "e1", "e2", "e1"):
                stream.accept({"executionId": name, "n": 1})
            self.assertEqual(stream.flush(), 4)
        frames = self.payloads(server)[0]["batch"]["frames"]
        seen = {}
        for frame in frames:
            seen.setdefault(frame["aggregateKey"], []).append(frame["sequence"])
        self.assertEqual(seen["e1"], [1, 2, 3])
        self.assertEqual(seen["e2"], [1])

    # A23
    def test_flush_sends_chunks_of_flush_size(self):
        with dispatch_stub() as server:
            stream = self.stream(server.endpoint, capacity=10, flush_size=2)
            for index in range(5):
                stream.accept({"executionId": "e1", "n": index})
            pushed = stream.flush()
            counts = [payload["count"] for payload in self.payloads(server)]
        self.assertEqual(pushed, 5)
        self.assertEqual(counts, [2, 2, 1])
        self.assertEqual(stream.stats()["queued"], 0)
        state = Store(self.root / "store").stream_state("demo", "dev")
        self.assertEqual(state["status"], "registered")
        self.assertEqual(state["count"], 1)

    # A24
    def test_failure_keeps_outbox_and_replay_drains_it(self):
        stream = self.stream("http://127.0.0.1:9/x", flush_size=5)
        stream.accept({"executionId": "e1", "n": 1})
        self.assertEqual(stream.flush(), 0)
        stats = stream.stats()
        self.assertEqual(stats["pushed"], 0)
        self.assertGreaterEqual(stats["failed_flushes"], 1)
        self.assertEqual(stats["outbox"], 1)

        with dispatch_stub() as server:
            stream._config = resolve_config(endpoint=server.endpoint, token="secret")
            self.assertEqual(stream.replay(), 1)
        self.assertEqual(stream.stats()["outbox"], 0)
        self.assertEqual(stream.stats()["pushed"], 1)

    def test_invalid_payload_is_counted_not_raised(self):
        with dispatch_stub() as server:
            stream = self.stream(server.endpoint, flush_size=5)
            self.assertTrue(stream.accept({"executionId": "e1", "n": 1}))
            self.assertTrue(stream.accept({"executionId": "e1", "bad": float("nan")}))
            self.assertTrue(stream.accept({"executionId": "e1", "n": 3}))
            self.assertEqual(stream.flush(), 2)
        self.assertEqual(stream.stats()["invalid"], 1)
        frames = self.payloads(server)[0]["batch"]["frames"]
        self.assertEqual([f["sequence"] for f in frames], [1, 3])

    def test_unattributed_records_are_visible(self):
        stream = self.stream("http://127.0.0.1:9/x")
        self.assertTrue(stream.accept({"n": 1}))
        self.assertTrue(stream.accept({"executionId": "bad/key", "n": 2}))
        stats = stream.stats()
        self.assertEqual(stats["renamed"], 1)
        self.assertEqual(stats["accepted"], 2)

    def test_background_flusher_drains_and_closes(self):
        with dispatch_stub() as server:
            stream = self.stream(server.endpoint, flush_size=1, interval=0.02)
            stream.start()
            stream.accept({"executionId": "e1", "n": 1})
            deadline = time.monotonic() + 2.0
            while not server.requests and time.monotonic() < deadline:
                time.sleep(0.01)
            stream.close()
        self.assertTrue(server.requests)
        self.assertGreaterEqual(stream.stats()["pushed"], 1)

    # A26
    def test_accept_intent_preserves_identity_verbatim(self):
        with dispatch_stub() as server:
            stream = self.stream(server.endpoint, flush_size=5)
            accepted = stream.accept_intent({
                "event_id": "evt-001", "event_type": "order.placed",
                "schema_version": "1", "aggregate_key": "order-42", "sequence": 5,
                "payload": {"amount": 9900}, "occurred_at": 1700000000.0})
            self.assertTrue(accepted)
            self.assertEqual(stream.flush(), 1)
            frame = self.payloads(server)[0]["batch"]["frames"][0]
        self.assertEqual(frame["kind"], "event_intent")
        self.assertEqual(frame["eventId"], "evt-001")          # 身份原样保留，不重算
        self.assertEqual(frame["aggregateKey"], "order-42")
        self.assertEqual(frame["sequence"], 5)                 # 序号沿用意图，不重派
        self.assertEqual(frame["occurredAt"], "2023-11-14T22:13:20+00:00")
        self.assertEqual(frame["payload"]["event_type"], "order.placed")
        self.assertEqual(frame["payload"]["payload"], {"amount": 9900})

    # A27
    def test_intent_without_identity_is_counted_not_queued(self):
        stream = self.stream("http://127.0.0.1:9/x", flush_size=5)
        for intent in ({"aggregate_key": "a", "sequence": 1},                       # 无 event_id
                       {"event_id": "x", "aggregate_key": "bad/key", "sequence": 1},  # 聚合键非法
                       {"event_id": "y", "aggregate_key": "a", "sequence": 0}):      # 序号非法
            self.assertFalse(stream.accept_intent(intent))
        stats = stream.stats()
        self.assertEqual(stats["invalid"], 3)
        self.assertEqual(stats["accepted"], 0)
        self.assertEqual(stats["queued"], 0)

    def test_intent_and_record_frames_share_one_batch(self):
        with dispatch_stub() as server:
            stream = self.stream(server.endpoint, flush_size=5)
            stream.accept({"executionId": "exec-1", "node_id": "calc", "duration_ms": 12})
            stream.accept_intent({"event_id": "evt-9", "event_type": "order.placed",
                                  "schema_version": "1", "aggregate_key": "order-9",
                                  "sequence": 1, "payload": {}})
            self.assertEqual(stream.flush(), 2)
            frames = self.payloads(server)[0]["batch"]["frames"]
        self.assertEqual([frame["kind"] for frame in frames],
                         ["runtime_record", "event_intent"])
        self.assertEqual([frame["aggregateKey"] for frame in frames], ["exec-1", "order-9"])


if __name__ == "__main__":
    unittest.main()
