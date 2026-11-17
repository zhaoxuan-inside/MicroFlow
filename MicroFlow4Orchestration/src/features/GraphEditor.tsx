/** 编排画布（@xyflow/react，MIT）：调色板加节点 / 连线（成环拒绝）/ 删除 /
 * 入口出口检查器 / JSON↔图双向同步 / 撤销重做 / 只读态。
 *
 * 语义与主站 Vue GraphEditor 一致：拓扑分列布局（Kahn BFS）、节点类型推断、
 * 拖拽位置写回草稿对象（_x/_y）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeChange,
  type EdgeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Badge, Button, cn } from "@microflow4kit/ui";
import { inferNodeType, type GraphEdge, type GraphNode } from "./catalog";
import { reaches, topoLayout } from "./graphLayout";

const NODE_W = 190;
const NODE_H = 86;
const COL_GAP = 70;
const ROW_GAP = 26;

export interface PaletteItem {
  kind: "OPERATOR" | "SUBGRAPH";
  key: string;
  label: string;
  domain?: string;
  description?: string;
}

export interface EditorGraph {
  entry_node: string;
  exit_node: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  enable_saga_compensation?: boolean;
}

/** 节点执行态（来自最近一次 run 的 node_traces）：键为节点 id。 */
export interface NodeExecution {
  status: string;
  duration_ms: number;
}

const typeBadgeTone: Record<string, "primary" | "warning" | "success" | "neutral"> = {
  GUARD: "warning",
  STORAGE: "success",
  CACHE: "primary",
  BIZ: "neutral",
};

const execDot: Record<string, string> = {
  SUCCESS: "bg-success",
  FAILED: "bg-destructive",
  GUARD_REJECTED: "bg-warning",
  SKIPPED: "bg-muted-foreground",
};

function nodeLabel(n: GraphNode, palette: PaletteItem[]): { title: string; sub: string } {
  const ref = n.kind === "SUBGRAPH" ? n.subgraph : n.operator;
  const item = palette.find((p) => p.key === ref);
  return {
    title: item?.label || ref || n.id,
    sub: n.kind === "SUBGRAPH" ? `子图 ${ref || "?"}` : `算子 ${ref || "?"}`,
  };
}

export function GraphEditor({
  graph,
  editable,
  allowSubgraphs,
  palette,
  execution,
  onChange,
}: {
  graph: EditorGraph;
  editable: boolean;
  allowSubgraphs: boolean;
  palette: PaletteItem[];
  /** 最近一次执行的节点态：存在时节点内嵌状态点与时长 */
  execution?: Record<string, NodeExecution>;
  onChange: (next: EditorGraph) => void;
}) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const historyRef = useRef<EditorGraph[]>([]);
  const [historyDepth, setHistoryDepth] = useState(0);
  const syncedSig = useRef("");

  const signature = useMemo(
    () =>
      JSON.stringify({
        n: graph.nodes.map((n) => [n.id, n.kind, n.operator, n.subgraph, n.type]),
        e: graph.edges,
        entry: graph.entry_node,
        exit: graph.exit_node,
      }),
    [graph],
  );

  // 图 → 画布同步（语义变化才重排，拖拽位置从节点对象 _x/_y 恢复）
  useEffect(() => {
    if (signature === syncedSig.current) return;
    syncedSig.current = signature;
    const layout = topoLayout(graph.nodes, graph.edges);
    setNodes(
      graph.nodes.map((n) => {
        const { title, sub } = nodeLabel(n, palette);
        return {
          id: n.id,
          position: {
            x: typeof n._x === "number" ? n._x : 40 + (layout.get(n.id)?.col || 0) * (NODE_W + COL_GAP),
            y: typeof n._y === "number" ? n._y : 40 + (layout.get(n.id)?.row || 0) * (NODE_H + ROW_GAP),
          },
          data: {
            label: (
              <div className="w-full px-1 text-left">
                <div className="flex items-center justify-between gap-1">
                  <span className="truncate text-xs font-semibold">{title}</span>
                  <Badge tone={typeBadgeTone[n.type] || "neutral"}>{n.type}</Badge>
                </div>
                <div className="truncate text-[10px] text-muted-foreground">{sub}</div>
                {execution?.[n.id] ? (
                  <div className="mt-1 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                    <span className={cn("size-1.5 rounded-full", execDot[execution[n.id].status] || "bg-muted-foreground")} />
                    <span className="font-mono tabular-nums">{execution[n.id].duration_ms}ms</span>
                    <span className="truncate">{execution[n.id].status}</span>
                  </div>
                ) : null}
                <div className="mt-1 flex gap-1">
                  {graph.entry_node === n.id && <Badge tone="primary">入口</Badge>}
                  {graph.exit_node === n.id && <Badge tone="success">出口</Badge>}
                </div>
              </div>
            ),
          },
          style: {
            width: NODE_W,
            height: NODE_H,
            border:
              graph.entry_node === n.id || graph.exit_node === n.id
                ? "2px solid var(--color-primary, #6366f1)"
                : execution?.[n.id]?.status === "FAILED"
                  ? "1.5px solid var(--color-destructive, #ef4444)"
                  : undefined,
            borderRadius: 8,
            background: "var(--color-card, #fff)",
            color: "var(--color-card-foreground, #111)",
          },
        } satisfies Node;
      }),
    );
    setEdges(
      graph.edges.map(
        (e) =>
          ({
            id: `${e.from_node}=>${e.to_node}`,
            source: e.from_node,
            target: e.to_node,
            animated: false,
            markerEnd: { type: MarkerType.ArrowClosed },
          }) satisfies Edge,
      ),
    );
  }, [signature, graph, palette, execution]);

  const commit = useCallback(
    (mutate: (draft: EditorGraph) => EditorGraph) => {
      if (!editable) return;
      historyRef.current = [...historyRef.current.slice(-49), JSON.parse(JSON.stringify(graph))];
      setHistoryDepth(historyRef.current.length);
      const next = mutate(JSON.parse(JSON.stringify(graph)));
      onChange(next);
    },
    [editable, graph, onChange],
  );

  const undo = useCallback(() => {
    const prev = historyRef.current.pop();
    if (!prev) return;
    setHistoryDepth(historyRef.current.length);
    onChange(prev);
  }, [onChange]);

  const uniqueId = useCallback(
    (base: string) => {
      if (!graph.nodes.some((n) => n.id === base)) return base;
      let i = 2;
      while (graph.nodes.some((n) => n.id === `${base}_${i}`)) i += 1;
      return `${base}_${i}`;
    },
    [graph.nodes],
  );

  const addNode = useCallback(
    (item: PaletteItem) =>
      commit((draft) => {
        const id = uniqueId(item.key);
        const node: GraphNode & { _x?: number; _y?: number } = {
          id,
          kind: item.kind,
          type: inferNodeType(item.key),
          timeout_ms: 3000,
        };
        if (item.kind === "SUBGRAPH") node.subgraph = item.key;
        else node.operator = item.key;
        if (!draft.entry_node) draft.entry_node = id;
        draft.exit_node = id;
        draft.nodes.push(node);
        return draft;
      }),
    [commit, uniqueId],
  );

  const onConnect = useCallback(
    (conn: Connection) =>
      commit((draft) => {
        const { source, target } = conn;
        if (!source || !target) return draft;
        if (source === target) return draft; // 自环
        if (draft.edges.some((e) => e.from_node === source && e.to_node === target)) return draft; // 重复连线
        if (reaches(target, source, draft.edges)) return draft; // 成环
        draft.edges.push({ from_node: source, to_node: target });
        return draft;
      }),
    [commit],
  );

  const onNodesDelete = useCallback(
    (deleted: Node[]) =>
      commit((draft) => {
        const removed = new Set(deleted.map((d) => d.id));
        draft.nodes = draft.nodes.filter((n) => !removed.has(n.id));
        draft.edges = draft.edges.filter((e) => !removed.has(e.from_node) && !removed.has(e.to_node));
        if (removed.has(draft.entry_node)) draft.entry_node = draft.nodes[0]?.id || "";
        if (removed.has(draft.exit_node)) draft.exit_node = draft.nodes[draft.nodes.length - 1]?.id || "";
        return draft;
      }),
    [commit],
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) =>
      commit((draft) => {
        const removed = new Set(deleted.map((d) => d.id));
        draft.edges = draft.edges.filter((e) => !removed.has(`${e.from_node}=>${e.to_node}`));
        return draft;
      }),
    [commit],
  );

  const onNodeDragStop = useCallback(
    (_: unknown, node: Node) => {
      // 拖拽仅更新呈现位置（写回草稿对象，不进历史栈）
      const target = graph.nodes.find((n) => n.id === node.id) as (GraphNode & { _x?: number; _y?: number }) | undefined;
      if (!target) return;
      target._x = Math.round(node.position.x);
      target._y = Math.round(node.position.y);
    },
    [graph.nodes],
  );

  const setEntryExit = useCallback(
    (id: string, role: "entry" | "exit") =>
      commit((draft) => {
        if (role === "entry") draft.entry_node = id;
        else draft.exit_node = id;
        return draft;
      }),
    [commit],
  );

  const removeNode = useCallback(
    (id: string) => {
      // 复用画布删除回调：按需构造仅含 id 的最小 Node 适配对象（非 Mock 数据）
      const synthetic: Node[] = [{ id, position: { x: 0, y: 0 } } as Node];
      onNodesDelete(synthetic);
    },
    [onNodesDelete],
  );

  const removeEdge = useCallback(
    (edge: GraphEdge) => {
      const synthetic: Edge[] = [{ id: `${edge.from_node}=>${edge.to_node}`, source: edge.from_node, target: edge.to_node } as Edge];
      onEdgesDelete(synthetic);
    },
    [onEdgesDelete],
  );

  const selected = graph.nodes.find((n) => n.id === selectedId);
  const filteredPalette = palette.filter((p) => allowSubgraphs || p.kind === "OPERATOR");

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_260px]">
      <div
        className={cn(
          "h-[480px] overflow-hidden rounded-md border border-border",
          !editable && "opacity-95",
        )}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={(_changes: NodeChange[]) => {
            /* 位置变化在 dragStop 统一写回；选择变化走 onSelectionChange */
          }}
          onEdgesChange={(_changes: EdgeChange[]) => {}}
          onConnect={onConnect}
          onNodeDragStop={onNodeDragStop}
          onNodesDelete={onNodesDelete}
          onEdgesDelete={onEdgesDelete}
          onNodeClick={(_, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId("")}
          nodesDraggable={editable}
          nodesConnectable={editable}
          elementsSelectable={editable}
          deleteKeyCode={editable ? "Delete" : null}
          fitView
          minZoom={0.3}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable className="!bg-card" />
        </ReactFlow>
      </div>

      <div className="flex max-h-[480px] flex-col gap-3 overflow-y-auto rounded-md border border-border p-3">
        {editable && (
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">节点调色板</span>
            <div className="flex gap-1">
              <Button variant="secondary" className="h-6 px-2 text-[11px]" disabled={!historyDepth} onClick={undo}>
                撤销
              </Button>
            </div>
          </div>
        )}
        {editable &&
          filteredPalette.map((item) => (
            <button
              key={`${item.kind}:${item.key}`}
              type="button"
              className="rounded-md border border-border px-2.5 py-2 text-left transition-colors hover:bg-accent"
              onClick={() => addNode(item)}
            >
              <div className="flex items-center gap-1.5">
                <Badge tone={item.kind === "SUBGRAPH" ? "primary" : "neutral"}>
                  {item.kind === "SUBGRAPH" ? "子图" : "算子"}
                </Badge>
                <span className="truncate text-xs font-medium">{item.label}</span>
              </div>
              {item.description && (
                <div className="truncate text-[10px] text-muted-foreground">{item.description}</div>
              )}
            </button>
          ))}

        {editable && selected ? (
          <div className="space-y-2 rounded-md border border-border bg-muted/30 p-2.5">
            <div className="text-xs font-medium">检查器 · {selected.id}</div>
            <div className="flex flex-wrap gap-1.5">
              <Button
                variant={graph.entry_node === selected.id ? "primary" : "secondary"}
                className="h-6 px-2 text-[11px]"
                onClick={() => setEntryExit(selected.id, "entry")}
              >
                设为入口
              </Button>
              <Button
                variant={graph.exit_node === selected.id ? "primary" : "secondary"}
                className="h-6 px-2 text-[11px]"
                onClick={() => setEntryExit(selected.id, "exit")}
              >
                设为出口
              </Button>
              <Button variant="destructive" className="h-6 px-2 text-[11px]" onClick={() => removeNode(selected.id)}>
                移除节点
              </Button>
            </div>
            <div className="text-[11px] text-muted-foreground">
              当前入口 {graph.entry_node || "—"} · 出口 {graph.exit_node || "—"}
            </div>
          </div>
        ) : null}

        {graph.edges.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground">连线（{graph.edges.length}）</div>
            {graph.edges.map((e) => (
              <div key={`${e.from_node}=>${e.to_node}`} className="flex items-center justify-between gap-1 text-[11px]">
                <span className="truncate">
                  {e.from_node} → {e.to_node}
                </span>
                {editable && (
                  <Button variant="ghost" className="h-5 px-1 text-[11px] text-destructive" onClick={() => removeEdge(e)}>
                    ×
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
        {editable && (
          <div className="text-[10px] leading-relaxed text-muted-foreground">
            点调色板加节点 · 拖拽节点手柄连线 · Delete 删除选中 · 成环连线会被拒绝
          </div>
        )}
      </div>
    </div>
  );
}
