"""Acceptance A1-A5 and A12: deterministic projection, honest gaps, hard gates."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock
from pathlib import Path

from microflow_registry import cli
from microflow_registry.codes import PROTOCOL

from . import fixtures

STUB = Path(__file__).resolve().parent / "stub_cli.py"


def run(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(argv)
    return code, json.loads(out.getvalue())


class ProjectionTests(unittest.TestCase):
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

    def export(self, project, *extra, group="dev", namespace="demo"):
        return run(["export", str(project), "--namespace", namespace, "--group", group,
                    "--ephemeral", *extra])

    # A1
    def test_export_is_deterministic(self):
        project = fixtures.write_project(self.root / "p1")
        first_code, first = self.export(project)
        out_file = self.root / "report.json"
        second_code, second = self.export(project, "--out", str(out_file))
        self.assertEqual((first_code, second_code), (0, 0))
        self.assertEqual(first, second)
        self.assertEqual(first["protocol"], PROTOCOL)
        self.assertEqual(out_file.read_text(encoding="utf-8").strip(),
                         json.dumps(first, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":")))

    # A2 (with the framework's path-dependent releaseId kept as truth)
    def test_digest_stable_across_paths(self):
        left = fixtures.write_project(self.root / "a" / "proj")
        right = fixtures.write_project(self.root / "b" / "proj")
        _, first = self.export(left)
        _, second = self.export(right)
        self.assertEqual(first["project"]["digest"], second["project"]["digest"])
        self.assertEqual(first["contentDigest"], second["contentDigest"])
        self.assertEqual(first["assets"][0]["source"]["path"], "ops.py")
        self.assertEqual(first["assets"][0]["digest"], second["assets"][0]["digest"])
        # Documented framework fact: releaseId hashes a manifest keyed by absolute
        # source paths, so it moves with the checkout directory. The registry keeps
        # it as truth and uses contentDigest as the portable key.
        self.assertNotEqual(first["project"]["releaseId"], second["project"]["releaseId"])
        self.assertNotEqual(first["digest"], second["digest"])

    # A3
    def test_asset_digest_tracks_source(self):
        project = fixtures.write_project(self.root / "p")
        _, before = self.export(project)
        module = (self.root / "p" / "ops.py").read_text(encoding="utf-8")
        (self.root / "p" / "ops.py").write_text(module.replace('adds one', 'adds two'),
                                                encoding="utf-8")
        _, after = self.export(project)
        self.assertNotEqual(before["assets"][0]["digest"], after["assets"][0]["digest"])
        self.assertNotEqual(before["project"]["releaseId"], after["project"]["releaseId"])

    # A12
    def test_effective_policy_is_declared_unavailable(self):
        project = fixtures.write_project(self.root / "p")
        code, report = self.export(project)
        self.assertEqual(code, 0)
        policy = report["policy"]
        self.assertEqual(policy["effective"], "unavailable")
        self.assertTrue(policy["reason"])
        self.assertTrue(policy["hint"])
        for key in ("schemaDigest", "defaultsDigest", "mergeDigest"):
            self.assertEqual(len(policy[key]), 64)
        self.assertEqual(report["diagnostics"], [])

    def test_export_requires_ephemeral(self):
        project = fixtures.write_project(self.root / "p")
        code, payload = run(["export", str(project), "--namespace", "demo", "--group", "dev"])
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "EPHEMERAL_REQUIRED")

    def test_bad_addressing_key_is_rejected(self):
        project = fixtures.write_project(self.root / "p")
        code, payload = self.export(project, namespace="../escape")
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "INVALID_ADDRESSING")

    # A4
    def test_export_gates_on_diagnostics(self):
        project = fixtures.write_project(self.root / "p")
        patcher = mock.patch.dict(os.environ, {"MF_REGISTRY_CLI": f"{sys.executable} {STUB}"})
        patcher.start()
        self.addCleanup(patcher.stop)
        code, payload = self.export(project)
        self.assertEqual(code, 1)
        self.assertEqual(payload["diagnostic"]["error_code"], "PROJECT_CHECK_FAILED")
        self.assertIn("STUB_DIAGNOSTIC", payload["diagnostic"]["message"])

    def test_compile_error_is_a_request_failure_not_a_gate_negative(self):
        root = self.root / "broken"
        root.mkdir()
        (root / "ops.py").write_text(fixtures.MODULE, encoding="utf-8")
        project = root / "project.json"
        project.write_text(json.dumps({"modules": ["ops.py"], "flows": [
            {"id": "main", "input_schema": "ints", "output_schema": "ints",
             "nodes": {"a": {"operator": "increment@1",
                             "bogus": {"from": "flow.input.n"}}},
             "outputs": {"n": {"from": "nodes.a.output.data.n"}}}]}), encoding="utf-8")
        code, payload = self.export(project)
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "CLI_FAILED")

    # A5
    def test_missing_cli_command_is_rejected(self):
        project = fixtures.write_project(self.root / "p")
        patcher = mock.patch.dict(
            os.environ, {"MF_REGISTRY_CLI": f"{sys.executable} {STUB}", "STUB_MODE": "missing"})
        patcher.start()
        self.addCleanup(patcher.stop)
        code, payload = self.export(project)
        self.assertEqual(code, 2)
        self.assertEqual(payload["diagnostic"]["error_code"], "UNSUPPORTED_COMMAND")
        self.assertIn("operators", payload["diagnostic"]["message"])

    def test_capabilities_declares_only_implemented_commands(self):
        code, payload = run(["capabilities"])
        self.assertEqual(code, 0)
        self.assertEqual(set(payload["commands"]),
                         {"capabilities", "diagnostics", "export", "push", "status", "stream"})
        self.assertEqual(payload["requires"]["cliProtocol"], "microflow-cli-v1")

    def test_diagnostics_catalog_is_exposed(self):
        code, payload = run(["diagnostics"])
        self.assertEqual(code, 0)
        self.assertEqual(payload["count"], len(payload["diagnostics"]))
        codes = [entry["code"] for entry in payload["diagnostics"]]
        self.assertEqual(codes, sorted(codes))


if __name__ == "__main__":
    unittest.main()
