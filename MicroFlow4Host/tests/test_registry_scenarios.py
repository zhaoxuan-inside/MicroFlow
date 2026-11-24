"""registry.publish / registry.stream / ops.events.list 契约测试。

摘要校验在测试侧独立重算（不 import 宿主的 _digest），证明两侧的 canonical JSON
约定一致——跨进程摘要可比是这条链路成立的前提。
"""
import hashlib
import json
import unittest

from test_host import HostTestBase


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":"), allow_nan=False)
                          .encode("utf-8")).hexdigest()


def _report(namespace="demo", group="dev", assets=1):
    body = {"protocol": "microflow-registry-v1", "namespace": namespace, "group": group,
            "source": {"implementation": "python", "cliProtocol": "microflow-cli-v1"},
            "project": {"digest": "p" * 64, "releaseId": "r" * 64, "durability": "ephemeral",
                        "flows": ["main"]},
            "assets": [{"kind": "operator", "dataId": f"op@{index}", "digest": f"{index}" * 64}
                       for index in range(assets)],
            "policy": {"effective": "unavailable"}, "summary": {"assets": assets},
            "diagnostics": []}
    body["digest"] = _sha(body)
    return body


def _frame(aggregate="exec-1", sequence=1, payload=None):
    return {"eventId": _sha({"aggregateKey": aggregate, "sequence": sequence,
                             "kind": "runtime_record", "payload": payload or {"n": sequence}}),
            "aggregateKey": aggregate, "sequence": sequence, "kind": "runtime_record",
            "payload": payload or {"n": sequence}}


def _batch(namespace="demo", group="dev", frames=None):
    frames = frames if frames is not None else [_frame()]
    body = {"protocol": "microflow-registry-stream-v1", "namespace": namespace, "group": group,
            "count": len(frames), "frames": frames}
    body["contentDigest"] = _sha(body)
    return body


class RegistryPublishTests(HostTestBase):
    def test_registers_then_shortcircuits_on_same_content(self):
        token = self.login()
        report = _report(assets=2)
        payload = {"namespace": report["namespace"], "group": report["group"],
                   "digest": report["digest"], "contentDigest": report["digest"],
                   "report": report}
        first = self.dispatch("registry.publish", payload, token=token)
        self.assertEqual(first.status_code, 200, first.json())
        self.assertEqual(first.json()["data"]["status"], "registered")
        self.assertEqual(first.json()["data"]["assets"], 2)

        again = self.dispatch("registry.publish", payload, token=token)
        self.assertEqual(again.json()["data"]["status"], "unchanged")

        changed = _report(assets=3)
        updated = self.dispatch("registry.publish", {
            "namespace": "demo", "group": "dev", "digest": changed["digest"],
            "contentDigest": changed["digest"], "report": changed}, token=token)
        self.assertEqual(updated.json()["data"]["status"], "updated")
        self.assertEqual(updated.json()["data"]["assets"], 3)

    def test_edited_report_is_rejected_by_digest_recomputation(self):
        token = self.login()
        report = _report()
        report["summary"]["assets"] = 99          # 内容改了，digest 没改
        response = self.dispatch("registry.publish", {
            "namespace": "demo", "group": "dev", "digest": report["digest"],
            "contentDigest": report["digest"], "report": report}, token=token)
        self.assertEqual(response.status_code, 422)
        self.assertIn("digest", response.json()["message"])

    def test_write_requires_registry_permission(self):
        self.dispatch("platform.users.create", {"username": "alice", "password": "pw"}, token=self.login())
        alice = self.dispatch("auth.login", {"username": "alice", "password": "pw"}).json()["data"]["token"]
        response = self.dispatch("registry.publish", {
            "namespace": "demo", "group": "dev", "digest": "x", "report": {}}, token=alice)
        self.assertEqual(response.status_code, 403)
        self.assertIn("registry:write", response.json()["message"])


class RegistryStreamTests(HostTestBase):
    def stream(self, batch, token):
        return self.dispatch("registry.stream", {
            "namespace": batch["namespace"], "group": batch["group"],
            "contentDigest": batch["contentDigest"], "count": batch["count"],
            "batch": batch}, token=token)

    def test_accepts_then_dedups_on_resend(self):
        token = self.login()
        frames = [_frame("exec-1", 1), _frame("exec-1", 2), _frame("exec-2", 1)]
        batch = _batch(frames=frames)
        first = self.stream(batch, token)
        self.assertEqual(first.status_code, 200, first.json())
        self.assertEqual(first.json()["data"],
                         {"status": "registered", "accepted": 3, "duplicates": 0, "count": 3})

        resent = self.stream(batch, token)
        self.assertEqual(resent.json()["data"],
                         {"status": "unchanged", "accepted": 0, "duplicates": 3, "count": 3})

    def test_tampered_batch_is_rejected(self):
        token = self.login()
        batch = _batch(frames=[_frame()])
        batch["frames"][0]["payload"] = {"forged": True}
        response = self.stream(batch, token)
        self.assertEqual(response.status_code, 422)
        self.assertIn("contentDigest", response.json()["message"])

    def test_addressing_must_agree_with_the_batch(self):
        token = self.login()
        batch = _batch()
        response = self.dispatch("registry.stream", {
            "namespace": "demo", "group": "other", "contentDigest": batch["contentDigest"],
            "count": batch["count"], "batch": batch}, token=token)
        self.assertEqual(response.status_code, 422)

    def test_unknown_protocol_and_bad_frames_are_rejected(self):
        token = self.login()
        batch = _batch()
        batch["protocol"] = "something-else"
        response = self.dispatch("registry.stream", {
            "namespace": "demo", "group": "dev", "count": 1,
            "batch": batch}, token=token)
        self.assertEqual(response.status_code, 422)
        self.assertIn("microflow-registry-stream-v1", response.json()["message"])

        bad_frame = _batch(frames=[{"eventId": "", "aggregateKey": "x", "sequence": 1,
                                    "kind": "runtime_record", "payload": {}}])
        response = self.stream(bad_frame, token)
        self.assertEqual(response.status_code, 422)

    def test_count_must_match_frames(self):
        token = self.login()
        batch = _batch(frames=[_frame()])
        response = self.dispatch("registry.stream", {
            "namespace": "demo", "group": "dev", "count": 5,
            "contentDigest": batch["contentDigest"], "batch": batch}, token=token)
        self.assertEqual(response.status_code, 422)


class OpsEventsListTests(HostTestBase):
    def test_reads_frames_with_filters(self):
        token = self.login()
        frames = [_frame("exec-1", 1, {"node_id": "calc", "status": "SUCCEEDED", "duration_ms": 12}),
                  _frame("exec-1", 2, {"node_id": "embed", "status": "SUCCEEDED", "duration_ms": 30})]
        batch = _batch(frames=frames)
        self.assertEqual(self.dispatch("registry.stream", {
            "namespace": "demo", "group": "dev", "contentDigest": batch["contentDigest"],
            "count": 2, "batch": batch}, token=token).status_code, 200)

        response = self.dispatch("ops.events.list", {"aggregate_key": "exec-1"}, token=token)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["total"], 2)
        self.assertEqual([event["sequence"] for event in data["events"]], [2, 1])
        self.assertEqual(data["events"][0]["payload"]["node_id"], "embed")
        self.assertEqual(data["events"][0]["kind"], "runtime_record")
        self.assertTrue(data["events"][0]["batch_digest"])

    def test_requires_ops_console_permission(self):
        self.dispatch("platform.users.create", {"username": "bob", "password": "pw"}, token=self.login())
        bob = self.dispatch("auth.login", {"username": "bob", "password": "pw"}).json()["data"]["token"]
        response = self.dispatch("ops.events.list", {}, token=bob)
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
