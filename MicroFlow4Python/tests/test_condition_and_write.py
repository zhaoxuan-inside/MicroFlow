"""Operator-node conditions (truthy/exists) and controlled write effects.

Baseline coverage:
- 条件执行：false 谓词跳过节点不失败流程；链式条件看到缺失即 False；
  非必需映射下游自动省略；谓词求值错误节点 FAILED。
- 受控 write：默认拒绝（WRITE_EFFECT_NOT_ALLOWED）；allow_write 显式放行并
  产出 write_effect_invoked 审计记录；纯算子不受影响。
"""
import asyncio
import unittest

from microflow import Registry
from microflow.compiler import compile_release
from microflow.errors import ContractError
from microflow.expressions import check as check_expression
from microflow.runtime import LocalRuntime
from microflow.values import thaw

from tests.test_compiler import EPHEMERAL, INTEGER_MAP, method

FLAG_MAP = {"type": "object",
            "properties": {"n": {"type": "integer"}, "flag": {"type": "boolean"}},
            "required": ["n"]}


def flagger(input, output, context, metrix, debug, log):
    output.set("n", input["n"])
    output.set("flag", input["n"] > 0)
    return True


def writer(input, output, context, metrix, debug, log):
    output.set("n", input["n"] + 1)
    return True


def rejecting_with_reason(input, output, context, metrix, debug, log):
    output.set("message", "库存不足")
    output.set("error_type", "ValueError")
    return False


def registry():
    result = Registry()
    result.register_schema("ints", INTEGER_MAP)
    result.register_schema("flagged", FLAG_MAP)
    result.register_operator(name="flagger", version="1", method=flagger,
                             input_schema="ints", output_schema="flagged")
    result.register_operator(name="increment", version="1", method=method,
                             input_schema="ints", output_schema="ints")
    result.register_operator(name="writer", version="1", method=writer,
                             input_schema="ints", output_schema="ints",
                             capabilities={"effect": "write", "idempotency_support": "natural"})
    return result


def flow():
    return {"id": "gated", "input_schema": "ints", "output_schema": "ints", "nodes": {
        "check": {"operator": "flagger@1",
                  "inputs": {"n": {"from": "flow.input.n", "required": True}}},
        "when_positive": {"operator": "increment@1", "condition": {
            "truthy": "nodes.check.output.data.flag"},
            "inputs": {"n": {"from": "nodes.check.output.data.n"}}},
        "when_chained": {"operator": "increment@1", "condition": {
            "truthy": "nodes.when_positive.output.data.n"},
            "inputs": {"n": {"from": "flow.input.n"}}}},
        "outputs": {"n": {"from": "nodes.check.output.data.n", "required": True}}}


def write_flow():
    return {"id": "writing", "input_schema": "ints", "output_schema": "ints", "nodes": {
        "bump": {"operator": "writer@1",
                 "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
        "outputs": {"n": {"from": "nodes.bump.output.data.n", "required": True}}}


def run(nodes, payload, **runtime_kwargs):
    reg = registry()
    release = compile_release(reg, [{**flow(), "nodes": nodes}], defaults=EPHEMERAL)
    return asyncio.run(LocalRuntime(release, **runtime_kwargs).run_async("gated", payload))


class ExpressionTests(unittest.TestCase):
    def test_truthy_is_registered_in_whitelist(self):
        check_expression({"truthy": "flow.input.n"})

    def test_truthy_rejects_non_path(self):
        with self.assertRaises(ContractError):
            check_expression({"truthy": 42})


class ConditionTests(unittest.TestCase):
    def test_false_condition_skips_node_and_flow_succeeds(self):
        result = run(flow()["nodes"], {"n": -5})
        self.assertEqual(result.output["meta"]["status"], "SUCCEEDED")
        self.assertEqual(result.nodes["when_positive"]["meta"]["status"], "SKIPPED")
        self.assertIsNone(result.nodes["when_positive"]["data"])

    def test_true_condition_executes_node(self):
        result = run(flow()["nodes"], {"n": 5})
        self.assertEqual(result.output["meta"]["status"], "SUCCEEDED")
        self.assertEqual(result.nodes["when_positive"]["meta"]["status"], "SUCCEEDED")
        self.assertEqual(result.nodes["when_positive"]["data"]["n"], 6)

    def test_chained_gate_skips_when_upstream_was_skipped(self):
        result = run(flow()["nodes"], {"n": -5})
        self.assertEqual(result.nodes["when_chained"]["meta"]["status"], "SKIPPED")

    def test_chained_gate_runs_when_upstream_ran(self):
        result = run(flow()["nodes"], {"n": 5})
        self.assertEqual(result.nodes["when_chained"]["meta"]["status"], "SUCCEEDED")

    def test_chained_conditions_see_skipped_nodes_as_missing(self):
        nodes = {"check": flow()["nodes"]["check"],
                 "gate_a": {"operator": "increment@1", "condition": {"truthy": "nodes.check.output.data.flag"},
                            "inputs": {"n": {"from": "flow.input.n"}}},
                 "gate_b": {"operator": "increment@1", "condition": {"truthy": "nodes.gate_a.output.data.n"},
                            "inputs": {"n": {"from": "flow.input.n"}}}}
        result = run(nodes, {"n": -1})
        self.assertEqual(result.output["meta"]["status"], "SUCCEEDED")
        self.assertEqual(result.nodes["gate_a"]["meta"]["status"], "SKIPPED")
        self.assertEqual(result.nodes["gate_b"]["meta"]["status"], "SKIPPED")

    def test_condition_evaluation_error_fails_node_and_flow(self):
        # A declared upstream node skipped at runtime makes its output paths
        # missing; an eq comparison against them must raise, not silently pass.
        nodes = {"check": flow()["nodes"]["check"],
                 "first": {"operator": "increment@1", "condition": {"truthy": "nodes.check.output.data.flag"},
                           "inputs": {"n": {"from": "flow.input.n"}}},
                 "probe": {"operator": "increment@1",
                           "condition": {"eq": [{"path": "nodes.first.output.data.n"}, 1]},
                           "inputs": {"n": {"from": "flow.input.n"}}}}
        result = run(nodes, {"n": -5})
        self.assertEqual(result.nodes["first"]["meta"]["status"], "SKIPPED")
        self.assertEqual(result.nodes["probe"]["meta"]["status"], "FAILED")
        self.assertEqual(result.output["meta"]["status"], "FAILED")
        self.assertEqual(result.output["error"]["code"], "MISSING_CONDITION_VALUE")

    def test_condition_on_subflow_node_is_rejected(self):
        reg = registry()
        nested = {"id": "nested", "input_schema": "ints", "output_schema": "ints", "nodes": {
            "only": {"operator": "increment@1", "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
            "outputs": {"n": {"from": "nodes.only.output.data.n", "required": True}}}
        outer = {"id": "outer", "input_schema": "ints", "output_schema": "ints", "nodes": {
            "child": {"type": "subflow", "flow": "nested", "condition": {"truthy": "flow.input.n"},
                      "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
            "outputs": {"n": {"from": "nodes.child.output.data.n", "required": True}}}
        release = compile_release(reg, [nested, outer], defaults=EPHEMERAL)
        with self.assertRaises(ContractError) as caught:
            LocalRuntime(release).run("outer", {"n": 1})
        self.assertEqual(caught.exception.diagnostic.error_code, "UNSUPPORTED_LOCAL_NODE")


class WriteEffectTests(unittest.TestCase):
    def test_write_operator_requires_explicit_opt_in(self):
        reg = registry()
        release = compile_release(reg, [write_flow()], defaults=EPHEMERAL)
        with self.assertRaises(ContractError) as caught:
            LocalRuntime(release).run("writing", {"n": 1})
        self.assertEqual(caught.exception.diagnostic.error_code, "WRITE_EFFECT_NOT_ALLOWED")

    def test_write_operator_runs_and_is_audited_when_allowed(self):
        reg = registry()
        release = compile_release(reg, [write_flow()], defaults=EPHEMERAL)
        result = asyncio.run(LocalRuntime(release, allow_write=True).run_async("writing", {"n": 1}))
        self.assertEqual(result.output["meta"]["status"], "SUCCEEDED")
        self.assertEqual(result.output["data"]["n"], 2)
        write_records = [r for r in result.records if r["event"] == "write_effect_invoked"]
        self.assertEqual(len(write_records), 1)
        self.assertEqual(write_records[0]["status"], "SUCCEEDED")
        self.assertEqual(write_records[0]["operatorName"], "writer")

    def test_pure_operator_runs_without_opt_in(self):
        reg = registry()
        release = compile_release(reg, [{**write_flow(), "nodes": {
            "bump": {"operator": "increment@1", "inputs": {"n": {"from": "flow.input.n", "required": True}}}}}],
            defaults=EPHEMERAL)
        result = asyncio.run(LocalRuntime(release).run_async("writing", {"n": 1}))
        self.assertEqual(result.output["data"]["n"], 2)
        self.assertFalse([r for r in result.records if r["event"] == "write_effect_invoked"])

    def test_frozen_output_remains_json_safe(self):
        reg = registry()
        release = compile_release(reg, [write_flow()], defaults=EPHEMERAL)
        result = asyncio.run(LocalRuntime(release, allow_write=True).run_async("writing", {"n": 1}))
        thaw(result.output)


class RejectionReasonTests(unittest.TestCase):
    def test_business_rejection_publishes_reason_data(self):
        """False return keeps output.data as the node result (documented contract)."""
        reg = registry()
        reg.register_operator(name="rejector", version="1", method=rejecting_with_reason,
                              input_schema="ints", output_schema="ints")
        flow_def = {"id": "rej", "input_schema": "ints", "output_schema": "ints", "nodes": {
            "gate": {"operator": "rejector@1",
                     "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
            "outputs": {"n": {"from": "nodes.gate.output.data.n", "required": True}}}
        release = compile_release(reg, [flow_def], defaults=EPHEMERAL)
        result = asyncio.run(LocalRuntime(release).run_async("rej", {"n": 1}))
        self.assertEqual(result.output["meta"]["status"], "FAILED")
        self.assertEqual(result.output["error"]["code"], "OPERATOR_REJECTED")
        self.assertEqual(result.nodes["gate"]["data"], {"message": "库存不足", "error_type": "ValueError"})


if __name__ == "__main__":
    unittest.main()
