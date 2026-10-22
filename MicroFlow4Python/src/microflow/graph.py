"""Stable Kahn ordering and nonrecursive cycle witnesses, including deep graphs."""
import heapq
from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType
from .errors import ContractError
from .values import freeze, thaw


@dataclass(frozen=True)
class Graph:
    order: tuple[str, ...]
    predecessors: Mapping[str, frozenset[str]]
    successors: Mapping[str, frozenset[str]]
    edge_sources: Mapping = field(default_factory=lambda: MappingProxyType({}))


def compile_graph(nodes, edges, *, edge_sources=None) -> Graph:
    nodes = list(nodes)
    if any(type(n) is not str or not n for n in nodes):
        raise ContractError("INVALID_NODE", "Graph identifiers must be nonempty strings")
    names = set(nodes)
    if len(names) != len(nodes):
        raise ContractError("DUPLICATE_NODE", "Graph node identifiers must be unique")
    predecessors = {n: set() for n in names}
    successors = {n: set() for n in names}
    sources = edge_sources or {}
    def witnesses(cycle):
        return [{"from": u, "to": v, "source_locations": thaw(sources.get((u, v), ()))}
                for u, v in zip(cycle, cycle[1:])]

    for u, v in edges:
        if u not in names or v not in names:
            raise ContractError("UNKNOWN_NODE", "Dependency references undeclared node", f"{u}->{v}",
                                edges=witnesses([u, v]))
        if u == v:
            raise ContractError("CYCLE_DETECTED", "Self cycle", u, cycle=[u, u], edges=witnesses([u, u]))
        predecessors[v].add(u)
        successors[u].add(v)
    indegree = {n: len(p) for n, p in predecessors.items()}
    ready = [n for n in names if not indegree[n]]
    heapq.heapify(ready)
    order = []
    while ready:
        u = heapq.heappop(ready)
        order.append(u)
        for v in successors[u]:
            indegree[v] -= 1
            if not indegree[v]:
                heapq.heappush(ready, v)
    if len(order) != len(names):
        remaining = names - set(order)
        color = {}
        for root in sorted(remaining):
            if color.get(root):
                continue
            path = [root]
            positions = {root: 0}
            color[root] = 1
            stack = [(root, iter(sorted(successors[root] & remaining)))]
            while stack:
                u, children = stack[-1]
                v = next(children, None)
                if v is None:
                    stack.pop()
                    path.pop()
                    positions.pop(u)
                    color[u] = 2
                elif color.get(v) == 1:
                    cycle = path[positions[v]:] + [v]
                    raise ContractError("CYCLE_DETECTED", "Directed cycle", "->".join(cycle),
                                        cycle=cycle, edges=witnesses(cycle))
                elif not color.get(v):
                    color[v] = 1
                    positions[v] = len(path)
                    path.append(v)
                    stack.append((v, iter(sorted(successors[v] & remaining))))
    return Graph(tuple(order), MappingProxyType({n: frozenset(p) for n, p in predecessors.items()}),
                 MappingProxyType({n: frozenset(s) for n, s in successors.items()}),
                 MappingProxyType({(u, v): freeze(sources.get((u, v), ()))
                                   for u in sorted(successors) for v in sorted(successors[u])}))


def critical_path(graph: Graph, weights: dict[str, float]):
    distances = {}
    for node in graph.order:
        distances[node] = weights.get(node, 0) + max((distances[p] for p in graph.predecessors[node]), default=0)
    return distances
