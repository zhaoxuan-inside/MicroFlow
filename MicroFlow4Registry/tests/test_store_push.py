"""Acceptance A6-A10: digest conflict, failure isolation, rate limit, idempotency."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from microflow_registry import cli

from . import fixtures
from .http_stub import dispatch_stub


def run(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(argv)
    return code, json.loads(out.getvalue())


class PushTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {
            "PYTHONPATH": str(fixtures.PYTHON_SRC),
            "MF_REGISTRY_CLI": f"{sys.executable} -m microflow",
            "MF_REGISTRY_ENDPOINT": "",
            "MF_REGISTRY_TOKEN": "",
        })
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "store"
        self.project = fixtures.write_project(self.root / "proj")

    def export(self, *, out="report.json"):
        target = self.root / out
        code, report = run(["export", str(self.project), "--namespace", "demo",
                            "--group", "dev", "--ephemeral", "--out", str(target)])
        self.assertEqual(code, 0, report)
        return target, report

    def push(self, path, endpoint, *extra, token="secret"):
        return run(["push", str(path), "--endpoint", endpoint, "--token", token,
                    "--store", str(self.store), *extra])

    def test_push_registers_and_records_state(self):
        path, report = self.export()
        with dispatch_stub() as server:
            code, payload = self.push(path, server.endpoint)
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["pushed"])
        self.assertEqual(payload["status"], "registered")
        self.assertEqual(payload["digest"], report["digest"])
        sent = server.requests[0]["body"]
        self.assertEqual(sent["scenario"], "registry.publish")
        self.assertEqual(sent["version"], 1)
        self.assertEqual(sent["payload"]["digest"], report["digest"])
        self.assertEqual(sent["context"]["token"], "secret")
        self.assertEqual(server.requests[0]["authorization"], "Bearer secret")
        state = json.loads((self.store / "snapshots/demo/dev/push.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "registered")

    # A9
    def test_push_short_circuits_identical_report(self):
        path, _ = self.export()
        with dispatch_stub() as server:
            first_code, _ = self.push(path, server.endpoint)
            second_code, payload = self.push(path, server.endpoint)
            requests = len(server.requests)
        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(payload["status"], "unchanged")
        self.assertFalse(payload["pushed"])
        self.assertEqual(payload["source"], "client-cache")
        self.assertEqual(requests, 1)

    # A6
    def test_digest_conflict_is_rejected(self):
        path, _ = self.export()
        with dispatch_stub() as server:
            self.assertEqual(self.push(path, server.endpoint)[0], 0)
            module = (self.root / "proj" / "ops.py").read_text(encoding="utf-8")
            (self.root / "proj" / "ops.py").write_text(
                module.replace('adds one', 'adds one, quietly'), encoding="utf-8")
            changed, _ = self.export(out="report2.json")
            code, payload = self.push(changed, server.endpoint)
            requests = len(server.requests)
        self.assertEqual(code, 1)
        self.assertEqual(payload["diagnostic"]["error_code"], "REGISTRY_DIGEST_CONFLICT")
        self.assertIn("increment@1", payload["diagnostic"]["message"])
        self.assertEqual(requests, 1, "a conflict must be refused before any network call")

    # A7
    def test_push_network_failure_keeps_snapshot(self):
        path, report = self.export()
        code, payload = self.push(path, "http://127.0.0.1:9/api/v1/dispatch")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "PUSH_FAILED")
        snapshot = json.loads((self.store / "snapshots/demo/dev/report.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["digest"], report["digest"])
        self.assertFalse((self.store / "snapshots/demo/dev/push.json").exists())

    # A8
    def test_push_rate_limited(self):
        path, _ = self.export()

        def overloaded(_server):
            return 429, {"code": 429, "data": None, "message": "telemetry backlog full",
                         "trace_id": "t-429"}

        with dispatch_stub(overloaded) as server:
            code, payload = self.push(path, server.endpoint)
            attempts = len(server.requests)
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "RATE_LIMITED")
        self.assertEqual(attempts, 1, "default is no retry")

    def test_push_retries_are_opt_in_and_bounded(self):
        path, _ = self.export()
        calls = {"n": 0}

        def flaky(_server):
            calls["n"] += 1
            if calls["n"] == 1:
                return 503, {"code": 503, "message": "temporarily unavailable"}
            return 200, {"code": 0, "data": {"status": "registered"}, "trace_id": "t-ok"}

        with dispatch_stub(flaky) as server:
            code, payload = self.push(path, server.endpoint, "--retries", "1")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "registered")
        self.assertEqual(calls["n"], 2)

    # A10
    def test_push_requires_token(self):
        path, _ = self.export()
        code, payload = run(["push", str(path), "--endpoint", "http://127.0.0.1:9/x",
                             "--store", str(self.store)])
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "TOKEN_NOT_CONFIGURED")

    def test_push_rejects_non_registry_report(self):
        path = self.root / "other.json"
        path.write_text(json.dumps({"protocol": "something-else"}), encoding="utf-8")
        code, payload = self.push(path, "http://127.0.0.1:9/x")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "REPORT_PROTOCOL_MISMATCH")

    def test_push_rejects_tampered_report(self):
        path, report = self.export()
        tampered = dict(report)
        tampered["summary"] = {"assets": 99, "flows": 1, "diagnostics": 0}
        path.write_text(json.dumps(tampered), encoding="utf-8")
        code, payload = self.push(path, "http://127.0.0.1:9/x")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "REPORT_DIGEST_MISMATCH")

    def test_push_rejects_ephemeral(self):
        path, _ = self.export()
        code, payload = self.push(path, "http://127.0.0.1:9/x", "--ephemeral")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "EPHEMERAL_REJECTED")

    def test_dry_run_makes_no_request(self):
        path, report = self.export()
        with dispatch_stub() as server:
            code, payload = self.push(path, server.endpoint, "--dry-run")
            requests = len(server.requests)
        self.assertEqual(code, 0)
        self.assertTrue(payload["dryRun"])
        self.assertEqual(payload["payload"]["scenario"], "registry.publish")
        self.assertEqual(requests, 0)
        self.assertFalse(self.store.exists())

    def test_status_reports_snapshot_sync_state(self):
        path, _ = self.export()
        with dispatch_stub() as server:
            self.assertEqual(self.push(path, server.endpoint)[0], 0)
        code, payload = run(["status", "--store", str(self.store)])
        self.assertEqual(code, 0)
        self.assertEqual(len(payload["snapshots"]), 1)
        row = payload["snapshots"][0]
        self.assertEqual((row["namespace"], row["group"]), ("demo", "dev"))
        self.assertTrue(row["inSync"])
        self.assertEqual(row["lastPush"]["status"], "registered")


if __name__ == "__main__":
    unittest.main()
