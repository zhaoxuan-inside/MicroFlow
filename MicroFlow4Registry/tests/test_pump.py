"""Acceptance A28-A32: the pump conserves at-least-once and never over-acks."""
import tempfile
import time
import unittest
from pathlib import Path

from microflow_registry.pump import EventPump
from microflow_registry.push import resolve_config
from microflow_registry.sink import RecordStream
from microflow_registry.store import Store

from .http_stub import dispatch_stub

PLANNED = [
    {"event_id": "evt-1", "event_type": "microflow.execution", "schema_version": "1",
     "aggregate_key": "exec-1", "sequence": 1, "payload": {"status": "ACCEPTED"},
     "occurred_at": 1.0, "content_digest": "d" * 64, "delivery": "PENDING"},
    {"event_id": "evt-2", "event_type": "microflow.execution", "schema_version": "1",
     "aggregate_key": "exec-1", "sequence": 2, "payload": {"status": "COMPLETED"},
     "occurred_at": 2.0, "content_digest": "e" * 64, "delivery": "PENDING"},
]


def stable_request_id(intent):
    import hashlib, json
    body = json.dumps({"ack": intent["event_id"], "content_digest": intent["content_digest"]},
                     sort_keys=True).encode()
    return hashlib.sha256(body).hexdigest()


class PumpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.acked_ids = []
        self.pending_intents = list(PLANNED)

    def pending(self, limit=100):
        # 像真状态账本：已确认的意图不再出现在 pending 里
        return [intent for intent in self.pending_intents
                if intent.get("event_id") not in self.acked_ids]

    def acknowledge(self, intent):
        self.acked_ids.append(intent["event_id"])

    def stream(self, endpoint):
        return RecordStream(namespace="demo", group="dev",
                            config=resolve_config(endpoint=endpoint, token="secret"),
                            store=Store(self.root / "store"),
                            capacity=50, flush_size=10, flush_interval=5.0)

    # A28
    def test_delivers_a_page_and_acks_every_intent(self):
        with dispatch_stub() as server:
            pump = EventPump(pending=self.pending, acknowledge=self.acknowledge,
                             stream=self.stream(server.endpoint))
            outcome = pump.tick()
        self.assertEqual(outcome, {"fetched": 2, "accepted": 2, "acked": 2,
                                    "clean": True, "outbox": 0, "tick": 1})
        self.assertEqual(self.acked_ids, ["evt-1", "evt-2"])
        frames = [request["body"]["payload"]["batch"]["frames"] for request in server.requests]
        self.assertEqual([frame["eventId"] for batch in frames for frame in batch],
                         ["evt-1", "evt-2"])
        self.assertTrue(all(frame["kind"] == "event_intent"
                            for batch in frames for frame in batch))

    # A29
    def test_flush_failure_keeps_intents_pending_and_never_over_acks(self):
        stream = self.stream("http://127.0.0.1:9/x")      # dead endpoint
        pump = EventPump(pending=self.pending, acknowledge=self.acknowledge, stream=stream)
        outcome = pump.tick()
        self.assertEqual(outcome["acked"], 0)
        self.assertFalse(outcome["clean"])
        self.assertEqual(self.acked_ids, [])               # no over-ack: intents stay PENDING
        self.assertEqual(outcome["outbox"], 1)             # the batch is durable
        self.assertEqual(pump.stats()["deferred"], 2)

        with dispatch_stub() as server:                    # host recovers → redelivery drains
            stream._config = resolve_config(endpoint=server.endpoint, token="secret")
            recovered = EventPump(pending=self.pending, acknowledge=self.acknowledge, stream=stream)
            outcome = recovered.tick()
        self.assertEqual(outcome["acked"], 2)
        self.assertEqual(self.acked_ids, ["evt-1", "evt-2"])
        self.assertEqual(outcome["outbox"], 0)

    # A30
    def test_invalid_intent_is_counted_and_does_not_poison_the_page(self):
        broken = dict(PLANNED[0])
        broken.pop("event_id")
        self.pending_intents = [broken, PLANNED[1]]
        with dispatch_stub() as server:
            pump = EventPump(pending=self.pending, acknowledge=self.acknowledge,
                             stream=self.stream(server.endpoint))
            outcome = pump.tick()
        self.assertEqual(outcome["accepted"], 1)
        self.assertEqual(pump.stats()["invalid"], 1)
        self.assertFalse(outcome["clean"])                  # conservative: dirty page → no ack
        self.assertEqual(self.acked_ids, [])

    # A31
    def test_ack_failure_is_counted_and_retried_next_tick(self):
        failing = {"n": 0}

        def flaky_ack(intent):
            failing["n"] += 1
            if failing["n"] <= 1:
                raise RuntimeError("state store unavailable")
            self.acked_ids.append(intent["event_id"])

        with dispatch_stub() as server:
            pump = EventPump(pending=self.pending, acknowledge=flaky_ack,
                             stream=self.stream(server.endpoint))
            first = pump.tick()
            self.assertEqual(first["acked"], 1)             # evt-2 acked, evt-1 raised
            second = pump.tick()
        self.assertEqual(second["acked"], 1)               # 只剩 evt-1 重试
        self.assertEqual(self.acked_ids, ["evt-2", "evt-1"])
        self.assertGreaterEqual(pump.stats()["ack_failures"], 1)

    # A32
    def test_background_loop_drains_and_closes(self):
        with dispatch_stub() as server:
            pump = EventPump(pending=self.pending, acknowledge=self.acknowledge,
                             stream=self.stream(server.endpoint), interval=0.02).start()
            deadline = time.monotonic() + 2.0
            while not self.acked_ids and time.monotonic() < deadline:
                time.sleep(0.01)
            pump.close()
        self.assertEqual(self.acked_ids, ["evt-1", "evt-2"])


if __name__ == "__main__":
    unittest.main()
