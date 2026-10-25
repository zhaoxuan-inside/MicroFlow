import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from microflow import cli
from microflow.codes import DIAGNOSTICS, PROTOCOL, describe_diagnostics

EXPECTED_COMMANDS = {"capabilities", "check", "describe", "diagnostics", "impact",
                     "operators", "policy-check", "policy-schema", "run", "schema"}

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
        for path in sorted(source.glob("*.py")):
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
            code, result = self._run(["policy-check", str(good)])
            self.assertEqual(code, 0)
            self.assertTrue(result["policyChecked"])
            self.assertEqual(result["topLevelFields"], ["durability"])
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"unknown_field": 1}), encoding="utf-8")
            code, result = self._run(["policy-check", str(bad)])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_POLICY_FIELD")

    def test_schema_and_operators_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ops.py").write_text(MODULE, encoding="utf-8")
            project = root / "project.json"
            project.write_text(json.dumps({"modules": ["ops.py"], "flows": flows()}),
                               encoding="utf-8")
            code, result = self._run(["schema", str(project), "ints", "--ephemeral"])
            self.assertEqual(code, 0)
            self.assertEqual(result["definition"], INTS)
            code, result = self._run(["schema", str(project), "absent", "--ephemeral"])
            self.assertEqual(code, 2)
            self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_SCHEMA")
            code, result = self._run(["operators", str(project), "--ephemeral"])
            self.assertEqual(code, 0)
            entry = result["operators"][0]
            self.assertEqual(entry["ref"], "increment@1")
            self.assertEqual(entry["staticReferences"], 3)
            self.assertEqual(entry["referencingFlows"], ["double", "main"])
            self.assertIn("defaultPolicy", entry)


if __name__ == "__main__":
    unittest.main()
