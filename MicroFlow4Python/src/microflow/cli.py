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
from .impact import (build_index, describe_index, describe_references, flow_references,
                     operator_flows, operator_references, upstream_flows)
from .codes import describe_diagnostics

# Machine-readable command catalog (design: docs/design/cli-command-system-design.md §3).
# resultKeys are the command-specific envelope keys; ephemeral records whether the
# command requires or rejects the explicit local boundary flag.
CAPABILITIES = {
    "capabilities": {"args": [], "ephemeral": "rejected",
                     "resultKeys": ["implementation", "implementationVersion", "commands"]},
    "check": {"args": ["project"], "ephemeral": "required",
              "resultKeys": ["releaseId", "durability", "flows", "diagnostics"]},
    "describe": {"args": ["files..."], "ephemeral": "rejected",
                 "resultKeys": ["operators", "schemas"]},
    "diagnostics": {"args": [], "ephemeral": "rejected",
                    "resultKeys": ["count", "diagnostics"]},
    "impact": {"args": ["project"], "flags": ["--operator REF", "--flow ID"], "ephemeral": "required",
               "resultKeys": ["releaseId", "durability", "impact"]},
    "operators": {"args": ["project"], "ephemeral": "required",
                  "resultKeys": ["releaseId", "durability", "operators"]},
    "policy-check": {"args": ["config"], "ephemeral": "rejected",
                     "resultKeys": ["policyChecked", "topLevelFields"]},
    "policy-schema": {"args": [], "ephemeral": "rejected",
                      "resultKeys": ["protocol", "schema", "defaults", "merge"]},
    "run": {"args": ["project", "flow", "input"], "ephemeral": "required",
            "resultKeys": ["durability", "output", "nodes"]},
    "schema": {"args": ["project", "name"], "ephemeral": "required",
               "resultKeys": ["releaseId", "schema", "definition"]},
}


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
    commands.add_parser("capabilities", help="Implementation and command catalog for tool probing")
    commands.add_parser("diagnostics", help="Diagnostic code catalog")
    commands.add_parser("policy-schema", help="Describe versioned policy fields, defaults and merge semantics")
    describe = commands.add_parser("describe", help="Register explicitly listed trusted Python files")
    describe.add_argument("files", nargs="+", type=Path)
    policy_check = commands.add_parser("policy-check", help="Validate a partial policy configuration layer")
    policy_check.add_argument("config", type=Path)
    schema_cmd = commands.add_parser("schema", help="Query one contract schema from a compiled project")
    schema_cmd.add_argument("project", type=Path)
    schema_cmd.add_argument("name")
    schema_cmd.add_argument("--ephemeral", action="store_true", required=True,
                            help="Explicit local compile boundary")
    operators_cmd = commands.add_parser("operators", help="Operator catalog with static reference counts")
    operators_cmd.add_argument("project", type=Path)
    operators_cmd.add_argument("--ephemeral", action="store_true", required=True,
                               help="Explicit local compile boundary")
    for name, help_text in (("check", "Compile and verify a local candidate"),
                            ("run", "Execute a local synchronous flow")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("project", type=Path)
        command.add_argument("--ephemeral", action="store_true", required=True,
                             help="Explicitly allow local execution without durability or recovery")
        if name == "run":
            command.add_argument("flow")
            command.add_argument("input", type=Path)
    impact = commands.add_parser("impact", help="Build the static impact reverse index for a project")
    impact.add_argument("project", type=Path)
    impact.add_argument("--ephemeral", action="store_true", required=True,
                        help="Explicit local compile boundary; the static index itself is policy independent")
    query = impact.add_mutually_exclusive_group()
    query.add_argument("--operator", help="References and upstream flows of one operator ref")
    query.add_argument("--flow", help="Direct references and upstream flows of one flow id")
    args = parser.parse_args(argv)
    try:
        code = 0
        if args.command == "policy-schema":
            result = describe_policy()
        elif args.command == "describe":
            registry = discover(args.files)
            result = {"protocol": "microflow-cli-v1", "operators": registry.describe(),
                      "schemas": sorted(registry.schemas)}
        elif args.command == "capabilities":
            result = {"protocol": "microflow-cli-v1", "implementation": "python",
                      "implementationVersion": __version__, "commands": CAPABILITIES}
        elif args.command == "diagnostics":
            described = describe_diagnostics()
            result = {"protocol": "microflow-cli-v1", "count": described["count"],
                      "diagnostics": described["diagnostics"]}
        elif args.command == "policy-check":
            config = load_json(args.config.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ContractError("INVALID_POLICY", "Policy layer must be an object")
            validate_policy(config)
            result = {"protocol": "microflow-cli-v1", "policyChecked": True,
                      "topLevelFields": sorted(config)}
        elif args.command == "schema":
            release = _load_project(args.project)
            if args.name not in release.registry.schemas:
                raise ContractError("UNKNOWN_SCHEMA", "Unknown schema", args.name)
            result = {"protocol": "microflow-cli-v1", "releaseId": release.release_id,
                      "schema": args.name, "definition": thaw(release.registry.schemas[args.name])}
        elif args.command == "operators":
            release = _load_project(args.project)
            index = build_index(release)
            operators = []
            for op_ref, op in sorted(release.registry.operators.items()):
                refs = index.operators.get(op_ref, ())
                operators.append({"ref": op_ref, "description": op.description,
                                  "inputSchema": op.input_schema, "outputSchema": op.output_schema,
                                  "capabilities": thaw(op.capabilities),
                                  "fallbackCapabilities": thaw(op.fallback_capabilities),
                                  "defaultPolicy": thaw(op.default_policy), "sourceFile": op.source_file,
                                  "staticReferences": len(refs),
                                  "referencingFlows": sorted({r.flow for r in refs})})
            result = {"protocol": "microflow-cli-v1", "releaseId": release.release_id,
                      "durability": "ephemeral", "operators": operators}
        elif args.command == "impact":
            release = _load_project(args.project)
            index = build_index(release)
            if args.operator is not None:
                using = operator_flows(index, args.operator)
                upstream = tuple(sorted({u for flow_id in using for u in upstream_flows(index, flow_id)}))
                body = {"protocol": index.protocol, "release_id": release.release_id,
                        "operator": args.operator,
                        "references": describe_references(operator_references(index, args.operator)),
                        "flows": list(using), "upstream_flows": list(upstream)}
            elif args.flow is not None:
                body = {"protocol": index.protocol, "release_id": release.release_id,
                        "flow": args.flow,
                        "references": describe_references(flow_references(index, args.flow)),
                        "upstream_flows": list(upstream_flows(index, args.flow))}
            else:
                body = describe_index(index)
            result = {"protocol": "microflow-cli-v1", "releaseId": release.release_id,
                      "durability": "ephemeral", "impact": body}
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
