/// 三层状态存储（§11）：page / session / product（+persistent 预留）。
/// 与 Flutter MFStateStore 同语义：writeDeep 按点分路径落位，peek 读取。

const SCOPES = ['component', 'page', 'session', 'product', 'persistent'] as const;
export type MFStateScope = (typeof SCOPES)[number];

export class MFStateStore {
  private layers: Record<string, Record<string, unknown>> = {};

  static isScope(scope: string): scope is MFStateScope {
    return (SCOPES as readonly string[]).includes(scope);
  }

  peek(scope: MFStateScope, path: string): unknown {
    const parts = path === '' ? [] : path.split('.');
    const key = parts[0] ?? '';
    if (!key) return this.layers[scope];
    const layer = this.layers[scope];
    if (!layer) return null;
    let cur: unknown = layer[key];
    for (const p of parts.slice(1)) {
      if (cur !== null && typeof cur === 'object') {
        cur = (cur as Record<string, unknown>)[p];
      } else {
        return null;
      }
    }
    return cur ?? null;
  }

  write(scope: MFStateScope, member: string, value: unknown): void {
    const layer = (this.layers[scope] ??= {});
    layer[member] = value;
  }

  writeDeep(scope: MFStateScope, path: string, value: unknown): void {
    const parts = path.split('.').filter(Boolean);
    if (parts.length === 0) return;
    const layer = (this.layers[scope] ??= {});
    const member = parts[0]!;
    if (parts.length === 1) {
      layer[member] = value;
      return;
    }
    const existing = layer[member];
    const root: Record<string, unknown> =
      existing !== null && typeof existing === 'object' && !Array.isArray(existing)
        ? { ...(existing as Record<string, unknown>) }
        : {};
    let cur = root;
    for (const p of parts.slice(1, -1)) {
      const next = cur[p];
      cur = cur[p] =
        next !== null && typeof next === 'object' && !Array.isArray(next)
          ? { ...(next as Record<string, unknown>) }
          : {};
    }
    cur[parts.at(-1)!] = value;
    layer[member] = root;
  }

  /** 会话/产品层快照导出（§16.1 恢复快照数据源）。 */
  exportLayers(scopes: MFStateScope[]): Record<string, Record<string, unknown>> {
    const out: Record<string, Record<string, unknown>> = {};
    for (const s of scopes) {
      if (this.layers[s]) out[s] = structuredClone(this.layers[s]);
    }
    return out;
  }

  importLayers(layers: Record<string, Record<string, unknown>>): void {
    for (const [scope, layer] of Object.entries(layers)) {
      if (MFStateStore.isScope(scope)) this.layers[scope] = structuredClone(layer);
    }
  }
}
