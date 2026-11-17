"""Canvas graph -> flow skeleton conversion (platform_graph)."""
import json
import unittest

from microflow.compiler import compile_release
from microflow.errors import ContractError
from microflow.platform_graph import CANVAS_PROTOCOL, convert_canvas_graph
from microflow.registry import Registry
from microflow.runtime import LocalRuntime
from tests.test_compiler import EPHEMERAL, INTEGER_MAP, method

# The skeleton maps the exit node's whole output object onto the flow output
# schema, so the compatible hand-declared output schema is an open object
# carrying one property named "result" (the skeleton's single output mapping).
OUTS = {"type": "object", "properties": {"result": {"type": "object", "additionalProperties": True}},
        "required": ["result"]}

CANVAS = {
    "entry_node": "start",
    "exit_node": "finish",
    "nodes": [
        {"id": "start", "kind": "OPERATOR", "operator": "increment", "operator_version": "1"},
        {"id": "middle", "kind": "OPERATOR", "operator": "increment", "operator_version": "1",
         "timeout_ms": 1500},
        {"id": "finish", "kind": "OPERATOR", "operator": "increment", "operator_version": "1"},
    ],
    "edges": [{"from_node": "start", "to_node": "middle"}, {"from_node": "middle", "to_node": "finish"}],
}


def registry():
    result = Registry()
    result.register_schema("ints", INTEGER_MAP)
    result.register_schema("outs", OUTS)
    result.register_operator(name="increment", version="1", method=method,
                             input_schema="ints", output_schema="ints")
    return result


class CanvasConversionTests(unittest.TestCase):
    def test_skeleton_has_stable_nodes_edges_and_timeout_policy(self):
        result = convert_canvas_graph(CANVAS, "example", input_schema="ints", output_schema="outs")
        self.assertEqual(result["protocol"], CANVAS_PROTOCOL)
        flow = result["flow"]
        self.assertEqual(flow["id"], "example")
        self.assertEqual(sorted(flow["nodes"]), ["finish", "middle", "start"])
        self.assertEqual(flow["nodes"]["middle"]["depends_on"], ["start"])
        self.assertEqual(flow["nodes"]["middle"]["policy"], {"timeout": {"attempt": "1500ms"}})
        self.assertNotIn("policy", flow["nodes"]["finish"])
        self.assertEqual(flow["outputs"], {"result": {"from": "nodes.finish.output.data"}})
        self.assertEqual(flow["nodes"]["start"]["operator"], "increment@1")
        self.assertEqual(result["diagnostics"], [])
        again = convert_canvas_graph(CANVAS, "example", input_schema="ints", output_schema="outs")
        self.assertEqual(json.dumps(result, sort_keys=True), json.dumps(again, sort_keys=True))

    def test_skeleton_compiles_and_runs_against_a_real_operator(self):
        skeleton = convert_canvas_graph(CANVAS, "example", input_schema="ints",
                                        output_schema="outs")["flow"]
        # The documented workflow: the skeleton names nodes and control edges;
        # data mappings are completed by the developer or the VibeCoding tool.
        skeleton["nodes"]["start"]["inputs"] = {"n": {"from": "flow.input.n", "required": True}}
        skeleton["nodes"]["middle"]["inputs"] = {"n": {"from": "nodes.start.output.data.n",
                                                       "required": True}}
        skeleton["nodes"]["finish"]["inputs"] = {"n": {"from": "nodes.middle.output.data.n",
                                                       "required": True}}
        release = compile_release(registry(), [skeleton], defaults=EPHEMERAL)
        outcome = LocalRuntime(release).run("example", {"n": 1})
        self.assertEqual(outcome.output["meta"]["status"], "SUCCEEDED")
        self.assertEqual(outcome.output["data"], {"result": {"n": 4}})
        self.assertGreaterEqual(outcome.nodes["middle"]["meta"]["durationMs"], 0)

    def test_missing_schemas_surface_as_advisories_and_fail_check(self):
        result = convert_canvas_graph(CANVAS, "example")
        self.assertEqual([item["error_code"] for item in result["diagnostics"]].count("UNKNOWN_SCHEMA"), 2)
        self.assertEqual(result["flow"]["input_schema"], "")
        with self.assertRaises(ContractError) as caught:
            compile_release(registry(), [result["flow"]], defaults=EPHEMERAL)
        self.assertEqual(caught.exception.diagnostic.error_code, "UNKNOWN_SCHEMA")

    def test_unreachable_nodes_are_excluded_with_a_warning(self):
        graph = {**CANVAS, "nodes": CANVAS["nodes"] + [
            {"id": "orphan", "kind": "OPERATOR", "operator": "increment", "operator_version": "1"}]}
        result = convert_canvas_graph(graph, "example", input_schema="ints", output_schema="outs")
        self.assertNotIn("orphan", result["flow"]["nodes"])
        self.assertEqual([item["path"] for item in result["diagnostics"]], ["nodes[orphan]"])

    def test_structural_violations_are_rejected(self):
        cases = [
            {**CANVAS, "entry_node": ""},
            {**CANVAS, "exit_node": "absent"},
            {**CANVAS, "nodes": []},
            {**CANVAS, "extra": 1},
            {**CANVAS, "nodes": [{**node, "id": "start"} for node in CANVAS["nodes"]]},
            {**CANVAS, "nodes": CANVAS["nodes"] + [{"id": "weird", "kind": "ROUTE"}]},
            {**CANVAS, "edges": CANVAS["edges"] + [{"from_node": "start", "to_node": "absent"}]},
            {**CANVAS, "edges": CANVAS["edges"] + [{"from_node": "start", "to_node": "middle"}]},
            {**CANVAS, "nodes": [{**node, "timeout_ms": 0} for node in CANVAS["nodes"]]},
            {**CANVAS, "nodes": [{**node, "extra_field": 1} for node in CANVAS["nodes"]]},
        ]
        for index, graph in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(ContractError) as caught:
                    convert_canvas_graph(graph, "example", input_schema="ints", output_schema="outs")
                self.assertEqual(caught.exception.diagnostic.error_code, "INVALID_CANVAS_GRAPH")

    def test_cycles_raise_the_graph_compilers_witness(self):
        cyclic = {"entry_node": "start", "exit_node": "start",
                  "nodes": [{"id": "start", "kind": "OPERATOR", "operator": "increment",
                             "operator_version": "1"}],
                  "edges": [{"from_node": "start", "to_node": "start"}]}
        with self.assertRaises(ContractError) as caught:
            convert_canvas_graph(cyclic, "example")
        self.assertEqual(caught.exception.diagnostic.error_code, "CYCLE_DETECTED")


if __name__ == "__main__":
    unittest.main()
