"""交付域测试：登记幂等/内容寻址、证据门禁、环境链守卫、第二人审批、审计与 REST 面。"""
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from delivery import DeliveryStore, GateRejected, create_app
from delivery.cli import main as cli_main
from delivery.errors import DeliveryError

# ---- 证据夹具（与 Spec / 4Python CLI / Verify 的真实信封同形） ----


def coverage_report(green: bool, digest: str = "sha256:" + "a" * 64) -> dict:
    return {"envelope": "microflow-spec-v1", "command": "coverage", "ok": green, "exit": 0 if green else 1,
            "summary": {"requirements": 2, "scenarios": 2, "covered": 2 if green else 1,
                        "uncovered": 0 if green else 1, "manualOnly": 0},
            "rows": [], "orphans": [], "diagnostics": [],
            "spec": {"project": "demo", "digest": digest, "counts": {"requirements": 2, "scenarios": 2}}}


def check_report(diagnostics: list | None = None) -> dict:
    return {"protocol": "microflow-cli-v1", "releaseId": "r1", "durability": "ephemeral",
            "flows": ["main"], "diagnostics": diagnostics if diagnostics is not None else []}


def verify_report(verdict: str = "pass") -> dict:
    return {"envelope": "microflow-verify-v1", "script": "verify/login.json", "verdict": verdict,
            "assertions": [], "summary": {"total": 2, "passed": 2 if verdict == "pass" else 1,
                                          "failed": 0 if verdict == "pass" else 1}}


class DeliveryTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.store = DeliveryStore(root / "store.sqlite3")
        self.files = root / "evidence"
        self.files.mkdir()
        self.blob = root / "bundle.tar"
        self.blob.write_bytes(b"artifact-bytes-v1")

    def tearDown(self):
        self.store.close()
        self._tmp.cleanup()

    def write(self, name: str, payload: dict) -> Path:
        path = self.files / name
        path.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True), encoding="utf-8")
        return path

    def register(self, *, blob: bytes | None = None, coverage: dict | None = None,
                 check: dict | None = None, verify: dict | None = None,
                 kind: str = "web_bundle", by: str = "builder") -> dict:
        return self.store.register_artifact(
            kind=kind, blob=blob if blob is not None else self.blob.read_bytes(),
            spec_coverage_path=self.write("coverage.json", coverage or coverage_report(True)),
            check_report_path=self.write("check.json", check or check_report()),
            verify_report_path=self.write("verify.json", verify or verify_report()),
            build_inputs_path=None, registered_by=by)


class RegisterTests(DeliveryTestBase):
    def test_register_is_content_addressed_and_idempotent(self):
        first = self.register()
        second = self.register()
        self.assertEqual(first["artifactId"], second["artifactId"])
        self.assertTrue(first["artifactId"].startswith("sha256:"))
        self.assertEqual(first["blobDigest"], "sha256:" + __import__("hashlib").sha256(b"artifact-bytes-v1").hexdigest())

    def test_different_bytes_yield_different_artifacts(self):
        other = self.register(blob=b"artifact-bytes-v2")
        self.assertNotEqual(self.register()["artifactId"], other["artifactId"])

    def test_evidence_envelopes_are_validated(self):
        with self.assertRaises(DeliveryError) as caught:
            self.register(coverage={"envelope": "other", "ok": True})
        self.assertEqual(caught.exception.code, "EVIDENCE_MALFORMED")

    def test_missing_spec_digest_is_rejected(self):
        bad = coverage_report(True)
        del bad["spec"]
        with self.assertRaises(DeliveryError) as caught:
            self.register(coverage=bad)
        self.assertEqual(caught.exception.code, "EVIDENCE_MALFORMED")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(DeliveryError) as caught:
            self.register(kind="iso_image")
        self.assertEqual(caught.exception.code, "INVALID_ARTIFACT_KIND")


class PromoteGateTests(DeliveryTestBase):
    def test_full_chain_with_approvers_passes(self):
        artifact = self.register()
        for env in ("dev", "test", "staging", "online"):
            result = self.store.promote(artifact["artifactId"], env,
                                        actor="alice", approver="bob" if env in ("staging", "online") else None)
        self.assertEqual(result["env"], "online")
        self.assertEqual([p["env"] for p in self.store.pointers()],
                         ["dev", "test", "staging", "online"])
        self.assertEqual(self.store.pointer("online")["artifactId"], artifact["artifactId"])

    def test_coverage_not_green_is_rejected(self):
        artifact = self.register(coverage=coverage_report(False))
        with self.assertRaises(GateRejected) as caught:
            self.store.promote(artifact["artifactId"], "dev", actor="alice")
        self.assertEqual(caught.exception.reasons[0]["gate"], "spec-coverage")

    def test_check_diagnostics_block_promotion(self):
        artifact = self.register(check=check_report([{"code": "SOMETHING"}]))
        with self.assertRaises(GateRejected) as caught:
            self.store.promote(artifact["artifactId"], "dev", actor="alice")
        self.assertEqual(caught.exception.reasons[0]["gate"], "check")

    def test_failed_verify_blocks_promotion(self):
        artifact = self.register(verify=verify_report("fail"))
        with self.assertRaises(GateRejected) as caught:
            self.store.promote(artifact["artifactId"], "dev", actor="alice")
        self.assertEqual(caught.exception.reasons[0]["gate"], "verify")

    def test_env_order_requires_previous_env_record(self):
        artifact = self.register()
        with self.assertRaises(GateRejected) as caught:
            self.store.promote(artifact["artifactId"], "test", actor="alice")
        self.assertEqual(caught.exception.reasons[0]["gate"], "env-order")
        self.store.promote(artifact["artifactId"], "dev", actor="alice")
        self.store.promote(artifact["artifactId"], "test", actor="alice")  # now passes

    def test_protected_envs_require_second_person(self):
        artifact = self.register()
        self.store.promote(artifact["artifactId"], "dev", actor="alice")
        self.store.promote(artifact["artifactId"], "test", actor="alice")
        with self.assertRaises(GateRejected) as caught:
            self.store.promote(artifact["artifactId"], "staging", actor="alice")
        gates = {r["gate"]: r["reason"] for r in caught.exception.reasons}
        self.assertIn("approval", gates)
        self.assertIn("second-person", gates["approval"])
        with self.assertRaises(GateRejected) as caught:
            self.store.promote(artifact["artifactId"], "staging", actor="alice", approver="alice")
        self.assertIn("同人禁审", caught.exception.reasons[0]["reason"])
        result = self.store.promote(artifact["artifactId"], "staging", actor="alice", approver="bob")
        self.assertEqual(result["approver"], "bob")

    def test_rollback_rereuns_the_guard_and_is_audited(self):
        old = self.register()
        new = self.register(blob=b"artifact-bytes-v2")
        self.store.promote(old["artifactId"], "dev", actor="alice")
        self.store.promote(old["artifactId"], "test", actor="alice")
        self.store.promote(new["artifactId"], "dev", actor="alice")
        self.store.promote(new["artifactId"], "test", actor="alice")
        # old 仍可回滚 test：它在 dev 有通过记录（守卫照常，不要求当前指针）
        result = self.store.promote(old["artifactId"], "test", actor="alice")
        self.assertTrue(result["rollback"])
        self.assertEqual(self.store.pointer("test")["artifactId"], old["artifactId"])
        events = [e["event"] for e in self.store.audit()]
        self.assertIn("rollback", events)


class CliTests(DeliveryTestBase):
    def test_cli_promote_exit_codes(self):
        artifact = self.register()
        argv = ["--store", str(self.store.path), "promote", artifact["artifactId"], "staging", "--actor", "alice"]
        # staging 未走链 → 门禁否定 exit 1
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli_main(argv + ["--approver", "bob"])
        self.assertEqual(code, 1)
        envelope = json.loads(out.getvalue())
        self.assertEqual(envelope["protocol"], "microflow-delivery-v1")
        self.assertEqual(envelope["exit"], 1)
        self.assertEqual(envelope["gates"][0]["gate"], "env-order")

        for env, approver in (("dev", None), ("test", None), ("staging", "bob"), ("online", "carol")):
            argv = ["--store", str(self.store.path), "promote", artifact["artifactId"], env,
                    "--actor", "alice"]
            if approver:
                argv += ["--approver", approver]
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli_main(argv)
            self.assertEqual(code, 0, out.getvalue())

    def test_cli_unknown_artifact_is_request_failure(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli_main(["--store", str(self.store.path), "show", "sha256:" + "0" * 64])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out.getvalue())["diagnostic"]["error_code"], "UNKNOWN_ARTIFACT")


class ServiceTests(DeliveryTestBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(create_app(self.store))

    def test_promote_via_rest_with_gate_rejection_conflict(self):
        artifact = self.register()
        response = self.client.post(f"/api/v1/artifacts/{artifact['artifactId']}/promote",
                                    json={"env": "test", "actor": "alice"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "GATE_REJECTED")
        self.client.post(f"/api/v1/artifacts/{artifact['artifactId']}/promote",
                         json={"env": "dev", "actor": "alice"})
        response = self.client.post(f"/api/v1/artifacts/{artifact['artifactId']}/promote",
                                    json={"env": "test", "actor": "alice"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)
        self.assertEqual(response.json()["data"]["pointer"]["env"], "test")

    def test_unknown_artifact_is_404(self):
        response = self.client.post(f"/api/v1/artifacts/sha256:{'0' * 64}/promote",
                                    json={"env": "dev", "actor": "alice"})
        self.assertEqual(response.status_code, 404)

    def test_read_endpoints(self):
        artifact = self.register()
        self.assertEqual(len(self.client.get("/api/v1/artifacts").json()["data"]["artifacts"]), 1)
        self.assertEqual(self.client.get(f"/api/v1/artifacts/{artifact['artifactId']}").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/pointers").json()["data"]["pointers"], [])
        self.assertEqual(len(self.client.get("/api/v1/audit").json()["data"]["events"]), 1)


if __name__ == "__main__":
    unittest.main()
