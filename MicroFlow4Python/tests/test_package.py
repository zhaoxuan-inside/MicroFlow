import asyncio
import importlib.resources
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from microflow import ScheduledRuntime, discover
from microflow.cli import _load_project
from microflow.coordinator import Coordinator
from microflow.errors import ContractError
from microflow.persistence import StorageBinding
from microflow.scheduling import ExecutionCommands
from microflow.testing import MemoryStateStore
from microflow.compiler import compile_release
from microflow.values import digest, load_json, thaw


ROOT = Path(__file__).resolve().parents[1]

# 内联集成夹具：不依赖仓库内示例文件；与 README「集成与使用」同构。
FIXTURE_MODULE = '''"""Pure calculation fixture. It performs no external operations."""


def calculate(input, output, context, metrix, debug, log):
    output.set("total", sum(item["price"] * item["quantity"] for item in input["items"]))
    return True


def register(registry):
    registry.register_schema("quote.input@1", {
        "type": "object", "properties": {"items": {"type": "array", "items": {
            "type": "object", "properties": {"price": {"type": "integer", "minimum": 0},
                                             "quantity": {"type": "integer", "minimum": 1}},
            "required": ["price", "quantity"]}}}, "required": ["items"]})
    registry.register_schema("quote.output@1", {"type": "object", "properties": {
        "total": {"type": "integer", "minimum": 0}}, "required": ["total"]})
    registry.register_operator(name="quote.calculate", version="1", method=calculate,
                               input_schema="quote.input@1", output_schema="quote.output@1")
'''

FIXTURE_FLOW = {
    "id": "quote",
    "input_schema": "quote.input@1",
    "output_schema": "quote.output@1",
    "options": {"scene": "order.quote", "version": "quote@1"},
    "nodes": {
        "calculate": {
            "operator": "quote.calculate@1",
            "inputs": {"items": {"from": "flow.input.items", "required": True}}
        }
    },
    "outputs": {"total": {"from": "nodes.calculate.output.data.total", "required": True}},
}

FIXTURE_INPUT = {"items": [{"price": 1200, "quantity": 2}, {"price": 1500, "quantity": 1}]}


def _write_fixture(directory: Path) -> tuple[str, str, str]:
    module = directory / "quote.py"
    module.write_text(FIXTURE_MODULE, encoding="utf-8")
    project = directory / "quote.project.json"
    project.write_text(json.dumps({"modules": ["quote.py"], "flows": [FIXTURE_FLOW]}),
                       encoding="utf-8")
    source = directory / "quote.input.json"
    source.write_text(json.dumps(FIXTURE_INPUT), encoding="utf-8")
    return str(module), str(project), str(source)


class PackageTests(unittest.TestCase):
    def test_scheduled_runtime_end_to_end(self):
        async def main():
            with tempfile.TemporaryDirectory() as directory:
                module = Path(directory) / "quote.py"
                module.write_text(FIXTURE_MODULE, encoding="utf-8")
                release = compile_release(discover([module]), [FIXTURE_FLOW],
                                          defaults={"durability": "ephemeral",
                                                    "recovery": {"enabled": False}})
                store = MemoryStateStore()
                coordinator = Coordinator(store)
                binding = StorageBinding("memory-test", "runtime-state", "example",
                                         store.load_recovery_view().binding_revision, digest({}))
                commands = ExecutionCommands(coordinator, release, binding=binding,
                                             protocol_test=True)
                try:
                    async with ScheduledRuntime(commands, workers=2) as runtime:
                        accepted = await runtime.submit("quote", FIXTURE_INPUT,
                                                        request_id="scheduled-quote-fixture")
                        result = await runtime.wait(accepted["execution_id"], timeout=5)
                        self.assertEqual(accepted["durability"], "ephemeral")
                        self.assertTrue(accepted["protocol_test"])
                        self.assertEqual(thaw(result["output"])["data"]["total"], 3900)
                finally:
                    coordinator.close()
        asyncio.run(main())

    def test_ephemeral_flag_does_not_hide_invalid_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            for defaults in ({"recovery": {"typo": True}}, {"durability": None}, {"recovery": None}):
                path.write_text(json.dumps({"modules": [], "flows": [{}], "defaults": defaults}), encoding="utf-8")
                with self.subTest(defaults=defaults), self.assertRaises(ContractError) as caught:
                    _load_project(path)
                self.assertEqual(caught.exception.diagnostic.source_file, str(path.resolve()))

    def test_policy_descriptor_cli(self):
        result = subprocess.run([sys.executable, "-m", "microflow", "policy-schema"],
                                text=True, capture_output=True, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["protocol"], "microflow-policy-schema-v1")
        self.assertEqual(payload["defaults"]["checkpoint_policy"], "operator")
        self.assertEqual(payload["merge"]["arrays"], "replace")

    def test_invalid_project_json_has_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "project.json"
            for contents in ('{"flows":', '[]', '{"modules": [], "flows": []}'):
                path.write_text(contents, encoding="utf-8")
                result = subprocess.run([sys.executable, "-m", "microflow", "check", str(path), "--ephemeral"],
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                diagnostic = json.loads(result.stdout)["diagnostic"]
                self.assertEqual(diagnostic["source_file"], str(path.resolve()))
                self.assertEqual(result.stderr, "")

    def test_module_help_and_version(self):
        result = subprocess.run([sys.executable, "-m", "microflow", "--help"],
                                text=True, capture_output=True, check=True)
        self.assertIn("describe", result.stdout)
        version = subprocess.run([sys.executable, "-m", "microflow", "--version"],
                                 text=True, capture_output=True, check=True)
        self.assertEqual(version.stdout.strip(), "0.1.0")

    def test_registration_via_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            module, _, _ = _write_fixture(Path(directory))
            result = subprocess.run([sys.executable, "-m", "microflow", "describe", module],
                                    text=True, capture_output=True, check=True)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["operators"][0]["ref"], "quote.calculate@1")
            self.assertEqual(payload["schemas"], ["quote.input@1", "quote.output@1"])

    def test_missing_file_is_structured_failure(self):
        result = subprocess.run([sys.executable, "-m", "microflow", "describe",
                                 str(ROOT / "absent.py")], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["diagnostic"]["error_code"], "FILE_UNAVAILABLE")

    def test_type_marker_is_distributed(self):
        self.assertTrue(importlib.resources.files("microflow").joinpath("py.typed").is_file())

    def test_check_and_run_with_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            _, project, source = _write_fixture(Path(directory))
            checked = subprocess.run([sys.executable, "-m", "microflow", "check", project, "--ephemeral"],
                                     capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(checked.stdout)["flows"], ["quote"])
            ran = subprocess.run([sys.executable, "-m", "microflow", "run", project, "quote",
                                  source, "--ephemeral"],
                                 capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(ran.stdout)["output"]["data"], {"total": 3900})

    def test_run_requires_explicit_ephemeral_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            _, project, _ = _write_fixture(Path(directory))
            result = subprocess.run([sys.executable, "-m", "microflow", "check", project],
                                    capture_output=True)
            self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
