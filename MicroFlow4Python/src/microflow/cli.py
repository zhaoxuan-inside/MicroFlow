"""Standard-library CLI. Only implemented capabilities are exposed."""
import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from . import __version__
from .errors import MicroFlowError
from .registry import discover
from .compiler import compile_release
from .releases import build_candidate
from .runtime import LocalRuntime
from .values import load_json, thaw
from .errors import ContractError
from .policy import describe_policy, validate_policy


def _read_project(path):
    config = load_json(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) - {"modules", "flows", "defaults"}:
        raise ContractError("INVALID_PROJECT", "Expected modules, flows and optional defaults")
    if not isinstance(config.get("modules"), list) or any(type(p) is not str for p in config["modules"]):
        raise ContractError("INVALID_PROJECT", "modules must list trusted Python file paths")
    if not isinstance(config.get("flows"), list) or not config["flows"]:
        raise ContractError("INVALID_PROJECT", "flows must be a nonempty list")
    defaults = config.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ContractError("INVALID_PROJECT", "defaults must be an object")
    validate_policy(defaults)
    # --ephemeral is explicit at the command boundary and changes only defaults;
    # a node that asks for durability remains invalid without a real provider.
    defaults = {**defaults, "durability": "ephemeral", "recovery": {"enabled": False}}
    registry = discover([path.parent / p for p in config["modules"]])
    return compile_release(registry, config["flows"], defaults=defaults, source_file=str(path.resolve()))


def _load_project(path):
    try:
        return _read_project(path)
    except MicroFlowError as exc:
        exc.diagnostic = replace(exc.diagnostic, source_file=exc.diagnostic.source_file or str(path.resolve()))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(prog="microflow", description="MicroFlow framework tools")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("policy-schema", help="Describe versioned policy fields, defaults and merge semantics")
    describe = commands.add_parser("describe", help="Register explicitly listed trusted Python files")
    describe.add_argument("files", nargs="+", type=Path)
    for name, help_text in (("check", "Compile and verify a local candidate"),
                            ("run", "Execute a local synchronous flow")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("project", type=Path)
        command.add_argument("--ephemeral", action="store_true", required=True,
                             help="Explicitly allow local execution without durability or recovery")
        if name == "run":
            command.add_argument("flow")
            command.add_argument("input", type=Path)
    args = parser.parse_args(argv)
    try:
        code = 0
        if args.command == "policy-schema":
            result = describe_policy()
        elif args.command == "describe":
            registry = discover(args.files)
            result = {"protocol": "microflow-cli-v1", "operators": registry.describe(),
                      "schemas": sorted(registry.schemas)}
        else:
            release = _load_project(args.project)
            candidate = build_candidate(release)
            if args.command == "check":
                result = {"protocol": "microflow-cli-v1", "releaseId": candidate.release_id,
                          "durability": "ephemeral", "flows": sorted(release.flows),
                          "diagnostics": [thaw(d) for p in release.flows.values() for d in p.diagnostics]}
            else:
                outcome = LocalRuntime(release).run(args.flow, load_json(args.input.read_text(encoding="utf-8")))
                result = {"protocol": "microflow-cli-v1", "durability": "ephemeral",
                          "output": thaw(outcome.output), "nodes": thaw(outcome.nodes)}
                code = 0 if outcome.output["meta"]["status"] == "SUCCEEDED" else 1
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return code
    except MicroFlowError as exc:
        print(json.dumps({"protocol": "microflow-cli-v1", "diagnostic": asdict(exc.diagnostic)},
                         ensure_ascii=True, sort_keys=True))
        return 2
    except OSError:
        print(json.dumps({"protocol": "microflow-cli-v1", "diagnostic": {
            "error_code": "FILE_UNAVAILABLE", "message": "Cannot read an input file"}}))
        return 2
