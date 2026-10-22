import importlib.resources
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from microflow.cli import _load_project
from microflow.errors import ContractError


ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_scheduled_quote_example(self):
        result = subprocess.run([sys.executable, str(ROOT / 'examples' / 'scheduled_quote.py')],
                                text=True, capture_output=True, check=True)
        payload = json.loads(result.stdout)
        self.assertTrue(payload['protocol_test'])
        self.assertEqual(payload['durability'], 'ephemeral')
        self.assertEqual(payload['output']['data']['total'], 3900)

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

    def test_example_registration_via_cli(self):
        result = subprocess.run([sys.executable, "-m", "microflow", "describe",
                                 str(ROOT / "examples" / "quote.py")],
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

    def test_check_and_run_example(self):
        project = str(ROOT / "examples" / "quote.flow.json")
        checked = subprocess.run([sys.executable, "-m", "microflow", "check", project, "--ephemeral"],
                                 capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(checked.stdout)["flows"], ["quote"])
        ran = subprocess.run([sys.executable, "-m", "microflow", "run", project, "quote",
                              str(ROOT / "examples" / "quote.input.json"), "--ephemeral"],
                             capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(ran.stdout)["output"]["data"], {"total": 3900})

    def test_run_requires_explicit_ephemeral_flag(self):
        result = subprocess.run([sys.executable, "-m", "microflow", "check",
                                 str(ROOT / "examples" / "quote.flow.json")], capture_output=True)
        self.assertEqual(result.returncode, 2)
