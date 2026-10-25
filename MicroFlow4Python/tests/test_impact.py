import io
import json
import random
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from microflow import cli
from microflow.compiler import compile_release
from microflow.errors import ContractError
from microflow.impact import (build_index, describe_index, flow_references, operator_flows,
                              operator_references, upstream_flows)
from microflow.registry import Registry

EPHEMERAL = {"durability": "ephemeral", "recovery": {"enabled": False}}
INTS = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
INT_LIST = {"type": "array", "items": {"type": "integer"}}
MAIN_IN = {"type": "object",
           "properties": {"n": {"type": "integer"}, "items": INT_LIST},
           "required": ["n", "items"]}


def increment(input, output, context, metrix, debug, log):
    output.set("n", input["n"] + 1)
    return True


def registry():
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
                  "inputs": {"n": {"from": "nodes.calc.output.data.n", "required": True}}},
        "fan": {"type": "map", "flow": "double", "items": "flow.input.items", "max_items": 4,
                "depends_on": ["calc"]}},
        "outputs": {"n": {"from": "nodes.embed.output.data.n", "required": True}}}
    return [main, double]


def index():
    return build_index(compile_release(registry(), flows(), defaults=EPHEMERAL))


class ImpactIndexTests(unittest.TestCase):
    def test_operator_references_are_complete_and_ordered(self):
        result = index()
        self.assertEqual([(r.flow, r.node, r.kind) for r in operator_references(result, "increment@1")],
                         [("double", "first", "operator"), ("double", "second", "operator"),
                          ("main", "calc", "operator")])
        self.assertEqual(operator_flows(result, "increment@1"), ("double", "main"))

    def test_subflow_references_kinds_roots_and_upstream_closure(self):
        result = index()
        self.assertEqual([(r.flow, r.node, r.kind) for r in flow_references(result, "double")],
                         [("main", "embed", "subflow"), ("main", "fan", "map")])
        self.assertEqual(result.flows, ("double", "main"))
        self.assertEqual(result.roots, ("main",))
        self.assertEqual(upstream_flows(result, "double"), ("main",))
        self.assertEqual(upstream_flows(result, "main"), ())

    def test_describe_index_is_deterministic_and_independent(self):
        first = describe_index(index())
        rng = random.Random(7)
        shuffled = flows()
        rng.shuffle(shuffled)
        second = describe_index(build_index(compile_release(registry(), shuffled, defaults=EPHEMERAL)))
        self.assertEqual(first, second)
        first["flows"].append("mutated")
        self.assertNotIn("mutated", describe_index(index())["flows"])

    def test_unknown_and_unused_queries_are_distinguishable(self):
        result = index()
        self.assertIn("increment@1", result.registered_operators)
        with self.assertRaises(ContractError):
            operator_references(result, "absent@1")
        with self.assertRaises(ContractError):
            flow_references(result, "absent")
        with self.assertRaises(ContractError):
            upstream_flows(result, "absent")

    def test_registered_but_unreferenced_operator_is_a_valid_empty_state(self):
        reg = registry()
        def idle(input, output, context, metrix, debug, log):
            return True
        reg.register_operator(name="idle", version="1", method=idle,
                              input_schema="ints", output_schema="ints")
        result = build_index(compile_release(reg, flows(), defaults=EPHEMERAL))
        self.assertIn("idle@1", result.registered_operators)
        self.assertEqual(operator_references(result, "idle@1"), ())
        self.assertEqual(operator_flows(result, "idle@1"), ())


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


class ImpactCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "ops.py").write_text(MODULE, encoding="utf-8")
        project = {"modules": ["ops.py"], "flows": flows()}
        self.project = root / "project.json"
        self.project.write_text(json.dumps(project), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(argv)
        return code, json.loads(out.getvalue())

    def test_full_index_and_operator_query(self):
        code, result = self._run(["impact", str(self.project), "--ephemeral"])
        self.assertEqual(code, 0)
        body = result["impact"]
        self.assertEqual(body["protocol"], "microflow-impact-index-v1")
        self.assertEqual(body["roots"], ["main"])
        code, result = self._run(["impact", str(self.project), "--ephemeral", "--operator", "increment@1"])
        self.assertEqual(code, 0)
        body = result["impact"]
        self.assertEqual(body["operator"], "increment@1")
        self.assertEqual(len(body["references"]), 3)
        self.assertEqual(body["flows"], ["double", "main"])
        self.assertEqual(body["upstream_flows"], ["main"])

    def test_flow_query_and_unknown_operator_diagnostic(self):
        code, result = self._run(["impact", str(self.project), "--ephemeral", "--flow", "double"])
        self.assertEqual(code, 0)
        self.assertEqual([(r["node"], r["kind"]) for r in result["impact"]["references"]],
                         [("embed", "subflow"), ("fan", "map")])
        code, result = self._run(["impact", str(self.project), "--ephemeral", "--operator", "absent@1"])
        self.assertEqual(code, 2)
        self.assertEqual(result["diagnostic"]["error_code"], "UNKNOWN_OPERATOR")


if __name__ == "__main__":
    unittest.main()
