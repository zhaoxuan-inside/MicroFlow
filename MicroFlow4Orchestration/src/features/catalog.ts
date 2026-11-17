/** 编排目录契约：资产类型与共享纯工具（无网络依赖；网络统一走 orchClient）。
 *
 * 节点/边/图结构由 GraphEditor 与 graphLayout 消费；工具函数供测试直接覆盖。
 */
export type AssetKind = "operator" | "subgraph" | "scenario";

export interface AssetVersion {
  version: string;
  status: "DRAFT" | "PUBLISHED" | "SUPERSEDED";
  changelog?: string;
  created_by?: string;
  created_at?: string;
  published_by?: string;
  published_at?: string;
  definition?: { code?: string; entry_function?: string };
  graph?: {
    entry_node: string;
    exit_node: string;
    nodes: GraphNode[];
    edges: GraphEdge[];
    enable_saga_compensation?: boolean;
  };
  compiled?: unknown;
}

export interface GraphNode {
  id: string;
  _x?: number; // 画布拖拽位置缓存（仅前端呈现，不参与后端校验）
  _y?: number;
  kind?: "OPERATOR" | "SUBGRAPH";
  operator?: string;
  operator_version?: string;
  subgraph?: string;
  subgraph_version?: string;
  type: string; // GUARD | BIZ | STORAGE | CACHE
  timeout_ms?: number;
}

export interface GraphEdge {
  from_node: string;
  to_node: string;
}

export interface CatalogAsset {
  name?: string; // operator
  code?: string; // subgraph / scenario
  display_name?: string;
  description?: string;
  domain?: string;
  source?: "builtin" | "custom" | "managed" | "runtime";
  current_version?: string;
  versions?: AssetVersion[];
  created_by?: string;
  project_id?: string;
  runtime_status?: string;
  referenced_by?: string[];
  in_use?: boolean;
}

export function assetId(asset: CatalogAsset): string {
  return asset.name || asset.code || "";
}

export function assetKindLabel(kind: AssetKind): string {
  return kind === "operator" ? "算子" : kind === "subgraph" ? "子图" : "场景";
}

export function assetIdField(kind: AssetKind): "name" | "code" {
  return kind === "operator" ? "name" : "code";
}

export const versionTone: Record<string, "neutral" | "success" | "warning" | "primary"> = {
  DRAFT: "warning",
  PUBLISHED: "success",
  SUPERSEDED: "neutral",
};

/** 节点类型推断（与主站 GraphEditor inferNodeType 语义一致）。 */
export function inferNodeType(handlerKey: string): string {
  if (/guard|validate|check/.test(handlerKey)) return "GUARD";
  if (/persist|save|store/.test(handlerKey)) return "STORAGE";
  if (/cache/.test(handlerKey)) return "CACHE";
  return "BIZ";
}
