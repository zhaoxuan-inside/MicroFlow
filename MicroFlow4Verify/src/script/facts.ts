/// 从 MFProject JSON 提取脚本静态门禁所需的最小事实面（页/节点/契约事件）。
/// 结构化局部类型：不 import 渲染器实现——事实提取对渲染面中立。

export interface ProjectFacts {
  pageIds: ReadonlySet<string>;
  entryPage?: string;
  /** 节点 id → 组件类型（全部页面树并集）。 */
  nodeTypeById: ReadonlyMap<string, string>;
  /** 组件类型 → 契约声明事件集（registry）；未注册类型不在表中。 */
  eventsByType: ReadonlyMap<string, ReadonlySet<string>>;
}

interface FactNode {
  id?: unknown;
  type?: unknown;
  children?: unknown;
}

interface FactPage {
  id?: unknown;
  tree?: unknown;
}

interface FactRegistryEntry {
  id?: unknown;
  contract?: { events?: unknown };
}

function walkTree(node: unknown, into: Map<string, string>): void {
  if (typeof node !== 'object' || node === null) return;
  const record = node as FactNode;
  if (typeof record.id === 'string' && typeof record.type === 'string') {
    into.set(record.id, record.type);
  }
  if (Array.isArray(record.children)) {
    for (const child of record.children) walkTree(child, into);
  }
}

/** 非 JSON 对象 / 缺 pages 时返回 undefined——调用方按模型损坏处理。 */
export function extractFacts(project: unknown): ProjectFacts | undefined {
  if (typeof project !== 'object' || project === null || Array.isArray(project)) return undefined;
  const record = project as Record<string, unknown>;
  if (!Array.isArray(record['pages'])) return undefined;

  const pageIds = new Set<string>();
  const nodeTypeById = new Map<string, string>();
  for (const page of record['pages'] as FactPage[]) {
    if (typeof page?.id === 'string') pageIds.add(page.id);
    walkTree(page?.tree, nodeTypeById);
  }

  const eventsByType = new Map<string, ReadonlySet<string>>();
  if (Array.isArray(record['registry'])) {
    for (const entry of record['registry'] as FactRegistryEntry[]) {
      if (typeof entry?.id !== 'string') continue;
      const events = entry.contract?.events;
      if (typeof events === 'object' && events !== null && !Array.isArray(events)) {
        eventsByType.set(entry.id, new Set(Object.keys(events)));
      }
    }
  }

  const manifest = record['manifest'];
  const entryPage =
    typeof manifest === 'object' && manifest !== null && typeof (manifest as Record<string, unknown>)['entry_page'] === 'string'
      ? ((manifest as Record<string, unknown>)['entry_page'] as string)
      : undefined;

  return { pageIds, entryPage, nodeTypeById, eventsByType };
}
