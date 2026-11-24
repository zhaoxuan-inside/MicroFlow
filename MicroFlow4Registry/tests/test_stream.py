"""Acceptance A13-A20: event batches — deterministic frames, outbox, replay, gates."""
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from microflow_registry import cli
from microflow_registry.envelope import digest
from microflow_registry.stream import build_batch, build_frame

from .http_stub import dispatch_stub


def run(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(argv)
    return code, json.loads(out.getvalue())


def frames(count, aggregate="exec-1", start=1):
    return [build_frame({"node": f"n{index}"}, aggregate_key=aggregate, sequence=start + index)
            for index in range(count)]


class StreamCliTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {
            "MF_REGISTRY_TOKEN": "", "MF_REGISTRY_ENDPOINT": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "store"

    def write(self, batch, name="batch.json"):
        path = self.root / name
        path.write_text(json.dumps(batch), encoding="utf-8")
        return path

    def stream(self, path, endpoint, *extra, token="secret"):
        return run(["stream", str(path), "--endpoint", endpoint, "--token", token,
                    "--store", str(self.store), *extra])

    # A13
    def test_batch_is_deterministic_and_ordered(self):
        unordered = [build_frame({"n": 2}, aggregate_key="b", sequence=1),
                     build_frame({"n": 1}, aggregate_key="a", sequence=2)]
        first = build_batch("demo", "dev", unordered)
        second = build_batch("demo", "dev", list(reversed(unordered)))
        self.assertEqual(first, second)
        self.assertEqual([(f["aggregateKey"], f["sequence"]) for f in first["frames"]],
                         [("a", 2), ("b", 1)])
        self.assertEqual(first["count"], 2)

    # A14
    def test_stream_pushes_and_acknowledges(self):
        batch = build_batch("demo", "dev", frames(2))
        path = self.write(batch)
        with dispatch_stub() as server:
            code, payload = self.stream(path, server.endpoint)
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["pushed"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["outbox"], 0)
        sent = server.requests[0]["body"]
        self.assertEqual(sent["scenario"], "registry.stream")
        self.assertEqual(sent["payload"]["contentDigest"], batch["contentDigest"])
        self.assertEqual(sent["payload"]["count"], 2)
        self.assertEqual(len(sent["payload"]["batch"]["frames"]), 2)
        self.assertEqual(server.requests[0]["authorization"], "Bearer secret")

    # A15
    def test_network_failure_keeps_outbox_then_replay_drains_it(self):
        batch = build_batch("demo", "dev", frames(3))
        path = self.write(batch)
        code, payload = self.stream(path, "http://127.0.0.1:9/api/v1/dispatch")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "PUSH_FAILED")
        self.assertEqual(len(list((self.store / "snapshots/demo/dev/outbox").glob("*.json"))), 1)

        with dispatch_stub() as server:
            replay_code, replay = run(["stream", "--replay", "--namespace", "demo", "--group", "dev",
                                       "--endpoint", server.endpoint, "--token", "secret",
                                       "--store", str(self.store)])
        self.assertEqual(replay_code, 0, replay)
        self.assertEqual(replay["acked"], 1)
        self.assertEqual(replay["frames"], 3)
        self.assertEqual(replay["outbox"], 0)

    # A16
    def test_tampered_batch_is_rejected(self):
        batch = build_batch("demo", "dev", frames(1))
        batch["frames"][0]["payload"] = {"node": "forged"}
        path = self.write(batch)
        code, payload = self.stream(path, "http://127.0.0.1:9/x")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "STREAM_DIGEST_MISMATCH")

    def test_forged_event_id_is_rejected(self):
        batch = build_batch("demo", "dev", frames(1))
        body = {key: value for key, value in batch.items() if key != "contentDigest"}
        body["frames"][0]["eventId"] = "0" * 64
        body["contentDigest"] = digest(body)          # make the batch self-consistent
        path = self.write(body)
        code, payload = self.stream(path, "http://127.0.0.1:9/x")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "STREAM_DIGEST_MISMATCH")
        self.assertIn("eventId", payload["diagnostic"]["message"])

    # A17
    def test_oversized_batch_is_rejected(self):
        path = self.write({"protocol": "microflow-registry-stream-v1", "namespace": "demo",
                           "group": "dev", "count": 501, "frames": [{"x": 1}] * 501,
                           "contentDigest": "0" * 64})
        code, payload = self.stream(path, "http://127.0.0.1:9/x")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "BATCH_TOO_LARGE")

    # A18
    def test_identical_batch_short_circuits(self):
        batch = build_batch("demo", "dev", frames(1))
        path = self.write(batch)
        with dispatch_stub() as server:
            self.assertEqual(self.stream(path, server.endpoint)[0], 0)
            code, payload = self.stream(path, server.endpoint)
            requests = len(server.requests)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "unchanged")
        self.assertEqual(requests, 1)

    def test_needs_a_batch_or_replay(self):
        code, payload = run(["stream"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "STREAM_INVALID")

    def test_replay_dry_run_lists_pending_without_sending(self):
        batch = build_batch("demo", "dev", frames(2))
        self.stream(self.write(batch), "http://127.0.0.1:9/x")
        with dispatch_stub() as server:
            code, payload = run(["stream", "--replay", "--namespace", "demo", "--group", "dev",
                                 "--endpoint", server.endpoint, "--token", "secret",
                                 "--store", str(self.store), "--dry-run"])
            requests = len(server.requests)
        self.assertEqual(code, 0)
        self.assertEqual(payload["pending"], [batch["contentDigest"]])
        self.assertEqual(requests, 0)

    def test_stream_rejects_ephemeral(self):
        batch = build_batch("demo", "dev", frames(1))
        code, payload = self.stream(self.write(batch), "http://127.0.0.1:9/x", "--ephemeral")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "EPHEMERAL_REJECTED")

    # A25
    def test_status_lists_stream_only_groups(self):
        batch = build_batch("demo", "dev", frames(2))
        with dispatch_stub() as server:
            self.stream(self.write(batch), server.endpoint)
        code, payload = run(["status", "--store", str(self.store)])
        self.assertEqual(code, 0, payload)
        row = payload["snapshots"][0]
        self.assertEqual((row["namespace"], row["group"]), ("demo", "dev"))
        self.assertEqual(row["outbox"], 0)
        self.assertEqual(row["lastStream"]["status"], "registered")
        self.assertEqual(row["lastStream"]["count"], 2)
        self.assertEqual(row["assets"], 0)

    def test_batch_addressing_must_agree_with_flags(self):
        batch = build_batch("demo", "dev", frames(1))
        code, payload = self.stream(self.write(batch), "http://127.0.0.1:9/x", "--group", "online")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "INVALID_ADDRESSING")


if __name__ == "__main__":
    unittest.main()
