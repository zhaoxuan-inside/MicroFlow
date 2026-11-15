import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from microflow import LocalRuntime, discover, parse_project
from microflow.compiler import compile_release
from microflow.errors import ContractError
from microflow import cli
from tests.test_cli_system import MODULE


SOURCE = '''
module("ops.py")

with flow("calculate", input_schema="ints", output_schema="ints"):
    operator("first", operator="increment@1",
             inputs={"n": source("flow.input.n", required=True)})
    operator("second", operator="increment@1",
             when=gt(path("nodes.first.output.data.n"), 0),
             inputs={"n": source("nodes.first.output.data.n", required=True)})
    output("n", "nodes.first.output.data.n", required=True)
'''


class DslTests(unittest.TestCase):
    def run_cli(self, args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(args)
        return code, json.loads(out.getvalue())

    def test_cli_executes_condition_and_preserves_existing_compilation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ops.py").write_text(MODULE, encoding="utf-8")
            project = root / "project.mf"
            project.write_text(SOURCE, encoding="utf-8")
            input_file = root / "input.json"
            code, check = self.run_cli(["check", str(project), "--ephemeral"])
            self.assertEqual(code, 0, check)
            for number, expected in ((1, "SUCCEEDED"), (-2, "SKIPPED")):
                input_file.write_text(json.dumps({"n": number}), encoding="utf-8")
                code, result = self.run_cli(["run", str(project), "calculate", str(input_file), "--ephemeral"])
                self.assertEqual(code, 0, result)
                self.assertEqual(result["nodes"]["second"]["meta"]["status"], expected)
                self.assertEqual(result["output"]["data"]["n"], number + 1)
            model = parse_project(SOURCE)
            registry = discover([root / "ops.py"])
            defaults = {"durability": "ephemeral", "recovery": {"enabled": False}}
            release = compile_release(registry, model["flows"], defaults=defaults)
            self.assertEqual(LocalRuntime(release).run("calculate", {"n": 1}).output["data"]["n"], 2)
            json_project = root / "project.json"
            json_project.write_text(json.dumps(model), encoding="utf-8")
            code, json_check = self.run_cli(["check", str(json_project), "--ephemeral"])
            self.assertEqual(code, 0, json_check)
            self.assertEqual(check["releaseId"], json_check["releaseId"])

    def test_rejects_code_and_duplicate_declarations(self):
        for text in ('module(__import__("os").system("false"))',
                     'with flow("x"):\n    operator("a", operator="x")\n    operator("a", operator="y")',
                     'with flow("x"):\n    output("x", "flow.input.x")\n    output("x", "flow.input.x")',
                     'with flow("x"):\n    operator("a", operator="x", inputs={"x": 1, "x": 2})'):
            with self.subTest(text=text), self.assertRaises(ContractError):
                parse_project(text)

    def test_syntax_error_has_location(self):
        with self.assertRaises(ContractError) as error:
            parse_project('with flow("x")\n    pass')
        self.assertEqual(error.exception.diagnostic.error_code, "INVALID_PROJECT")
        self.assertEqual(error.exception.diagnostic.details["line"], 1)


if __name__ == "__main__":
    unittest.main()
