"""Compile immutable definitions, mappings, control edges and effective policies."""
from dataclasses import dataclass, field, replace
from collections.abc import Mapping
import json
from . import expressions
from .errors import ContractError, MicroFlowError
from .graph import Graph, compile_graph
from .paths import Field, parse, check_rules
from .compatibility import schema_at, compatible, PROVED_INCOMPATIBLE, UNKNOWN
from .policy import EffectiveOperatorPolicy, resolve, validate_policy
from .registry import Registry
from .values import digest, freeze, thaw, validate_value


@dataclass(frozen=True)
class FlowPlan:
    flow_id: str
    definition: Mapping
    graph: Graph
    policies: Mapping[str, EffectiveOperatorPolicy]
    diagnostics: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class CompiledRelease:
    release_id: str
    registry: Registry
    flows: Mapping[str, FlowPlan]
    manifest: Mapping
    sources: Mapping


def _rules(rules):
    check_rules(rules)
    for rule in rules.values():
        yield rule["from"]


def compile_release(registry: Registry, flows: list[Mapping], *, defaults=None,
                    provider_capabilities=None, source_file="") -> CompiledRelease:
    location = {"source_file": str(source_file), "flow_id": "", "node_id": ""}
    try:
        return _compile_release(registry, flows, defaults=defaults,
                                provider_capabilities=provider_capabilities, location=location)
    except MicroFlowError as error:
        diagnostic = error.diagnostic
        edge_locations = [s for e in diagnostic.details.get("edges", []) for s in e["source_locations"]]
        origin = edge_locations[0] if edge_locations else location
        error.diagnostic = replace(diagnostic, source_file=diagnostic.source_file or str(source_file),
                                   flow_id=origin.get("flow_id", ""), node_id=origin.get("node_id", ""),
                                   expected=diagnostic.details.get("expected", diagnostic.expected),
                                   actual=diagnostic.details.get("actual", diagnostic.actual),
                                   hint=diagnostic.hint or "Correct the referenced definition and compile again.")
        raise


def _compile_release(registry, flows, *, defaults, provider_capabilities, location):
    defaults = {} if defaults is None else defaults
    validate_policy(defaults)
    validate_value(flows)
    if not isinstance(flows, (list, tuple)):
        raise ContractError("INVALID_FLOW", "Expected a list of flow definitions")
    registry.seal()
    definitions = {}
    flow_indexes = {}
    for index, flow in enumerate(flows):
        if not isinstance(flow, Mapping) or not isinstance(flow.get("id"), str) or not flow["id"]:
            raise ContractError("INVALID_FLOW", "Flow needs a stable id")
        if flow["id"] in definitions:
            raise ContractError("DUPLICATE_FLOW", "Duplicate flow", flow["id"])
        if set(flow) - {"id", "input_schema", "output_schema", "nodes", "outputs", "options"}:
            raise ContractError("UNKNOWN_FLOW_FIELD", "Unknown flow fields", flow["id"])
        definitions[flow["id"]] = thaw(flow)
        flow_indexes[flow["id"]] = index
    references = []
    reference_sources = {}
    plans = {}
    for flow_id, definition in definitions.items():
        location.update(flow_id=flow_id, node_id="")
        for role in ("input_schema", "output_schema"):
            if type(definition.get(role)) is not str or definition[role] not in registry.schemas:
                raise ContractError("UNKNOWN_SCHEMA", "Unknown flow schema", f"{flow_id}.{role}")
        options = definition.get("options", {})
        if (not isinstance(options, Mapping) or set(options) - {"scene", "version"}
                or any(type(v) is not str or not v for v in options.values())):
            raise ContractError("INVALID_FLOW_OPTIONS", "Only nonempty scene and version strings are supported", flow_id)
        nodes = definition.get("nodes", {})
        if not isinstance(nodes, Mapping):
            raise ContractError("INVALID_FLOW", "nodes must be an object", flow_id)
        edges = []
        edge_sources = {}
        checked_sources = []
        def add_edge(u, v, path, kind, *, is_reference=False):
            collection, origins = (references, reference_sources) if is_reference else (edges, edge_sources)
            collection.append((u, v))
            origins.setdefault((u, v), []).append({**location, "path": path, "kind": kind})

        flow_path = f"flows[{flow_indexes[flow_id]}]"
        policies = {}
        for node_id, node in nodes.items():
            location["node_id"] = node_id
            if not isinstance(node_id, str) or not node_id or not isinstance(node, Mapping):
                raise ContractError("INVALID_NODE", "Invalid node declaration", flow_id)
            known = {"type", "operator", "flow", "inputs", "depends_on", "policy", "condition",
                     "branches", "default", "join", "items", "max_items", "max_iterations",
                     "until", "signal", "result_schema"}
            if set(node) - known:
                raise ContractError("UNKNOWN_NODE_FIELD", "Unknown node field", node_id)
            kind = node.get("type", "operator")
            if kind not in ("operator", "subflow", "route", "join", "map", "loop", "wait"):
                raise ContractError("INVALID_NODE_TYPE", "Unsupported node type", node_id)
            fields = {"operator": {"operator"}, "subflow": {"flow"},
                      "route": {"branches", "default"}, "join": {"join"},
                      "map": {"flow", "items", "max_items"},
                      "loop": {"flow", "until", "max_iterations"}, "wait": {"signal", "result_schema"}}
            if set(node) - ({"type", "inputs", "depends_on", "policy", "condition"} | fields[kind]):
                raise ContractError("INVALID_NODE_FIELD", "Field is not applicable to this node type", node_id)
            node_path = flow_path + f".nodes[{json.dumps(node_id)}]"
            caps = {"effect": "pure", "idempotency_support": "natural"}
            op_defaults = {}
            if kind == "operator":
                if type(node.get("operator")) is not str or node["operator"] not in registry.operators:
                    raise ContractError("UNKNOWN_OPERATOR", "Unknown operator", node_id)
                op = registry.operators[node["operator"]]
                caps, op_defaults = op.capabilities, op.default_policy
            if kind in ("subflow", "map", "loop"):
                if type(node.get("flow")) is not str or node["flow"] not in definitions:
                    raise ContractError("UNKNOWN_FLOW", "Unknown child flow", node_id)
                add_edge(flow_id, node["flow"], node_path + ".flow", "subflow", is_reference=True)
            if kind == "map":
                if type(node.get("items")) is not str:
                    raise ContractError("INVALID_NODE", "Map needs an items source path", node_id)
                if type(node.get("max_items")) is not int or node["max_items"] < 1:
                    raise ContractError("INVALID_NODE", "Map needs a positive max_items", node_id)
            if kind == "loop":
                if type(node.get("max_iterations")) is not int or node["max_iterations"] < 1:
                    raise ContractError("INVALID_NODE", "Loop needs a positive max_iterations", node_id)
                expressions.check(node.get("until"))
            if kind == "wait":
                if (not isinstance(node.get("signal"), str) or not node["signal"] or type(node.get("result_schema")) is not str
                        or node["result_schema"] not in registry.schemas):
                    raise ContractError("INVALID_NODE", "Wait needs signal and result_schema", node_id)
            if kind == "join" and node.get("join", "all_active_success") != "all_active_success":
                raise ContractError("UNSUPPORTED_JOIN", "Only all_active_success is currently implemented", node_id)
            check_rules(node.get("inputs", {}))
            source_paths = [(rule["from"], node_path + f".inputs[{json.dumps(target)}].from")
                            for target, rule in node.get("inputs", {}).items()]
            if "condition" in node:
                expressions.check(node["condition"])
                source_paths += [(p, node_path + ".condition") for p in expressions.paths(node["condition"])]
            if kind == "loop":
                source_paths += [(p, node_path + ".until") for p in expressions.paths(node["until"])]
            if kind == "route":
                branches = node.get("branches", [])
                if not isinstance(branches, (list, tuple)) or not branches:
                    raise ContractError("INVALID_ROUTE", "Route needs ordered branches", node_id)
                for index, branch in enumerate(branches):
                    if (not isinstance(branch, Mapping) or set(branch) != {"when", "target"}
                            or type(branch["target"]) is not str or not branch["target"]):
                        raise ContractError("INVALID_ROUTE", "Branch needs when and target", node_id)
                    expressions.check(branch["when"])
                    source_paths += [(p, node_path + f".branches[{index}].when") for p in expressions.paths(branch["when"])]
                    add_edge(node_id, branch["target"], node_path + f".branches[{index}].target", "route")
                if "default" not in node:
                    raise ContractError("INVALID_ROUTE", "Declare a default target or null", node_id)
                if node["default"] is not None:
                    if type(node["default"]) is not str or not node["default"]:
                        raise ContractError("INVALID_ROUTE", "Default must be a node id or null", node_id)
                    add_edge(node_id, node["default"], node_path + ".default", "route")
            if kind == "map":
                source_paths.append((node["items"], node_path + ".items"))
            depends = node.get("depends_on", [])
            if not isinstance(depends, (list, tuple)) or any(not isinstance(x, str) for x in depends):
                raise ContractError("INVALID_DEPENDENCY", "depends_on must be a list", node_id)
            for index, parent in enumerate(depends):
                add_edge(parent, node_id, node_path + f".depends_on[{index}]", "control")
            for source, source_location in source_paths:
                checked_sources.append((source, node_id))
                tokens = parse(source)
                if not isinstance(tokens[0], Field) or tokens[0].name not in ("flow", "nodes", "context"):
                    raise ContractError("INVALID_SOURCE", "Source must start with flow/nodes/context", source)
                if tokens[0].name == "nodes":
                    if len(tokens) < 3 or not isinstance(tokens[1], Field) or not isinstance(tokens[2], Field) or tokens[2].name != "output":
                        raise ContractError("INVALID_SOURCE", "Expected nodes.<id>.output", source)
                    add_edge(tokens[1].name, node_id, source_location, "data")
            policy = resolve(defaults or {}, op_defaults, node.get("policy", {}),
                             capabilities=caps, provider_capabilities=provider_capabilities)
            if kind == "operator" and op.fallback:
                resolve(policy.values, capabilities=op.fallback_capabilities,
                        provider_capabilities=provider_capabilities)
            policies[node_id] = policy
        location["node_id"] = ""
        graph = compile_graph(nodes, edges, edge_sources=edge_sources)
        diagnostics = []

        def source_schema(source):
            tokens = parse(source)
            if tokens[0] == Field("context"):
                return None
            if tokens[:2] == (Field("flow"), Field("input")):
                return schema_at(registry.schemas[definition["input_schema"]], tokens[2:], source)
            if (len(tokens) >= 4 and tokens[0] == Field("nodes") and isinstance(tokens[1], Field)
                    and tokens[2:4] == (Field("output"), Field("data"))):
                if tokens[1].name not in nodes:
                    raise ContractError("UNKNOWN_NODE", "Source references unknown node", source)
                parent = nodes[tokens[1].name]
                if parent.get("type", "operator") == "operator":
                    schema = registry.schemas[registry.operators[parent["operator"]].output_schema]
                elif parent.get("type") == "subflow":
                    schema = registry.schemas[definitions[parent["flow"]]["output_schema"]]
                elif parent.get("type") == "wait":
                    schema = registry.schemas[parent["result_schema"]]
                else:
                    return None
                return schema_at(schema, tokens[4:], source)
            raise ContractError("INVALID_SOURCE", "Expected flow.input, nodes.<id>.output.data or context", source)

        def check_mapping(rules, target_schema, mapping_path):
            for target, rule in rules.items():
                source = source_schema(rule["from"])
                target_path = mapping_path + f"[{json.dumps(target)}]"
                dest = schema_at(target_schema, parse(target), target_path)
                proof = compatible(source, dest)
                if proof == PROVED_INCOMPATIBLE:
                    raise ContractError("SCHEMA_INCOMPATIBLE", "Source and destination types are incompatible",
                                        target_path, source_path=rule["from"],
                                        expected=dest["type"], actual=source["type"])
                if proof == UNKNOWN:
                    diagnostics.append(freeze({"error_code": "SCHEMA_COMPATIBILITY_UNKNOWN", "severity": "warning",
                                               "message": "Static compatibility could not be proved",
                                               "path": target_path, "proof": UNKNOWN,
                                               "source_file": source_file, "flow_id": flow_id,
                                               "node_id": diagnostic_node, "release_id": "",
                                               "expected": "statically proved compatibility", "actual": UNKNOWN,
                                               "hint": "Runtime schema validation remains required."}))
                if "default" in rule and dest is not None:
                    from .schema import validate
                    validate(rule["default"], dest, target_path + ".default")

        source_file = location["source_file"]
        for source, node_id in checked_sources:
            location["node_id"] = node_id
            source_schema(source)
        for node_id, node in nodes.items():
            location["node_id"] = node_id
            diagnostic_node = node_id
            if node.get("type") == "map":
                items_schema = source_schema(node["items"])
                if items_schema is not None and items_schema["type"] != "array":
                    raise ContractError("SCHEMA_INCOMPATIBLE", "Map items must resolve to an array",
                                        flow_path + f".nodes[{json.dumps(node_id)}].items",
                                        expected="array", actual=items_schema["type"])
            if node.get("type", "operator") == "operator":
                target_schema = registry.schemas[registry.operators[node["operator"]].input_schema]
                check_mapping(node.get("inputs", {}), target_schema, flow_path + f".nodes[{json.dumps(node_id)}].inputs")
            elif node.get("type") == "subflow":
                target_schema = registry.schemas[definitions[node["flow"]]["input_schema"]]
                check_mapping(node.get("inputs", {}), target_schema, flow_path + f".nodes[{json.dumps(node_id)}].inputs")
        location["node_id"] = ""
        diagnostic_node = ""
        for source in _rules(definition.get("outputs", {})):
            source_schema(source)
        check_mapping(definition.get("outputs", {}), registry.schemas[definition["output_schema"]], flow_path + ".outputs")
        plans[flow_id] = FlowPlan(flow_id, freeze(definition), graph, freeze(policies), tuple(diagnostics))
    location.update(flow_id="", node_id="")
    compile_graph(definitions, references, edge_sources=reference_sources)
    # Hash actual module bytes as well as definitions/contracts, not just version labels.
    import hashlib
    from pathlib import Path
    sources = dict(registry.sources)
    for path, content in sources.items():
        if Path(path).read_bytes() != content:
            raise ContractError("SOURCE_CHANGED", "Registered source changed before compilation", path)
    for op in registry.operators.values():
        if op.source_file and op.source_file not in sources:
            sources[op.source_file] = Path(op.source_file).read_bytes()
    manifest = {"protocol": "microflow-release-v1", "compiler": "0.1.0",
                "flows": definitions, "schemas": thaw(registry.schemas),
                "operators": [{**d, "default_policy": thaw(registry.operators[d["ref"]].default_policy)}
                              for d in registry.describe()],
                "sources": {p: hashlib.sha256(b).hexdigest() for p, b in sources.items()},
                "defaults": thaw(defaults or {}),
                "policies": {f: {n: p.policy_digest for n, p in plan.policies.items()} for f, plan in plans.items()}}
    release_id = digest(manifest)
    plans = {f: replace(p, diagnostics=tuple(freeze({**d, "release_id": release_id}) for d in p.diagnostics))
             for f, p in plans.items()}
    return CompiledRelease(release_id, registry, freeze(plans), freeze(manifest), freeze(sources))
