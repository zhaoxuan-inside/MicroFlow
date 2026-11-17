/** 编排画布纯图算法：拓扑分列布局与可达性检测（供 GraphEditor 与测试复用）。
 *
 * 从 GraphEditor.tsx 原样抽出的纯函数模块——无 React、无副作用，
 * 语义与主站 Vue GraphEditor 一致（Kahn BFS 分列、DFS 成环拒绝）。
 */
import type { GraphEdge, GraphNode } from "./catalog";

/** 拓扑分列布局（Kahn 入度 BFS），返回 nodeId → (col,row)。 */
export function topoLayout(nodes: GraphNode[], edges: GraphEdge[]): Map<string, { col: number; row: number }> {
  const ids = nodes.map((n) => n.id);
  const adjacency = new Map<string, string[]>(ids.map((id) => [id, []]));
  const indegree = new Map<string, number>(ids.map((id) => [id, 0]));
  for (const e of edges) {
    if (!adjacency.has(e.from_node) || !indegree.has(e.to_node)) continue;
    adjacency.get(e.from_node)!.push(e.to_node);
    indegree.set(e.to_node, (indegree.get(e.to_node) || 0) + 1);
  }
  let frontier = ids.filter((id) => (indegree.get(id) || 0) === 0);
  const colOf = new Map<string, number>();
  let col = 0;
  const visited = new Set<string>();
  while (frontier.length) {
    const next: string[] = [];
    for (const id of frontier) {
      if (visited.has(id)) continue;
      visited.add(id);
      colOf.set(id, col);
      for (const nxt of adjacency.get(id) || []) next.push(nxt);
    }
    frontier = next;
    col += 1;
  }
  // 成环/不可达节点兜底排到末列，保证全部可见
  for (const id of ids) if (!colOf.has(id)) colOf.set(id, col);
  const rows = new Map<number, number>();
  const result = new Map<string, { col: number; row: number }>();
  for (const id of ids) {
    const c = colOf.get(id) || 0;
    const r = rows.get(c) || 0;
    rows.set(c, r + 1);
    result.set(id, { col: c, row: r });
  }
  return result;
}

/** DFS：from 是否可达 to（用于成环拒绝）。 */
export function reaches(from: string, to: string, edgesList: GraphEdge[]): boolean {
  const adjacency = new Map<string, string[]>();
  for (const e of edgesList) {
    if (!adjacency.has(e.from_node)) adjacency.set(e.from_node, []);
    adjacency.get(e.from_node)!.push(e.to_node);
  }
  const stack = [from];
  const seen = new Set<string>();
  while (stack.length) {
    const cur = stack.pop()!;
    if (cur === to) return true;
    if (seen.has(cur)) continue;
    seen.add(cur);
    for (const nxt of adjacency.get(cur) || []) stack.push(nxt);
  }
  return false;
}
