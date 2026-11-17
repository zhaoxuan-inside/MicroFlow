"""Canvas graph -> flow definition converter for the orchestration platform.

The orchestration console stores scenario graphs in the canvas protocol
`microflow-canvas-graph-v1` (entry/exit markers, OPERATOR/SUBGRAPH nodes and
control edges). This module converts such a graph into a MicroFlow flow
definition skeleton: node ids are kept stable, edges become control
dependencies, and the exit node feeds the single output mapping.

The converter deliberately produces a skeleton, never a finished flow: data
mappings, schemas and operator contracts cannot be invented from a control
skeleton. Missing pieces surface as advisory diagnostics (with codes from the
diagnostic catalog) and the skeleton fails `check` with the framework's own
errors until they are filled in. Control-only concepts outside the canvas
protocol (route/join/map/loop/wait) are rejected instead of approximated.
"""
import hashlib
import json
from collections.abc import Mapping

from .errors import ContractError
from .graph import compile_graph

CANVAS_PROTOCOL = "microflow-canvas-graph-v1"
_KIND_TO_NODE = {"OPERATOR": "operator", "SUBGRAPH": "subflow"}
_REF_FIELD = {"OPERATOR": "operator", "SUBGRAPH": "subgraph"}


def _advisory(code, severity, message, path, hint=""):
    return {"error_code": code, "severity": severity, "message": message, "path": path,
            "hint": hint, "source_file": "", "flow_id": "", "node_id": "", "release_id": "",
            "expected": "", "actual": ""}


def _require(condition, message, path, **details):
    if not condition:
        raise ContractError("INVALID_CANVAS_GRAPH", message, path, **details)


def convert_canvas_graph(graph, flow_id, *, input_schema=None, output_schema=None):
    """Convert one canvas graph into a flow definition skeleton.

    Returns {"protocol", "flow", "diagnostics"} where diagnostics are advisory
    entries sorted deterministically. Structural violations raise
    ContractError("INVALID_CANVAS_GRAPH"); cycles raise the graph compiler's
    own CYCLE_DETECTED witness.
    """
    _require(isinstance(graph, Mapping), "Canvas graph must be an object", "")
    _require(set(graph) - {"entry_node", "exit_node", "nodes", "edges"} == set(),
             "Unknown canvas graph fields", "", unexpected=sorted(set(graph) - {"entry_node", "exit_node", "nodes", "edges"}))
    entry, exit_node = graph.get("entry_node"), graph.get("exit_node")
    for field, value in (("entry_node", entry), ("exit_node", exit_node)):
        _require(type(value) is str and bool(value), f"{field} must be a nonempty node id", field)
    nodes = graph.get("nodes")
    _require(isinstance(nodes, list) and nodes, "nodes must be a nonempty list", "nodes")
    edges = graph.get("edges")
    _require(isinstance(edges, list), "edges must be a list", "edges")

    declarations, order = {}, []
    unversioned, subgraph_versions = [], []
    for index, node in enumerate(nodes):
        path = f"nodes[{index}]"
        _require(isinstance(node, Mapping), "Node must be an object", path)
        node_id = node.get("id")
        _require(type(node_id) is str and bool(node_id), "Node needs a nonempty id", f"{path}.id")
        _require(node_id not in declarations, "Duplicate canvas node id", f"{path}.id", id=node_id)
        kind = node.get("kind")
        _require(kind in _KIND_TO_NODE, "Unsupported canvas node kind",
                 f"{path}.kind", expected=sorted(_KIND_TO_NODE), actual=kind)
        ref_field = _REF_FIELD[kind]
        ref = node.get(ref_field)
        _require(type(ref) is str and bool(ref), f"{kind} node needs a nonempty {ref_field} reference",
                 f"{path}.{ref_field}")
        _require(set(node) - {"id", "kind", ref_field, f"{ref_field}_version", "timeout_ms"} == set(),
                 "Unknown canvas node fields", path, unexpected=sorted(
                     set(node) - {"id", "kind", ref_field, f"{ref_field}_version", "timeout_ms"}))
        declared = {"type": _KIND_TO_NODE[kind], ref_field: ref}
        version = node.get(f"{ref_field}_version")
        if version is not None:
            _require(type(version) is str and bool(version), f"{ref_field}_version must be a nonempty string",
                     f"{path}.{ref_field}_version")
            if kind == "OPERATOR":
                declared[ref_field] = f"{ref}@{version}"
        elif kind == "OPERATOR":
            unversioned.append(f"nodes[{index}]")
        if kind == "SUBGRAPH" and version is not None:
            subgraph_versions.append(f"nodes[{index}]")
        timeout = node.get("timeout_ms")
        if timeout is not None:
            _require(type(timeout) is int and not isinstance(timeout, bool) and timeout > 0,
                     "timeout_ms must be a positive integer", f"{path}.timeout_ms")
            declared["policy"] = {"timeout": {"attempt": f"{timeout}ms"}}
        declarations[node_id] = declared
        order.append(node_id)

    seen_edges = set()
    successors = {node_id: set() for node_id in order}
    for index, edge in enumerate(edges):
        path = f"edges[{index}]"
        _require(isinstance(edge, Mapping) and set(edge) == {"from_node", "to_node"},
                 "Edge must be exactly from_node and to_node", path)
        source, target = edge["from_node"], edge["to_node"]
        _require(source in declarations, "Edge references an undeclared node", f"{path}.from_node", id=source)
        _require(target in declarations, "Edge references an undeclared node", f"{path}.to_node", id=target)
        _require((source, target) not in seen_edges, "Duplicate edge", path)
        seen_edges.add((source, target))
        successors[source].add(target)
    graph_shape = compile_graph(order, sorted(seen_edges))

    reachable, pending = {entry}, [entry]
    while pending:
        for successor in sorted(successors[pending.pop()]):
            if successor not in reachable:
                reachable.add(successor)
                pending.append(successor)
    _require(exit_node in reachable, "Exit node is unreachable from the entry node", "exit_node", id=exit_node)
    dropped = sorted(set(order) - reachable)

    flow_nodes = {}
    for node_id in graph_shape.order:
        if node_id not in reachable:
            continue
        declared = declarations[node_id]
        predecessors = graph_shape.predecessors[node_id] & reachable
        if predecessors:
            declared = {**declared, "depends_on": sorted(predecessors)}
        flow_nodes[node_id] = declared
    flow = {"id": flow_id, "input_schema": input_schema or "", "output_schema": output_schema or "",
            "nodes": flow_nodes,
            "outputs": {"result": {"from": f"nodes.{exit_node}.output.data"}}}

    diagnostics = [_advisory("UNKNOWN_NODE", "warning", "Node is unreachable from the entry and was excluded",
                             f"nodes[{node_id}]", "Remove the node or connect it to the entry path.")
                   for node_id in dropped]
    diagnostics += [_advisory("UNKNOWN_OPERATOR", "warning",
                              "Operator reference carries no version; the registry resolves name@version",
                              path, "Add operator_version to the canvas node or pin it in the skeleton.")
                    for path in unversioned]
    diagnostics += [_advisory("UNKNOWN_FLOW", "note",
                              "Subgraph version is recorded by the control plane; "
                              "the subflow reference must resolve to a flow id in this project",
                              path, "Name the project flow to match the platform subgraph version.")
                    for path in subgraph_versions]
    for role, schema in (("input_schema", input_schema), ("output_schema", output_schema)):
        if not schema:
            diagnostics.append(_advisory(
                "UNKNOWN_SCHEMA", "warning", f"Flow declares no {role}",
                f"flow.{role}",
                "Schemas cannot be invented from a control skeleton; declare one before check."))
    diagnostics.sort(key=lambda item: (item["path"], item["error_code"]))
    return {"protocol": CANVAS_PROTOCOL, "flow": flow, "diagnostics": diagnostics}


def canvas_digest(graph) -> str:
    """Platform-side content digest of a canvas graph (canonical JSON sha-256).

    Mirrors the orchestration control plane's config hash: deterministic across
    processes, unlike Python's randomized str hash. The framing here matches
    the server contract (sort_keys + compact separators), not the framework's
    typed canonical tree used for release identities.
    """
    from .values import validate_value
    validate_value(graph)

    def tree(value):
        if isinstance(value, Mapping):
            return {key: tree(value[key]) for key in sorted(value)}
        if isinstance(value, list):
            return [tree(item) for item in value]
        return value

    canonical = json.dumps(tree(graph), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
