"""MCP bridge protocol and tool behavior tests (stdlib only, no live stdio)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from microflow_mcp.server import handle_message, serve
from microflow_mcp.tools import TOOLS

ROOT = Path(__file__).resolve().parent.parent
PYTHON_SRC = ROOT.parent / "MicroFlow4Python" / "src"


def by_name(name):
    return next(tool for tool in TOOLS if tool.name == name)


class ProtocolTests(unittest.TestCase):
    def test_initialize_negotiates_and_advertises_tools_capability(self):
        response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-06-18"}}, TOOLS)
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(response["result"]["serverInfo"]["name"], "microflow-mcp")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_notifications_produce_no_response(self):
        self.assertIsNone(handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, TOOLS))
        self.assertIsNone(handle_message({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                          "params": {"requestId": 9}}, TOOLS))

    def test_tools_list_exposes_the_twelve_command_tools(self):
        response = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, TOOLS)
        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(len(names), 12)
        self.assertIn("microflow_check", names)
        self.assertIn("microflow_run", names)
        self.assertIn("microflow_context", names)
        self.assertIn("microflow_scaffold", names)
        for tool in response["result"]["tools"]:
            self.assertIn("description", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_unknown_tool_and_method_and_malformed_requests(self):
        self.assertEqual(handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                         "params": {"name": "absent"}}, TOOLS)["error"]["code"], -32602)
        self.assertEqual(handle_message({"jsonrpc": "2.0", "id": 4, "method": "resources/list"}, TOOLS)
                         ["error"]["code"], -32601)
        self.assertEqual(handle_message({"jsonrpc": "2.0", "id": 5}, TOOLS)["error"]["code"], -32600)
        self.assertEqual(handle_message("not a dict", TOOLS)["error"]["code"], -32600)

    def test_serve_loop_replies_line_by_line_and_survives_bad_lines(self):
        import io
        incoming = "\n".join([
            "not json",
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            "",
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]) + "\n"
        out = io.StringIO()
        serve(TOOLS, stdin=io.StringIO(incoming), stdout=out)
        lines = [json.loads(line) for line in out.getvalue().strip().splitlines()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertEqual(lines[1]["result"], {})
        self.assertEqual(len(lines[2]["result"]["tools"]), 12)


class ToolBehaviorTests(unittest.TestCase):
    def _call(self, name, arguments):
        return json.loads(by_name(name).invoke(arguments)["content"][0]["text"])

    def test_capabilities_envelope_lists_twelve_cli_commands(self):
        result = by_name("microflow_capabilities").invoke({})
        self.assertFalse(result["isError"])
        envelope = json.loads(result["content"][0]["text"])
        self.assertEqual(envelope["protocol"], "microflow-cli-v1")
        self.assertEqual(set(envelope["commands"]),
                         {"capabilities", "check", "context", "describe", "diagnostics", "impact",
                          "operators", "policy-check", "policy-schema", "run", "scaffold", "schema"})

    def test_bridge_rejects_relative_paths_without_spawning_the_cli(self):
        result = by_name("microflow_check").invoke({"project": "relative/project.json"})
        self.assertTrue(result["isError"])
        envelope = json.loads(result["content"][0]["text"])
        self.assertEqual(envelope["diagnostic"]["error_code"], "INVALID_ARGUMENT")

    def test_missing_project_file_is_rejected(self):
        result = by_name("microflow_check").invoke({"project": "/definitely/absent.json"})
        self.assertTrue(result["isError"])
        envelope = json.loads(result["content"][0]["text"])
        self.assertEqual(envelope["diagnostic"]["error_code"], "FILE_UNAVAILABLE")

    def test_check_run_context_round_trip_on_a_real_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module = root / "ops.py"
            module.write_text(
                "SCHEMA = {'type': 'object', 'properties': {'n': {'type': 'integer'}}, 'required': ['n']}\n"
                "def bump(input, output, context, metrix, debug, log):\n"
                "    output.set('n', input['n'] + 1)\n"
                "    return True\n"
                "def register(registry):\n"
                "    registry.register_schema('ints', SCHEMA)\n"
                "    registry.register_operator(name='bump', version='1', method=bump,"
                " input_schema='ints', output_schema='ints')\n", encoding="utf-8")
            project = root / "project.json"
            project.write_text(json.dumps({
                "modules": ["ops.py"],
                "flows": [{"id": "main", "input_schema": "ints", "output_schema": "ints",
                           "nodes": {"step": {"operator": "bump@1",
                                              "inputs": {"n": {"from": "flow.input.n", "required": True}}}},
                           "outputs": {"n": {"from": "nodes.step.output.data.n", "required": True}}}],
            }), encoding="utf-8")
            checked = self._call("microflow_check", {"project": str(project)})
            self.assertEqual(checked["diagnostics"], [])
            ran = self._call("microflow_run", {"project": str(project), "flow": "main", "input": {"n": 2}})
            self.assertEqual(ran["output"]["data"], {"n": 3})
            context = self._call("microflow_context", {"project": str(project), "operator_ref": "bump@1"})
            self.assertEqual(context["context"]["flows"], ["main"])

    def test_scaffold_generates_files_through_the_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            into = Path(tmp) / "gen"
            result = by_name("microflow_scaffold").invoke(
                {"kind": "operator", "name": "demo_op", "into": str(into)})
            self.assertFalse(result["isError"], result["content"][0]["text"])
            self.assertTrue((into / "demo_op_operator.py").exists())

    def test_impact_requires_exactly_one_selector(self):
        result = by_name("microflow_impact").invoke({"project": "/x.json"})
        self.assertTrue(result["isError"])
        result = by_name("microflow_impact").invoke({"project": "/x.json", "operator": "a@1",
                                                     "flow": "main"})
        self.assertTrue(result["isError"])


class StdioEndToEndTests(unittest.TestCase):
    """One real subprocess round trip: initialize -> tools/list -> tools/call."""

    def test_subprocess_stdio_round_trip(self):
        server = subprocess.run(
            [sys.executable, "-c",
             "from microflow_mcp.tools import TOOLS; from microflow_mcp.server import serve; serve(TOOLS)"],
            input="\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18"}}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "microflow_capabilities", "arguments": {}}}),
            ]) + "\n",
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(PYTHON_SRC)])},
            cwd=str(ROOT))
        lines = [json.loads(line) for line in server.stdout.strip().splitlines()]
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "microflow-mcp")
        envelope = json.loads(lines[1]["result"]["content"][0]["text"])
        self.assertEqual(envelope["implementation"], "python")
        self.assertFalse(lines[1]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
