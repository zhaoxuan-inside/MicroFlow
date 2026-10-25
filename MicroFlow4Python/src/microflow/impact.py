"""Static impact reverse index derived from a compiled release.

The index answers "what statically references this operator or flow": operator
references per node, child-flow references (subflow/map/loop) and the upstream
flow closure. It is a build-time projection only; runtime usage, invocation
counts and collected metrics stay in the observability layer (platform §14.4).
An operator absent from the index means "not referenced by this release",
which is a first-class state, not an error.
"""
from dataclasses import dataclass
from collections.abc import Mapping
from types import MappingProxyType

from .compiler import CompiledRelease
from .errors import ContractError
from .graph import compile_graph

PROTOCOL = "microflow-impact-index-v1"


@dataclass(frozen=True)
class Reference:
    """One node-level reference: flow_id declares node kind referencing a target."""

    flow: str
    node: str
    kind: str


@dataclass(frozen=True)
class ImpactIndex:
    protocol: str
    release_id: str
    flows: tuple
    roots: tuple
    registered_operators: tuple
    operators: Mapping
    subflows: Mapping


def build_index(release: CompiledRelease) -> ImpactIndex:
    """Derive the deterministic reference index; revalidates the flow reference graph."""
    if not isinstance(release, CompiledRelease):
        raise ContractError("INVALID_RELEASE", "Expected a compiled release")
    flow_ids = sorted(release.flows)
    registered = sorted(release.registry.operators)
    operators = {}
    subflows = {}
    edges = []
    for flow_id in flow_ids:
        plan = release.flows[flow_id]
        nodes = plan.definition.get("nodes", {})
        if not isinstance(nodes, Mapping):
            raise ContractError("IMPACT_STRUCTURE", "Flow nodes must be an object", flow_id)
        for node_id in sorted(nodes):
            node = nodes[node_id]
            if not isinstance(node, Mapping):
                raise ContractError("IMPACT_STRUCTURE", "Node must be an object",
                                    f"{flow_id}.{node_id}")
            kind = node.get("type", "operator")
            if kind == "operator":
                ref = node.get("operator")
                if type(ref) is not str or ref not in release.registry.operators:
                    raise ContractError("IMPACT_STRUCTURE", "Node references an unknown operator",
                                        f"{flow_id}.{node_id}", operator=ref)
                operators.setdefault(ref, []).append(Reference(flow_id, node_id, "operator"))
            elif kind in ("subflow", "map", "loop"):
                child = node.get("flow")
                if type(child) is not str or child not in release.flows:
                    raise ContractError("IMPACT_STRUCTURE", "Node references an unknown child flow",
                                        f"{flow_id}.{node_id}", flow=child)
                subflows.setdefault(child, []).append(Reference(flow_id, node_id, kind))
                edges.append((flow_id, child))
    # The release already rejected cycles; revalidate so the index itself carries
    # the acyclicity invariant its traversals rely on.
    compile_graph(flow_ids, edges)
    roots = tuple(flow_id for flow_id in flow_ids if flow_id not in subflows)
    return ImpactIndex(PROTOCOL, release.release_id, tuple(flow_ids), roots, tuple(registered),
                       MappingProxyType({ref: tuple(refs) for ref, refs in sorted(operators.items())}),
                       MappingProxyType({child: tuple(refs) for child, refs in sorted(subflows.items())}))


def _embeddings(index) -> dict:
    return {child: tuple(sorted({r.flow for r in refs})) for child, refs in index.subflows.items()}


def operator_references(index: ImpactIndex, ref: str) -> tuple:
    """Node-level references of one registered operator; empty when unused by this release."""
    if type(ref) is not str or ref not in index.registered_operators:
        raise ContractError("UNKNOWN_OPERATOR", "Operator is not registered in this release", ref)
    return index.operators.get(ref, ())


def operator_flows(index: ImpactIndex, ref: str) -> tuple:
    """Distinct flows that reference the operator, in stable order."""
    return tuple(sorted({r.flow for r in operator_references(index, ref)}))


def flow_references(index: ImpactIndex, flow_id: str) -> tuple:
    """Direct references embedding the flow as a subflow, map or loop node."""
    if type(flow_id) is not str or flow_id not in index.flows:
        raise ContractError("UNKNOWN_FLOW", "Unknown flow", flow_id)
    return index.subflows.get(flow_id, ())


def upstream_flows(index: ImpactIndex, flow_id: str) -> tuple:
    """Transitive closure of flows that embed the flow, directly or via subflows."""
    if type(flow_id) is not str or flow_id not in index.flows:
        raise ContractError("UNKNOWN_FLOW", "Unknown flow", flow_id)
    embeddings = _embeddings(index)
    visited = {flow_id}
    pending = [flow_id]
    result = []
    while pending:
        current = pending.pop()
        for parent in embeddings.get(current, ()):
            if parent not in visited:
                visited.add(parent)
                result.append(parent)
                pending.append(parent)
    return tuple(sorted(result))


def describe_references(references) -> list:
    return [{"flow": r.flow, "node": r.node, "kind": r.kind} for r in references]


def describe_index(index: ImpactIndex) -> dict:
    """Independent JSON projection; callers may mutate the result freely."""
    return {
        "protocol": index.protocol,
        "release_id": index.release_id,
        "flows": list(index.flows),
        "roots": list(index.roots),
        "registered_operators": list(index.registered_operators),
        "operators": {ref: describe_references(refs) for ref, refs in index.operators.items()},
        "subflows": {child: describe_references(refs) for child, refs in index.subflows.items()},
    }
