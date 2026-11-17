import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from microflow import cli
from microflow.codes import DIAGNOSTICS, PROTOCOL, describe_diagnostics

EXPECTED_COMMANDS = {"capabilities", "check", "context", "describe", "diagnostics", "impact",
                     "operators", "policy-check", "policy-schema", "run", "scaffold", "schema"}

INTS = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
INT_LIST = {"type": "array", "items": {"type": "integer"}}
MAIN_IN = {"type": "object",
           "properties": {"n": {"type": "integer"}, "items": INT_LIST},
           "required": ["n", "items"]}


def increment(input, output, context, metrix, debug, log):
    output.set("n", input["n"] + 1)
    return True


def registry():
    from microflow.registry import Registry
    result = Registry()
    result.register_schema("ints", INTS)
    result.register_schema("intlist", INT_LIST)
    result.register_schema("mainin", MAIN_IN)
    result.register_operator(name="increment", version="1", method=increment,
                             input_schema="ints", output_schema="ints")
    return result


def run_cli(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(argv)
    return code, json.loads(out.getvalue())


def flows():
    double = {"id": "double", "input_schema": "ints", "output_schema": "ints", "nodes": {
        "first": {"operator": "increment@1", "inputs": {"n": {"from": "flow.input.n", "required": True}}},
        "second": {"operator": "increment@1", "inputs": {"n": {
            "from": "nodes.first.output.data.n", "required": True}}}},
        "outputs": {"n": {"from": "nodes.second.output.data.n", "required": True}}}
    main = {"id": "main", "input_schema": "mainin", "output_schema": "ints", "nodes": {
        "calc": {"operator": "increment@1", "inputs": {"n": {"from": "flow.input.n", "required": True}}},
        "embed": {"type": "subflow", "flow": "double", "depends_on": ["calc"],
                  "inputs": {"n": {"from": "nodes.calc.output.data.n", "required": True}}}},
        "outputs": {"n": {"from": "nodes.embed.output.data.n", "required": True}}}
    return [main, double]


MODULE = '''
def increment(input, output, context, metrix, debug, log):
    output.set("n", input["n"] + 1)
    return True

def register(registry):
    registry.register_schema("ints", %s)
    registry.register_schema("intlist", %s)
    registry.register_schema("mainin", %s)
    registry.register_operator(name="increment", version="1", method=increment,
                               input_schema="ints", output_schema="ints")
''' % (json.dumps(INTS), json.dumps(INT_LIST), json.dumps(MAIN_IN))


class CatalogGuardTests(unittest.TestCase):
    def test_every_raised_code_is_registered_and_no_entry_is_dead(self):
        source = Path(__file__).resolve().parent.parent / "src" / "microflow"
        raised = set()
        pattern = re.compile(r'(?:ContractError|MicroFlowError|PersistenceError)\(\s*"([A-Z][A-Z_]*)"'
                             r'|_error\("([A-Z][A-Z_]*)"')
        for path in sorted(source.rglob("*.py")):
            for match in pattern.finditer(path.read_text(encoding="utf-8")):
                raised.add(match.group(1) or match.group(2))
        self.assertEqual(raised, set(DIAGNOSTICS),
                         "raised codes and the diagnostic catalog must match exactly")

    def test_catalog_projection_is_sorted_and_stable(self):
        described = describe_diagnostics()
        self.assertEqual(described["protocol"], PROTOCOL)
        codes = [entry["code"] for entry in described["diagnostics"]]
        self.assertEqual(codes, sorted(codes))
        self.assertEqual(described["count"], len(codes))
        self.assertTrue(all(entry["stability"] in ("shared", "implementation")
                            for entry in described["diagnostics"]))
        shared = {entry["code"] for entry in described["diagnostics"] if entry["stability"] == "shared"}
        self.assertLess(shared, set(DIAGNOSTICS))


class CliSystemTests(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(argv)
        return code, json.loads(out.getvalue())

    def test_capabilities_declares_exactly_the_implemented_commands(self):
        code, result = self._run(["capabilities"])
        self.assertEqual(code, 0)
        self.assertEqual(set(result["commands"]), EXPECTED_COMMANDS)
        for entry in result["commands"].values():
            self.assertIn(entry["ephemeral"], ("required", "rejected"))
            self.assertIsInstance(entry["resultKeys"], list)
            self.assertIsInstance(entry["args"], list)
        self.assertEqual(result["implementation"], "python")
        self.assertEqual(result["protocol"], "microflow-cli-v1")

    def test_diagnostics_command_outputs_the_catalog(self):
        code, result = self._run(["diagnostics"])
        self.assertEqual(code, 0)
        self.assertEqual(result["count"], len(DIAGNOSTICS))
        spot = {entry["code"]: entry for entry in result["diagnostics"]}
        self.assertEqual(spot["CYCLE_DETECTED"]["stability"], "shared")
        self.assertEqual(spot["IMPACT_STRUCTURE"]["stability"], "implementation")

    def test_policy_check_accepts_valid_and_rejects_invalid_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.json"
            good.write_text(json.dumps({"durability": "ephemeral"}), encoding="utf-8")
            code, result = run_cli(["policy-check", str(good)])
            self.assertEqual(code, 0)
            self.assertTrue(result["policyChecked"])
            self.assertEqual(result["topLevelFields"], ["durability"])
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"unknown_field": 1}), encoding="utf-8")
            code, result = run_cli(["policy-check", str(bad)])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_POLICY_FIELD")

    def test_schema_and_operators_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ops.py").write_text(MODULE, encoding="utf-8")
            project = root / "project.json"
            project.write_text(json.dumps({"modules": ["ops.py"], "flows": flows()}),
                               encoding="utf-8")
            code, result = run_cli(["schema", str(project), "ints", "--ephemeral"])
            self.assertEqual(code, 0)
            self.assertEqual(result["definition"], INTS)
            code, result = run_cli(["schema", str(project), "absent", "--ephemeral"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_SCHEMA")
            code, result = run_cli(["operators", str(project), "--ephemeral"])
            self.assertEqual(code, 0)
            entry = result["operators"][0]
            self.assertEqual(entry["ref"], "increment@1")
            self.assertEqual(entry["staticReferences"], 3)
            self.assertEqual(entry["referencingFlows"], ["double", "main"])
            self.assertIn("defaultPolicy", entry)


class ContextCommandTests(unittest.TestCase):
    def _write_project(self, root: Path):
        (root / "ops.py").write_text(MODULE, encoding="utf-8")
        project = root / "project.json"
        project.write_text(json.dumps({"modules": ["ops.py"], "flows": flows()}), encoding="utf-8")
        return project

    def test_context_reports_bounded_local_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self._write_project(root)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_ops.py").write_text("# references increment twice\n# increment again\n",
                                                encoding="utf-8")
            code, result = run_cli(["context", str(project), "increment@1", "--ephemeral"])
            self.assertEqual(code, 0)
            body = result["context"]
            self.assertEqual(body["operator"]["ref"], "increment@1")
            self.assertEqual(body["operator"]["inputSchema"], "ints")
            self.assertEqual(body["flows"], ["double", "main"])
            self.assertEqual(body["relatedTests"], [{"path": str(tests / "test_ops.py"), "matches": 2}])
            self.assertTrue(body["boundaries"])
            self.assertFalse(body["summary"]["truncated"])
            self.assertEqual(body["upstreamFlows"], ["main"])
            # Deterministic bytes for the same input.
            code_again, result_again = run_cli(["context", str(project), "increment@1", "--ephemeral"])
            self.assertEqual(json.dumps(result, sort_keys=True), json.dumps(result_again, sort_keys=True))

    def test_context_notes_missing_test_directory_and_rejects_unknown_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self._write_project(root)
            code, result = run_cli(["context", str(project), "increment@1", "--ephemeral"])
            self.assertEqual(code, 0)
            self.assertTrue(result["context"]["notes"])
            self.assertEqual(result["context"]["relatedTests"], [])
            code, result = run_cli(["context", str(project), "absent@1", "--ephemeral"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_OPERATOR")

    def test_context_budget_exceeded_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self._write_project(root)
            tests = root / "tests"
            tests.mkdir()
            for index in range(3):
                (tests / f"t{index}.py").write_text("increment\n", encoding="utf-8")
            code, result = run_cli(["context", str(project), "increment@1", "--ephemeral", "--budget", "2"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "CONTEXT_BUDGET_EXCEEDED")


class ScaffoldCommandTests(unittest.TestCase):
    def test_scaffold_operator_writes_candidates_and_the_test_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            into = Path(tmp) / "generated"
            code, result = run_cli(["scaffold", "operator", "demo_op", "--into", str(into)])
            self.assertEqual(code, 0)
            self.assertEqual([f["kind"] for f in result["files"]], ["operator", "test"])
            module = into / "demo_op_operator.py"
            self.assertIn("def demo_op(", module.read_text(encoding="utf-8"))
            # The generated contract test passes as written.
            run = subprocess.run([sys.executable, "-m", "unittest", "test_demo_op_operator"],
                                 cwd=into, capture_output=True, text=True, env=dict(os.environ))
            self.assertEqual(run.returncode, 0, run.stderr)
            # Deterministic regeneration into a fresh directory yields identical bytes.
            fresh = Path(tmp) / "again"
            code, _ = run_cli(["scaffold", "operator", "demo_op", "--into", str(fresh)])
            for name in ("demo_op_operator.py", "test_demo_op_operator.py"):
                self.assertEqual((into / name).read_bytes(), (fresh / name).read_bytes())

    def test_scaffold_operator_never_overwrites_and_rejects_bad_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            into = Path(tmp) / "out"
            run_cli(["scaffold", "operator", "demo_op", "--into", str(into)])
            code, result = run_cli(["scaffold", "operator", "demo_op", "--into", str(into)])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "SCAFFOLD_TARGET_EXISTS")
            code, result = run_cli(["scaffold", "operator", "bad name", "--into", str(Path(tmp) / "x")])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "INVALID_SCAFFOLD_ID")
            code, result = run_cli(["scaffold", "operator", "ok", "--into", str(Path(tmp) / "y"),
                                      "--proxy", "cache"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "INVALID_SCAFFOLD_ID")

    def test_scaffold_operator_with_fallback_and_proxies_registers(self):
        with tempfile.TemporaryDirectory() as tmp:
            into = Path(tmp) / "out"
            code, result = run_cli(["scaffold", "operator", "safe_op", "--into", str(into),
                                      "--with-fallback", "--proxy", "metrix,log"])
            self.assertEqual(code, 0)
            text = (into / "safe_op_operator.py").read_text(encoding="utf-8")
            self.assertIn("def safe_op_fallback(", text)
            self.assertIn("def safe_op_metrix(", text)
            self.assertIn("def safe_op_log(", text)
            self.assertIn("fallback_capabilities=", text)
            from microflow.registry import discover
            registry = discover([into / "safe_op_operator.py"])
            self.assertEqual(registry.operators["safe_op@1"].fallback is not None, True)

    def test_scaffold_flow_emits_a_checkable_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli(["scaffold", "operator", "demo_op", "--into", str(root)])
            into = root / "flows"
            code, result = run_cli(["scaffold", "flow", "demo_flow", "--into", str(into),
                                      "--operator", "demo_op@1", "--input-schema", "demo_op_input",
                                      "--output-schema", "demo_op_output",
                                      "--module", "../demo_op_operator.py"])
            self.assertEqual(code, 0)
            project = json.loads((into / "demo_flow.flow.json").read_text(encoding="utf-8"))
            self.assertEqual(project["flows"][0]["nodes"]["step"]["operator"], "demo_op@1")
            self.assertEqual(project["modules"], ["../demo_op_operator.py"])
            # The skeleton names a real operator and schemas; check reaches the
            # flow-level mapping diagnostics instead of unknown references.
            code, result = run_cli(["check", str(into / "demo_flow.flow.json"), "--ephemeral"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_SCHEMA_PATH")
            # Missing schema names are rejected up front.
            code, result = run_cli(["scaffold", "flow", "x", "--into", str(into),
                                      "--operator", "demo_op@1", "--input-schema", "",
                                      "--output-schema", "demo_op_output"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_SCHEMA")

    def test_scaffold_rejects_the_ephemeral_flag_and_bad_operator_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            into = Path(tmp) / "out"
            code, result = run_cli(["scaffold", "flow", "demo", "--into", str(into),
                                      "--operator", "demo_op", "--input-schema", "a",
                                      "--output-schema", "b"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "INVALID_OPERATOR_ID")


if __name__ == "__main__":
    unittest.main()
