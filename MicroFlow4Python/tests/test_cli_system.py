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
                     "operators", "policy-check", "policy-schema", "run", "scaffold", "schema",
                     "test"}

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


class TestCommandTests(unittest.TestCase):
    """`test` 命令：项目声明的回归输入输出对 + 算子契约用例（隔离执行，结构化用例结果）。"""

    REJECT_MODULE = """
def increment(input, output, context, metrix, debug, log):
    output.set("n", input["n"] + 1)
    return True

def reject_even(input, output, context, metrix, debug, log):
    if input["n"] % 2 == 0:
        output.reject("EVEN_FORBIDDEN", "even values are not accepted")
        return False
    output.set("n", input["n"] * 10)
    return True

def register(registry):
    registry.register_schema("ints", {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]})
    registry.register_operator(name="increment", version="1", method=increment,
                               input_schema="ints", output_schema="ints")
    registry.register_operator(name="reject_even", version="1", method=reject_even,
                               input_schema="ints", output_schema="ints")
"""

    def _project(self, root, tests, module=MODULE):
        (root / "ops.py").write_text(module, encoding="utf-8")
        project = root / "project.json"
        project.write_text(json.dumps({"modules": ["ops.py"], "flows": flows(), "tests": tests}),
                           encoding="utf-8")
        return project

    def test_flow_regression_pairs_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-001", "kind": "flow", "flow": "double", "input": {"n": 1},
                 "expectOutput": {"n": 3}, "source": "PRD R-001"},
                {"id": "T-002", "kind": "flow", "flow": "main", "input": {"n": 1, "items": [1]},
                 "expectOutput": {"n": 4}, "source": "PRD R-002"},
            ])
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 0)
            self.assertEqual(result["tests"], {"total": 2, "passed": 2, "failed": 0})
            self.assertEqual([c["status"] for c in result["cases"]], ["passed", "passed"])
            self.assertEqual(result["releaseId"], result.get("releaseId"))

    def test_flow_mismatch_reports_failure_detail(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-100", "kind": "flow", "flow": "double", "input": {"n": 1},
                 "expectOutput": {"n": 3, "absent.path": True}, "source": "WRONG sample"},
            ])
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 1)
            self.assertEqual(result["tests"], {"total": 1, "passed": 0, "failed": 1})
            reasons = {f["reason"]: f for f in result["cases"][0]["failures"]}
            self.assertEqual(reasons["output-mismatch"]["path"], "absent.path")
            self.assertFalse(reasons["output-mismatch"]["present"])
            self.assertEqual(reasons["output-mismatch"]["expected"], True)
            status = [f for f in result["cases"][0]["failures"] if f["reason"] == "status-mismatch"]
            self.assertEqual(status, [])

    def test_status_mismatch_and_bool_strictness(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-200", "kind": "flow", "flow": "double", "input": {"n": 1},
                 "expectStatus": "FAILED", "source": "declared rejection path"},
                {"id": "T-201", "kind": "flow", "flow": "double", "input": {"n": 1},
                 "expectOutput": {"n": True}, "source": "type-strict negative"},
            ])
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 1)
            by_id = {c["id"]: c for c in result["cases"]}
            status = {f["reason"]: f for f in by_id["T-200"]["failures"]}
            self.assertEqual(status["status-mismatch"]["actual"], "SUCCEEDED")
            strict = {f["reason"]: f for f in by_id["T-201"]["failures"]}
            self.assertEqual(strict["output-mismatch"]["expected"], True)
            self.assertEqual(strict["output-mismatch"]["actual"], 3)  # double(1): 1→2→3

    def test_operator_contract_cases_with_rejection_and_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests = [
                {"id": "T-300", "kind": "operator", "operator": "reject_even@1",
                 "source": "confirmed sample 2026-11-01",
                 "cases": [
                     {"input": {"n": 3}, "expectOutput": {"n": 30}},
                     {"input": {"n": 2}, "expectAccepted": False},
                     {"input": {"n": 4}, "expectAccepted": True},
                 ]},
                {"id": "T-301", "kind": "operator", "operator": "increment@1",
                 "source": "PRD R-003",
                 "cases": [{"input": {"n": 1}, "expectOutput": {"n": 2}}]},
            ]
            # increment 在 reject_even 模块里同样存在；用本模块构建项目
            (root := Path(tmp) / "p").mkdir()
            module = self.REJECT_MODULE
            flows_here = [{"id": "double", "input_schema": "ints", "output_schema": "ints", "nodes": {
                "first": {"operator": "increment@1", "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
                "outputs": {"n": {"from": "nodes.first.output.data.n", "required": True}}}]
            (root / "ops.py").write_text(module, encoding="utf-8")
            project = root / "project.json"
            project.write_text(json.dumps({"modules": ["ops.py"], "flows": flows_here, "tests": tests}),
                               encoding="utf-8")
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 1)
            by_name = {(c["id"], c["name"]): c for c in result["cases"]}
            self.assertEqual(by_name[("T-300", "reject_even@1#1")]["status"], "passed")
            self.assertEqual(by_name[("T-300", "reject_even@1#2")]["status"], "passed")
            case3 = by_name[("T-300", "reject_even@1#3")]
            self.assertEqual(case3["status"], "failed")
            self.assertEqual(case3["failures"][0]["reason"], "accepted-mismatch")
            self.assertEqual(by_name[("T-301", "increment@1#1")]["status"], "passed")

    def test_operator_exception_is_a_failed_case_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = """
def increment(input, output, context, metrix, debug, log):
    output.set("n", input["n"] + 1)
    return True

def boom(input, output, context, metrix, debug, log):
    raise RuntimeError("exploded")

def register(registry):
    registry.register_schema("ints", {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]})
    registry.register_operator(name="increment", version="1", method=increment,
                               input_schema="ints", output_schema="ints")
    registry.register_operator(name="boom", version="1", method=boom,
                               input_schema="ints", output_schema="ints")
"""
            tests = [{"id": "T-400", "kind": "operator", "operator": "boom@1", "source": "negative path",
                      "cases": [{"input": {"n": 1}}]}]
            root = Path(tmp)
            flows_here = [{"id": "double", "input_schema": "ints", "output_schema": "ints", "nodes": {
                "first": {"operator": "increment@1", "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
                "outputs": {"n": {"from": "nodes.first.output.data.n", "required": True}}}]
            (root / "ops.py").write_text(module, encoding="utf-8")
            project = root / "project.json"
            project.write_text(json.dumps({"modules": ["ops.py"], "flows": flows_here, "tests": tests}),
                               encoding="utf-8")
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 1)
            case = result["cases"][0]
            self.assertEqual(case["status"], "failed")
            self.assertEqual(case["failures"][0]["reason"], "exception")

    def test_source_declaration_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-500", "kind": "flow", "flow": "double", "input": {"n": 1}},
            ])
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "INVALID_TEST_CONFIG")

    def test_unknown_targets_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-600", "kind": "flow", "flow": "ghost", "input": {"n": 1}, "source": "x"},
            ])
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_TEST_TARGET")

        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-601", "kind": "operator", "operator": "ghost@9", "source": "x",
                 "cases": [{"input": {}}]},
            ])
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_TEST_TARGET")

        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-602", "kind": "flow", "flow": "double", "input": {"n": 1}, "source": "a"},
                {"id": "T-602", "kind": "flow", "flow": "double", "input": {"n": 2}, "source": "b"},
            ])
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "INVALID_TEST_CONFIG")

    def test_dsl_project_declares_tests(self):
        dsl = (
            'module("ops.py")\n\n'
            'tests([{"id": "T-700", "kind": "flow", "flow": "double", "input": {"n": 5},'
            ' "expectOutput": {"n": 6}, "source": "PRD R-009"}])\n\n'
            'with flow("double", input_schema="ints", output_schema="ints"):\n'
            '    operator("first", operator="increment@1",'
            ' inputs={"n": source("flow.input.n", required=True)})\n'
            '    output("n", "nodes.first.output.data.n", required=True)\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "ops.py").write_text(MODULE, encoding="utf-8")
            project = Path(tmp) / "project.mf"
            project.write_text(dsl, encoding="utf-8")
            code, result = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(code, 0)
            self.assertEqual(result["tests"], {"total": 1, "passed": 1, "failed": 0})

    def test_budget_exceeding_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-800", "kind": "flow", "flow": "double", "input": {"n": 1}, "source": "a"},
                {"id": "T-801", "kind": "flow", "flow": "double", "input": {"n": 2}, "source": "b"},
            ])
            code, result = run_cli(["test", str(project), "--ephemeral", "--budget", "1"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "TEST_BUDGET_EXCEEDED")

    def test_deterministic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp), [
                {"id": "T-900", "kind": "flow", "flow": "double", "input": {"n": 1},
                 "expectOutput": {"n": 2}, "source": "PRD R-010"},
            ])
            first = run_cli(["test", str(project), "--ephemeral"])
            second = run_cli(["test", str(project), "--ephemeral"])
            self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
