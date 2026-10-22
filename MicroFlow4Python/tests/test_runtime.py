import asyncio
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from microflow import Registry
from microflow.compiler import compile_release
from microflow.errors import ContractError
from microflow.runtime import LocalRuntime
from microflow.values import thaw
from tests.test_compiler import EPHEMERAL, INTEGER_MAP, flow, method, registry


def throwing(input, output, context, metrix, debug, log):
    output.set("n", 999)
    raise RuntimeError("private password")


def rejecting(input, output, context, metrix, debug, log):
    return False


def fallback(input, output, context, metrix, debug, log):
    output.set("n", input["business_input"]["n"] + 10)
    return True


def invalid(input, output, context, metrix, debug, log):
    output.set("n", "not an integer")
    return True


def broken_collector(input, output, context, metrix, debug, log):
    raise RuntimeError("collector secret")


async def coroutine(input, output, context, metrix, debug, log):
    await asyncio.sleep(0)
    output.set("n", input["n"] + 2)
    return True


def compiled(main=method, **kwargs):
    reg = Registry()
    reg.register_schema("ints", INTEGER_MAP)
    reg.register_operator(name="increment", version="1", method=main, input_schema="ints", output_schema="ints", **kwargs)
    return compile_release(reg, [flow()], defaults=EPHEMERAL)


class RuntimeTests(unittest.TestCase):
    def test_dag_runs_and_generates_new_metadata_per_run(self):
        runtime = LocalRuntime(compiled())
        first, second = runtime.run("example", {"n": 1}), runtime.run("example", {"n": 1})
        self.assertEqual(first.output["data"], {"n": 3})
        self.assertEqual(first.output["meta"]["status"], "SUCCEEDED")
        self.assertNotEqual(first.output["meta"]["traceId"], second.output["meta"]["traceId"])
        with self.assertRaises(TypeError):
            first.output["data"]["n"] = 9

    def test_unhandled_exception_trips_root_and_skips_downstream(self):
        result = LocalRuntime(compiled(throwing)).run("example", {"n": 1})
        self.assertEqual(result.output["meta"]["stopReason"], "CIRCUIT_BROKEN")
        self.assertEqual(result.output["error"]["code"], "UNHANDLED_OPERATOR_EXCEPTION")
        self.assertIsNone(result.nodes["first"]["data"])
        self.assertEqual(result.nodes["second"]["meta"]["status"], "SKIPPED")
        self.assertNotIn("private password", str(thaw(result.output)))

    def test_fallback_uses_original_input_and_independent_output(self):
        result = LocalRuntime(compiled(throwing, fallback=fallback,
                         fallback_capabilities={"effect": "pure", "idempotency_support": "natural"})).run("example", {"n": 1})
        self.assertEqual(result.output["data"], {"n": 21})
        self.assertEqual(result.nodes["first"]["meta"]["resolution"], "fallback")
        self.assertIsNone(result.output["error"])

    def test_false_does_not_call_fallback(self):
        def forbidden(input, output, context, metrix, debug, log):
            self.fail("False must not invoke fallback")
        result = LocalRuntime(compiled(rejecting, fallback=forbidden,
                         fallback_capabilities={"effect": "pure", "idempotency_support": "natural"})).run("example", {"n": 1})
        self.assertEqual(result.output["error"]["code"], "OPERATOR_REJECTED")
        self.assertIsNone(result.output["meta"]["stopReason"])

    def test_invalid_output_is_contract_failure_and_not_fallback(self):
        result = LocalRuntime(compiled(invalid)).run("example", {"n": 1})
        self.assertEqual(result.output["error"]["code"], "OUTPUT_CONTRACT_VIOLATION")
        self.assertIsNone(result.nodes["first"]["data"])

    def test_fallback_exception_does_not_recurse(self):
        result = LocalRuntime(compiled(throwing, fallback=throwing,
                         fallback_capabilities={"effect": "pure", "idempotency_support": "natural"})).run("example", {"n": 1})
        self.assertEqual(result.output["error"]["code"], "FALLBACK_FAILED")
        self.assertEqual(result.output["meta"]["status"], "FAILED")

    def test_collectors_cannot_change_business_and_base_records_exist(self):
        result = LocalRuntime(compiled(log=broken_collector, metrix=broken_collector)).run("example", {"n": 1})
        self.assertEqual(result.output["data"], {"n": 3})
        self.assertEqual(sum(r["event"] == "collector_failed" for r in result.records), 4)
        completed = [r for r in result.records if r["event"] == "invocation_completed"]
        self.assertEqual(len(completed), 2)
        for record in completed:
            self.assertTrue(all(record[key] for key in ("scene", "version", "releaseId", "traceId", "operatorName", "startedAt", "endedAt")))
        self.assertNotIn("collector secret", str(result.records))

    def test_cancelled_before_dispatch(self):
        cancel = threading.Event()
        cancel.set()
        result = LocalRuntime(compiled()).run("example", {"n": 1}, cancel=cancel)
        self.assertEqual(result.output["meta"]["status"], "CANCELLED")
        self.assertTrue(all(n["meta"]["status"] == "SKIPPED" for n in result.nodes.values()))

    def test_coroutine_and_async_entry(self):
        result = asyncio.run(LocalRuntime(compiled(coroutine)).run_async("example", {"n": 1}))
        self.assertEqual(result.output["data"], {"n": 5})

    def test_nested_flow_keeps_release_and_root_stop(self):
        child = flow()
        parent = {"id": "parent", "input_schema": "ints", "output_schema": "ints", "nodes": {
            "child": {"type": "subflow", "flow": "example", "inputs": {"n": {"from": "flow.input.n"}}}},
            "outputs": {"n": {"from": "nodes.child.output.data.n"}}}
        release = compile_release(registry(), [child, parent], defaults=EPHEMERAL)
        result = LocalRuntime(release).run("parent", {"n": 1})
        self.assertEqual(result.output["data"], {"n": 3})
        self.assertTrue(all(n["meta"].get("releaseId") == release.release_id for n in result.nodes.values()))

    def test_unsupported_policy_is_rejected_before_any_business(self):
        definition = flow()
        definition["nodes"]["second"]["policy"] = {"cache": {"enabled": True}}
        release = compile_release(registry(), [definition], defaults=EPHEMERAL)
        with self.assertRaises(ContractError):
            LocalRuntime(release).run("example", {"n": 1})

    def test_invalid_input_runs_no_methods(self):
        result = LocalRuntime(compiled()).run("example", {"n": True})
        self.assertEqual(result.output["meta"]["status"], "FAILED")
        self.assertEqual(len(result.records), 0)

    def test_host_logging_failure_cannot_change_business_result(self):
        with patch("microflow.runtime.logger.info", side_effect=RuntimeError("sink offline")):
            result = LocalRuntime(compiled()).run("example", {"n": 1})
        self.assertEqual(result.output["data"], {"n": 3})

    def test_completion_view_does_not_mutate_context_seen_by_main(self):
        contexts = []
        def capture(input, output, context, metrix, debug, log):
            contexts.append(context)
            output.set("n", input["n"])
            return True
        result = LocalRuntime(compiled(capture)).run("example", {"n": 1})
        self.assertTrue(all(context.options["endedAt"] is None for context in contexts))
        self.assertTrue(all(r["endedAt"] for r in result.records if r["event"] == "invocation_completed"))
