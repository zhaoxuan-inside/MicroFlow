"""Tool registry: one MCP tool per CLI command, argv passing, no shell.

Discipline is embedded in the tool descriptions the agent reads before
calling: probe capabilities first, require zero diagnostics before run, and
never treat a successful call as business success. The bridge adds no
semantics of its own — every result is the CLI's deterministic envelope.
"""
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CLI_TIMEOUT_SECONDS = 120

_TEXT = "Text output is the CLI's `microflow-cli-v1` JSON envelope."


def _run_cli(arguments: list[str], *, timeout: int = CLI_TIMEOUT_SECONDS):
    """One CLI invocation; argv list only, never a shell string."""
    try:
        done = subprocess.run(
            [sys.executable, "-m", "microflow", *arguments],
            capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 2, "", json.dumps({"protocol": "microflow-cli-v1", "diagnostic": {
            "error_code": "CLI_TIMEOUT", "message": f"CLI exceeded {timeout}s"}})
    except OSError as error:
        return 2, "", json.dumps({"protocol": "microflow-cli-v1", "diagnostic": {
            "error_code": "CLI_UNAVAILABLE", "message": f"Cannot launch the CLI: {error}"}})
    return done.returncode, done.stdout, done.stderr


def _result(text: str, *, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _cli_tool(argv_builder: Callable[[dict], object]):
    """Builders return an argv list, or (argv, cleanup) when a temp file is involved."""
    def invoke(arguments: dict) -> dict:
        cleanup = None
        try:
            built = argv_builder(arguments or {})
            argv, cleanup = built if isinstance(built, tuple) else (built, None)
        except ContractViolation as error:
            return _result(error.envelope(), is_error=True)
        try:
            code, stdout, stderr = _run_cli(argv)
        finally:
            if cleanup is not None:
                cleanup()
        text = stdout.strip() or stderr.strip() or "{}"
        return _result(text, is_error=code != 0)
    return invoke


class ContractViolation(Exception):
    """Bridge-side argument rejection; emits a CLI-shaped diagnostic envelope."""

    def __init__(self, code: str, message: str, path: str = ""):
        super().__init__(f"{code}: {message}")
        self._envelope = {"protocol": "microflow-cli-v1",
                          "diagnostic": {"error_code": code, "message": message, "path": path}}

    def envelope(self) -> str:
        return json.dumps(self._envelope, ensure_ascii=True, sort_keys=True)


def _string(arguments: dict, field: str, *, required=True) -> str:
    value = arguments.get(field)
    if value is None:
        if required:
            raise ContractViolation("INVALID_ARGUMENT", f"Missing required argument: {field}", field)
        return ""
    if type(value) is not str or not value.strip():
        raise ContractViolation("INVALID_ARGUMENT", f"{field} must be a nonempty string", field)
    return value


def _absolute(arguments: dict, field: str, *, required=True) -> str:
    value = _string(arguments, field, required=required)
    if not value:
        return ""
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ContractViolation("INVALID_ARGUMENT", f"{field} must be an absolute path", field)
    return str(path)


def _existing_file(arguments: dict, field: str) -> str:
    value = _absolute(arguments, field)
    if not Path(value).is_file():
        raise ContractViolation("FILE_UNAVAILABLE", f"{field} is not an existing file", value)
    return value


def _object(arguments: dict, field: str) -> object:
    if field not in arguments or arguments[field] is None:
        raise ContractViolation("INVALID_ARGUMENT", f"Missing required argument: {field}", field)
    return arguments[field]


def _ephemeral(arguments: dict) -> list[str]:
    # The explicit local boundary is mandatory for compile/execute commands;
    # the bridge sets it so agents cannot forget it.
    return ["--ephemeral"]


# --- argv builders -----------------------------------------------------------


def _argv_capabilities(_):
    return ["capabilities"]


def _argv_diagnostics(_):
    return ["diagnostics"]


def _argv_policy_schema(_):
    return ["policy-schema"]


def _argv_policy_check(arguments):
    return ["policy-check", _existing_file(arguments, "config")]


def _argv_describe(arguments):
    files = _object(arguments, "files")
    if not isinstance(files, list) or not files or any(type(item) is not str for item in files):
        raise ContractViolation("INVALID_ARGUMENT", "files must be a nonempty array of paths", "files")
    resolved = [str(Path(item).expanduser()) for item in files]
    return ["describe", *resolved], None


def _argv_check(arguments):
    return ["check", _existing_file(arguments, "project"), *_ephemeral(arguments)]


def _argv_operators(arguments):
    return ["operators", _existing_file(arguments, "project"), *_ephemeral(arguments)]


def _argv_schema(arguments):
    return ["schema", _existing_file(arguments, "project"),
            _string(arguments, "name"), *_ephemeral(arguments)]


def _argv_impact(arguments):
    operator, flow = arguments.get("operator"), arguments.get("flow")
    if bool(operator) == bool(flow):
        raise ContractViolation("INVALID_ARGUMENT",
                                "Pass exactly one of operator or flow", "operator|flow")
    if operator:
        return ["impact", _existing_file(arguments, "project"), "--operator",
                _string(arguments, "operator"), *_ephemeral(arguments)]
    return ["impact", _existing_file(arguments, "project"), "--flow",
            _string(arguments, "flow"), *_ephemeral(arguments)]


def _argv_context(arguments):
    argv = ["context", _existing_file(arguments, "project"),
            _string(arguments, "operator_ref"), *_ephemeral(arguments)]
    if arguments.get("tests_dir"):
        argv += ["--tests-dir", _absolute(arguments, "tests_dir")]
    if arguments.get("budget") is not None:
        budget = arguments["budget"]
        if type(budget) is not int or budget < 1:
            raise ContractViolation("INVALID_ARGUMENT", "budget must be a positive integer", "budget")
        argv += ["--budget", str(budget)]
    return argv


def _argv_run(arguments):
    project = _existing_file(arguments, "project")
    flow = _string(arguments, "flow")
    payload = _object(arguments, "input")
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as error:
        raise ContractViolation("INVALID_ARGUMENT", "input must be JSON-serializable", "input") from error
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle, ensure_ascii=True, sort_keys=True)
    handle.close()
    return (["run", project, flow, handle.name, *_ephemeral(arguments)],
            lambda: os.unlink(handle.name))


def _argv_test(arguments):
    argv = ["test", _existing_file(arguments, "project"), *_ephemeral(arguments)]
    if arguments.get("budget") is not None:
        budget = arguments["budget"]
        if type(budget) is not int or budget < 1:
            raise ContractViolation("INVALID_ARGUMENT", "budget must be a positive integer", "budget")
        argv += ["--budget", str(budget)]
    return argv


def _argv_scaffold(arguments):
    kind = _string(arguments, "kind")
    into = _absolute(arguments, "into")
    if kind == "operator":
        argv = ["scaffold", "operator", _string(arguments, "name"), "--into", into]
        if arguments.get("version"):
            argv += ["--version", _string(arguments, "version")]
        if arguments.get("with_fallback"):
            argv += ["--with-fallback"]
        if arguments.get("proxy"):
            argv += ["--proxy", _string(arguments, "proxy")]
        return argv
    if kind == "flow":
        argv = ["scaffold", "flow", _string(arguments, "name"), "--into", into,
                "--operator", _string(arguments, "operator"),
                "--input-schema", _string(arguments, "input_schema"),
                "--output-schema", _string(arguments, "output_schema")]
        for module in arguments.get("modules") or []:
            if type(module) is not str or not module:
                raise ContractViolation("INVALID_ARGUMENT", "modules must be path strings", "modules")
            argv += ["--module", module]
        return argv
    raise ContractViolation("INVALID_ARGUMENT", "kind must be operator or flow", "kind")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    invoke: Callable[[dict], dict]

    @property
    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema}


def _tool(name, description, schema, builder) -> Tool:
    return Tool(name, description, schema, _cli_tool(builder))


_OBJECT = {"type": "object", "properties": {}, "additionalProperties": False}
_PROJECT = {"project": {"type": "string", "description": "Absolute path of the project configuration (.mf DSL or JSON)"}}

TOOLS = [
    _tool("microflow_capabilities",
          "Probe the implementation identity, version and the full command catalog. "
          "ALWAYS call this before any other MicroFlow tool; do not assume a command exists. " + _TEXT,
          {"type": "object", "properties": {}, "additionalProperties": False}, _argv_capabilities),
    _tool("microflow_diagnostics",
          "List the diagnostic code catalog (code, summary, stability). Interpret any "
          "diagnostic via this catalog instead of guessing its meaning. " + _TEXT,
          _OBJECT, _argv_diagnostics),
    _tool("microflow_policy_schema",
          "Describe the versioned policy fields, defaults and merge semantics "
          "(execution/timeout/retry/cache/idempotency). " + _TEXT, _OBJECT, _argv_policy_schema),
    _tool("microflow_describe",
          "Register explicitly listed trusted Python operator files and print their contracts. "
          "Only pass files you intend to load as operator modules. " + _TEXT,
          {"type": "object", "properties": {"files": {"type": "array", "minItems": 1, "items": {
              "type": "string", "description": "Absolute path of a trusted Python operator module"}}},
           "required": ["files"], "additionalProperties": False}, _argv_describe),
    _tool("microflow_policy_check",
          "Validate one partial policy configuration layer before using it in a flow. " + _TEXT,
          {"type": "object", "properties": {"config": {"type": "string",
              "description": "Absolute path of the policy JSON file"}},
           "required": ["config"], "additionalProperties": False}, _argv_policy_check),
    _tool("microflow_check",
          "Compile and static-check a project (cycles, references, types, policy "
          "combinations). Gate: continue only when the envelope reports zero diagnostics. " + _TEXT,
          {"type": "object", "properties": _PROJECT, "required": ["project"],
           "additionalProperties": False}, _argv_check),
    _tool("microflow_run",
          "Execute one flow locally with the explicit ephemeral boundary (forced). "
          "Calling success is NOT business success: inspect output.meta.status and "
          "validate outputs against the declared schema. " + _TEXT,
          {"type": "object",
           "properties": {**_PROJECT, "flow": {"type": "string"},
                          "input": {"type": "object", "description": "Flow input object"}},
           "required": ["project", "flow", "input"], "additionalProperties": False}, _argv_run),
    _tool("microflow_test",
          "Run project-declared tests in isolation (tests in the project configuration: "
          "flow regression input/expectOutput pairs and operator contract cases). Every "
          "test entry must cite the origin of its expectations (business rule or confirmed "
          "sample); exit 1 lists structured failures. " + _TEXT,
          {"type": "object",
           "properties": {**_PROJECT, "budget": {"type": "integer", "minimum": 1}},
           "required": ["project"], "additionalProperties": False}, _argv_test),
    _tool("microflow_operators",
          "List the operator catalog with schemas, capabilities, default policies and "
          "static reference counts for a compiled project. " + _TEXT,
          {"type": "object", "properties": _PROJECT, "required": ["project"],
           "additionalProperties": False}, _argv_operators),
    _tool("microflow_schema",
          "Query one registered contract schema by name. Read the contract before "
          "writing mappings — do not guess field shapes. " + _TEXT,
          {"type": "object",
           "properties": {**_PROJECT, "name": {"type": "string"}},
           "required": ["project", "name"], "additionalProperties": False}, _argv_schema),
    _tool("microflow_impact",
          "Static impact preview: who references this operator/flow and which flows are "
          "upstream. Call before changing an operator or flow contract. Pass exactly one "
          "of operator/flow. " + _TEXT,
          {"type": "object",
           "properties": {**_PROJECT, "operator": {"type": "string"}, "flow": {"type": "string"}},
           "required": ["project"], "additionalProperties": False}, _argv_impact),
    _tool("microflow_context",
          "Bounded local context of one operator ref (name@version): implementation "
          "summary, schemas, direct references, upstream flows, related tests and honest "
          "runtime boundaries. Read this instead of scanning the whole repository. " + _TEXT,
          {"type": "object",
           "properties": {**_PROJECT, "operator_ref": {"type": "string"},
                          "tests_dir": {"type": "string"}, "budget": {"type": "integer", "minimum": 1}},
           "required": ["project", "operator_ref"], "additionalProperties": False}, _argv_context),
    _tool("microflow_scaffold",
          "Generate candidate skeletons into an explicit directory (never overwrites): "
          "kind=operator needs name (+version, with_fallback, proxy=metrix,log); "
          "kind=flow needs name plus operator ref, input/output schema names and modules. "
          "Generated artifacts pass the same check gate as hand-written code. " + _TEXT,
          {"type": "object",
           "properties": {"kind": {"type": "string", "enum": ["operator", "flow"]},
                          "name": {"type": "string"}, "into": {"type": "string"},
                          "version": {"type": "string"}, "with_fallback": {"type": "boolean"},
                          "proxy": {"type": "string"}, "operator": {"type": "string"},
                          "input_schema": {"type": "string"}, "output_schema": {"type": "string"},
                          "modules": {"type": "array", "items": {"type": "string"}}},
           "required": ["kind", "into"], "additionalProperties": False}, _argv_scaffold),
]


def main() -> None:
    from .server import serve
    serve(TOOLS)


if __name__ == "__main__":
    main()
