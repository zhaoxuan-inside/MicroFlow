import graphlib
from pathlib import Path
import random
import tempfile
import unittest

from microflow.compiler import compile_release
from microflow.errors import ContractError
from microflow.graph import compile_graph
from microflow.registry import Registry, discover
from microflow.paths import get


EPHEMERAL = {"durability": "ephemeral", "recovery": {"enabled": False}}
INTEGER_MAP = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


def method(input, output, context, metrix, debug, log):
    output.set("n", input["n"] + 1)
    return True


def registry():
    result = Registry()
    result.register_schema("ints", INTEGER_MAP)
    result.register_schema("text", {"type": "object", "properties": {"n": {"type": "string"}}, "required": ["n"]})
    result.register_operator(name="increment", version="1", method=method,
                             input_schema="ints", output_schema="ints")
    return result


def flow():
    return {"id": "example", "input_schema": "ints", "output_schema": "ints", "nodes": {
        "first": {"operator": "increment@1", "inputs": {"n": {"from": "flow.input.n", "required": True}}},
        "second": {"operator": "increment@1", "inputs": {"n": {
            "from": "nodes.first.output.data.n", "required": True}}}},
        "outputs": {"n": {"from": "nodes.second.output.data.n", "required": True}}}


class GraphTests(unittest.TestCase):
    def test_random_graphs_agree_with_standard_library(self):
        rng = random.Random(121)
        for _ in range(1000):
            nodes = [f"n{i:02}" for i in range(rng.randrange(1, 18))]
            edges = [(u, v) for u in nodes for v in nodes if rng.random() < .08]
            predecessors = {n: {u for u, v in edges if v == n} for n in nodes}
            try:
                tuple(graphlib.TopologicalSorter(predecessors).static_order())
            except graphlib.CycleError:
                with self.assertRaises(ContractError):
                    compile_graph(nodes, edges)
            else:
                result = compile_graph(nodes, edges)
                positions = {n: i for i, n in enumerate(result.order)}
                self.assertTrue(all(positions[u] < positions[v] for u, v in edges))
                rng.shuffle(nodes)
                rng.shuffle(edges)
                self.assertEqual(result.order, compile_graph(nodes, edges).order)

    def test_deep_chain_cycle_and_cycle_downstream(self):
        nodes = [f"n{i:05}" for i in range(20_000)]
        edges = list(zip(nodes, nodes[1:]))
        self.assertEqual(compile_graph(nodes, edges).order, tuple(nodes))
        with self.assertRaises(ContractError) as caught:
            compile_graph(nodes, edges + [(nodes[-1], nodes[0])])
        self.assertEqual(len(caught.exception.diagnostic.details["cycle"]), 20_001)
        with self.assertRaises(ContractError) as caught:
            compile_graph(["a", "b", "c"], [("a", "b"), ("b", "a"), ("b", "c")])
        self.assertEqual(caught.exception.diagnostic.details["cycle"], ["a", "b", "a"])

    def test_unknown_nodes_duplicate_edges_and_immutability(self):
        with self.assertRaises(ContractError):
            compile_graph(["a"], [("a", "b")])
        graph = compile_graph(["a", "b"], [("a", "b"), ("a", "b")])
        self.assertEqual(graph.order, ("a", "b"))
        with self.assertRaises(TypeError):
            graph.successors["a"] = frozenset()


class CompilerTests(unittest.TestCase):
    def test_edge_sources_merge_without_losing_declarations(self):
        definition = flow()
        definition["nodes"]["second"]["depends_on"] = ["first", "first"]
        release = compile_release(registry(), [definition], defaults=EPHEMERAL, source_file="project.json")
        graph = release.flows["example"].graph
        origins = graph.edge_sources["first", "second"]
        self.assertEqual(len(origins), 3)
        self.assertEqual([o["kind"] for o in origins], ["control", "control", "data"])
        for origin in origins:
            self.assertEqual(origin["flow_id"], "example")
            self.assertEqual(origin["node_id"], "second")
            self.assertEqual(origin["source_file"], "project.json")
            self.assertIn(get({"flows": [definition]}, origin["path"]), ("first", "nodes.first.output.data.n"))
        with self.assertRaises(TypeError):
            origins[0]["path"] = "changed"

    def test_cycle_diagnostic_has_each_edge_location(self):
        definition = flow()
        definition["nodes"]["first"]["depends_on"] = ["second"]
        with self.assertRaises(ContractError) as caught:
            compile_release(registry(), [definition], defaults=EPHEMERAL, source_file="project.json")
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic.flow_id, "example")
        self.assertEqual(diagnostic.source_file, "project.json")
        self.assertEqual(len(diagnostic.details["edges"]), 2)
        self.assertTrue(all(e["source_locations"] for e in diagnostic.details["edges"]))
        self.assertTrue(diagnostic.hint)

    def test_unknown_target_and_subflow_recursion_locations(self):
        definition = flow()
        definition["nodes"]["first"]["depends_on"] = ["absent"]
        with self.assertRaises(ContractError) as caught:
            compile_release(registry(), [definition], defaults=EPHEMERAL)
        self.assertEqual(caught.exception.diagnostic.node_id, "first")
        definition["nodes"] = {"self": {"type": "subflow", "flow": "example"}}
        definition["outputs"] = {"n": {"from": "flow.input.n"}}
        with self.assertRaises(ContractError) as caught:
            compile_release(registry(), [definition], defaults=EPHEMERAL)
        origin = caught.exception.diagnostic.details["edges"][0]["source_locations"][0]
        self.assertEqual(origin["kind"], "subflow")
        self.assertEqual(origin["node_id"], "self")

    def test_diagnostic_context_and_location_do_not_change_identity(self):
        definition = flow()
        definition["nodes"]["first"]["inputs"]["n"]["from"] = "context.options.dynamic"
        first = compile_release(registry(), [definition], defaults=EPHEMERAL, source_file="one.json")
        second = compile_release(registry(), [definition], defaults=EPHEMERAL, source_file="two.json")
        self.assertEqual(first.release_id, second.release_id)
        diagnostic = first.flows["example"].diagnostics[0]
        self.assertEqual(diagnostic["release_id"], first.release_id)
        self.assertEqual(diagnostic["source_file"], "one.json")
        self.assertEqual(diagnostic["node_id"], "first")
        definition["input_schema"] = "text"
        definition["nodes"]["first"]["inputs"]["n"]["from"] = "flow.input.n"
        with self.assertRaises(ContractError) as caught:
            compile_release(registry(), [definition], defaults=EPHEMERAL)
        self.assertEqual((caught.exception.diagnostic.expected, caught.exception.diagnostic.actual), ("integer", "string"))

    def test_malformed_dynamic_nodes_are_structured_errors(self):
        route = {"type": "route", "branches": [{"when": {"exists": "flow.input.n"}, "target": "second"}], "default": None}
        invalid = [dict(route, branches=[None]), dict(route, branches=[[]]),
                   dict(route, branches=[{"when": {"exists": "flow.input.n"}, "target": []}]),
                   dict(route, default={}), dict(route, max_items=3),
                   {"type": "wait", "signal": "", "result_schema": "ints"}]
        for node in invalid:
            definition = flow()
            definition["nodes"]["first"] = node
            with self.subTest(node=node), self.assertRaises(ContractError) as caught:
                compile_release(registry(), [definition], defaults=EPHEMERAL)
            self.assertEqual(caught.exception.diagnostic.node_id, "first")

    def test_conditions_and_loop_until_dependencies_are_validated(self):
        definition = flow()
        definition["nodes"]["first"]["condition"] = {"exists": "flow.other.n"}
        with self.assertRaisesRegex(ContractError, "INVALID_SOURCE"):
            compile_release(registry(), [definition], defaults=EPHEMERAL)
        definition = flow()
        child = flow()
        child["id"] = "child"
        definition["nodes"]["loop"] = {"type": "loop", "flow": "child", "max_iterations": 2,
            "until": {"exists": "nodes.second.output.data.n"}}
        plan = compile_release(registry(), [definition, child], defaults=EPHEMERAL).flows["example"]
        self.assertIn("second", plan.graph.predecessors["loop"])

    def test_invalid_defaults_are_checked_even_without_nodes(self):
        for defaults in ([], False, {"concurrency": 0}):
            with self.subTest(defaults=defaults), self.assertRaises(ContractError):
                compile_release(registry(), [], defaults=defaults)

    def test_map_items_type_and_wait_result_schema(self):
        definition, child = flow(), flow()
        child["id"] = "child"
        definition["nodes"]["first"] = {"type": "map", "flow": "child", "max_items": 2, "items": "flow.input.n"}
        with self.assertRaises(ContractError) as caught:
            compile_release(registry(), [definition, child], defaults=EPHEMERAL)
        self.assertEqual(caught.exception.diagnostic.expected, "array")
        definition["nodes"]["first"] = {"type": "wait", "signal": "ready", "result_schema": "text"}
        with self.assertRaises(ContractError) as caught:
            compile_release(registry(), [definition], defaults=EPHEMERAL)
        self.assertEqual((caught.exception.diagnostic.expected, caught.exception.diagnostic.actual), ("integer", "string"))

    def test_plan_is_repeatable_and_infers_data_edges(self):
        first = compile_release(registry(), [flow()], defaults=EPHEMERAL)
        second = compile_release(registry(), [flow()], defaults=EPHEMERAL)
        self.assertEqual(first.release_id, second.release_id)
        self.assertEqual(first.flows["example"].graph.predecessors["second"], {"first"})
        with self.assertRaises(TypeError):
            first.manifest["flows"]["example"]["nodes"]["first"]["operator"] = "changed"

    def test_invalid_output_source_has_framework_diagnostic(self):
        for source in ("other.n", "nodes.first.output.error", "nodes.first[0]", "flow.other.n"):
            definition = flow()
            definition["outputs"]["n"]["from"] = source
            with self.subTest(source=source), self.assertRaises(ContractError):
                compile_release(registry(), [definition], defaults=EPHEMERAL)

    def test_static_type_conflict_and_missing_schema_path(self):
        for source, schema in (("flow.input.n", "text"), ("flow.input.absent", "ints")):
            definition = flow()
            definition["input_schema"] = schema
            definition["nodes"]["first"]["inputs"]["n"]["from"] = source
            with self.subTest(source=source), self.assertRaises(ContractError):
                compile_release(registry(), [definition], defaults=EPHEMERAL)

    def test_control_data_union_and_subflow_recursion(self):
        definition = flow()
        definition["nodes"]["first"]["depends_on"] = ["second"]
        with self.assertRaises(ContractError):
            compile_release(registry(), [definition], defaults=EPHEMERAL)
        definition = flow()
        definition["nodes"] = {"self": {"type": "subflow", "flow": "example"}}
        with self.assertRaises(ContractError):
            compile_release(registry(), [definition], defaults=EPHEMERAL)

    def test_malformed_reference_types_have_structured_errors(self):
        for field, value in (("input_schema", []), ("output_schema", {}), ("options", []), ("id", "")):
            definition = flow()
            definition[field] = value
            with self.subTest(field=field), self.assertRaises(ContractError):
                compile_release(registry(), [definition], defaults=EPHEMERAL)
        definition = flow()
        definition["nodes"]["first"]["operator"] = []
        with self.assertRaises(ContractError):
            compile_release(registry(), [definition], defaults=EPHEMERAL)

    def test_unknown_compatibility_is_not_reported_as_proved(self):
        definition = flow()
        definition["nodes"]["first"]["inputs"]["n"]["from"] = "context.options.dynamic"
        release = compile_release(registry(), [definition], defaults=EPHEMERAL)
        self.assertEqual(release.flows["example"].diagnostics[0]["proof"], "UNKNOWN")

    def test_failed_registration_batch_does_not_modify_existing_registry(self):
        previous = registry().seal()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.py"
            bad = Path(directory) / "bad.py"
            first.write_text('def register(registry):\n    registry.register_schema("ok", {"type": "object"})\n')
            bad.write_text('def register(registry):\n    raise RuntimeError("secret payload")\n')
            with self.assertRaises(ContractError) as caught:
                discover([first, bad])
            self.assertNotIn("secret payload", str(caught.exception))
        self.assertEqual(list(previous.operators), ["increment@1"])
        self.assertNotIn("ok", previous.schemas)

    def test_missing_entry_invalid_signature_and_method_none(self):
        with self.assertRaises(ContractError):
            registry().register_operator(name="bad", version="1", method=None,
                                         input_schema="ints", output_schema="ints")
        with self.assertRaises(ContractError):
            registry().register_operator(name="bad", version="1", method=lambda x: True,
                                         input_schema="ints", output_schema="ints")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.py"
            path.write_text('value = 1\n')
            with self.assertRaises(ContractError):
                discover([path])
