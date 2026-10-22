import threading
import unittest

from microflow import Context, Input, Metrics, Output
from microflow.errors import ContractError
from microflow import expressions
from microflow.paths import get, map_values, parse
from microflow.schema import check_schema, validate
from microflow.values import MISSING, digest, load_json, validate_value


class ContractTests(unittest.TestCase):
    def test_json_rejects_duplicate_nonfinite_and_invalid_syntax(self):
        for text in ('{"x":1,"x":2}', 'NaN', '1e999', '{"secret":}'):
            with self.subTest(text=text), self.assertRaises(ContractError):
                load_json(text)

    def test_json_diagnostic_has_line_column_without_document(self):
        with self.assertRaises(ContractError) as caught:
            load_json('{\n"secret":}')
        self.assertEqual(caught.exception.diagnostic.details["line"], 2)
        self.assertNotIn("secret", caught.exception.diagnostic.message)

    def test_json_budgets(self):
        with self.assertRaises(ContractError):
            load_json('"abcd"', max_bytes=3)
        with self.assertRaises(ContractError):
            validate_value([[[0]]], max_depth=2)
        with self.assertRaises(ContractError):
            validate_value([0, 1], max_items=2)

    def test_schema_is_strict_and_bool_is_not_integer(self):
        schema = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}
        check_schema(schema)
        validate({"n": 1}, schema)
        for value in ({}, {"n": None}, {"n": True}, {"n": 1, "other": 2}):
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate(value, schema)

    def test_malformed_schema_never_raises_python_type_error(self):
        for schema in ({"type": []}, {"type": "object", "required": [[]]},
                       {"type": "integer", "items": {"type": "oops"}},
                       {"type": "integer", "minLength": 2}):
            with self.subTest(schema=schema), self.assertRaises(ContractError):
                check_schema(schema)

    def test_paths_missing_null_and_special_keys(self):
        value = {"items": [{"a.b": None}]}
        self.assertIsNone(get(value, 'items[0]["a.b"]'))
        self.assertIs(get(value, "items[1]"), MISSING)
        for path in ("a[-1]", "a()", "a.*", "a.", 'a.["b"]'):
            with self.subTest(path=path), self.assertRaises(ContractError):
                parse(path)

    def test_mapping_required_precedes_default(self):
        with self.assertRaises(ContractError):
            map_values({"x": {"from": "missing", "required": True, "default": 5}}, {})

    def test_optional_mapping_preserves_missing_and_null(self):
        self.assertEqual(map_values({"x": {"from": "absent"}}, {}), {})
        self.assertEqual(map_values({"x": {"from": "n", "default": 1}}, {"n": None}), {"x": None})
        self.assertEqual(map_values({"x": {"from": "absent", "default": 1}}, {}), {"x": 1})

    def test_mapping_conflicts_even_with_missing_inputs(self):
        for rules in ({"x": {"from": "absent"}, "x.y": {"from": "absent"}},
                      {"x": {"from": "n", "unknown": True}}):
            with self.assertRaises(ContractError):
                map_values(rules, {"n": 1})

    def test_digest_distinguishes_types_and_orders_maps(self):
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))
        self.assertEqual(len({digest(x) for x in (True, 1, 1.0, "1", None, [], {})}), 7)

    def test_input_and_context_are_deeply_immutable(self):
        original = {"nested": {"n": 1}}
        value = Input(original)
        context = Context({"policy": original}, {"db": object()})
        original["nested"]["n"] = 99
        self.assertEqual(value["nested"]["n"], 1)
        self.assertEqual(context.options["policy"]["nested"]["n"], 1)
        with self.assertRaises(TypeError):
            context.options["x"] = 1
        with self.assertRaises(TypeError):
            context.resources["db"] = None

    def test_output_assignment_does_not_publish_partial_paths(self):
        output = Output()
        with self.assertRaises(ContractError):
            output.set("new.items[0]", 1)
        self.assertEqual(output.data, {})

    def test_conditions_short_circuit_and_reject_bool_ordering(self):
        expression = {"or": [{"exists": "n"}, {"eq": [{"path": "absent"}, 1]}]}
        expressions.check(expression)
        self.assertTrue(expressions.evaluate(expression, {"n": None}))
        with self.assertRaises(ContractError):
            expressions.evaluate({"lt": [True, False]}, {})
        with self.assertRaises(ContractError):
            expressions.check({"eq": [float("nan"), 1]})

    def test_metrics_are_bounded_and_operations_are_explicit(self):
        metrics = Metrics(limit=1)
        metrics.increment("calls")
        metrics.increment("calls", 2)
        metrics.observe("duration", .1)
        self.assertEqual(metrics.counts["calls"], 3)
        self.assertEqual(metrics.samples["duration"]["count"], 1)
        for action in (lambda: metrics.increment("other"), lambda: metrics.observe("other", 1),
                       lambda: metrics.increment("calls", True), lambda: metrics.observe("duration", float("nan"))):
            with self.assertRaises(ContractError):
                action()
