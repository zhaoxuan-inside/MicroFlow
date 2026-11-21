/// 静态校验门禁（§2.7）：一切修改（含纯配置创建）过同一 validate()。
/// 诊断码与 Flutter 实现同名同语义（§41）。

import type { MFProjectJson, MFNodeJson, MFActionJson, MFTypeSpec, ComponentContractJson } from '../model/types.ts';
import { mfDiag, MFCodes, type MFDiag } from '../diagnostics.ts';
import { MFStyleResolver, isRef } from '../model/loader.ts';

const SUPPORTED_DIALECTS = ['1.0'];
const TIER_A = new Set([
  'Text', 'Icon', 'Image', 'Button', 'Input', 'Select', 'Checkbox',
  'Stack', 'Scroll', 'Overlay', 'List', 'Modal',
]);
const TIER_B = new Set(['Grid', 'Split', 'Anchor', 'Tabs', 'Drawer', 'Table']);

export interface MFValidationResult {
  ok: boolean;
  diags: MFDiag[];
}

export interface MFValidatorOptions {
  /** 注册面（原语/适配器/函数契约）；缺省用项目内嵌 registry。 */
  registryEntries?: { id: string; kind: string; contract: ComponentContractJson }[];
}

export class MFValidator {
  private readonly diags: MFDiag[] = [];
  private readonly project: MFProjectJson;
  private readonly resolver: MFStyleResolver;
  private readonly registryIds = new Map<string, { kind: string; contract: ComponentContractJson }>();
  private readonly referencedTokens = new Set<string>();

  constructor(project: MFProjectJson, opts: MFValidatorOptions = {}) {
    this.project = project;
    this.resolver = new MFStyleResolver(
      project.tokens ?? {},
      project.styleSheets ?? {},
      project.themes ?? {},
      project.manifest.default_theme,
    );
    for (const e of opts.registryEntries ?? project.registry ?? []) {
      this.registryIds.set(e.id, { kind: e.kind, contract: e.contract });
    }
    // Tier A/B 内建缺省契约：不覆盖项目/注册面已声明的条目。
    for (const t of TIER_A) if (!this.registryIds.has(t)) this.registryIds.set(t, { kind: 'primitive', contract: {} });
    for (const t of TIER_B) if (!this.registryIds.has(t)) this.registryIds.set(t, { kind: 'primitive', contract: {} });
    for (const [id, c] of Object.entries(project.components ?? {})) {
      this.registryIds.set(id, { kind: 'component', contract: c.contract });
    }
  }

  validate(): MFValidationResult {
    this.validateManifest();
    this.validateRoutesAndNav();
    for (const p of this.project.pages ?? []) {
      this.validateTree(p.tree);
      this.validatePageAnchors(p.id, p.onEnter, p.onLeave);
      this.validateStateMembers(p);
      this.collectStyleTokenRefs(p.tree, p.pageOverrides);
    }
    
    this.validateBindingMaps();
    this.validateMotionTokens();
    this.validateStyleSheets();
    this.diags.push(...this.resolver.completenessDiagnostics(this.referencedTokens));
    return { ok: this.diags.every((d) => d.severity !== 'error'), diags: this.diags };
  }

  private validateManifest(): void {
    const dialect = this.project.manifest.type_dialect_version ?? '1.0';
    if (!SUPPORTED_DIALECTS.includes(dialect)) {
      this.push(MFCodes.schemaDialectUnsupported, `manifest 类型方言版本不受支持：${dialect}（§4.6、基线 14）`);
    }
  }

  private validateRoutesAndNav(): void {
    const pages = this.project.pages ?? [];
    const ids = new Set<string>();
    const routes = new Set<string>();
    for (const p of pages) {
      if (ids.has(p.id)) this.push(MFCodes.routeDuplicate, `页面 id 重复：${p.id}（§9）`);
      if (routes.has(p.route)) this.push(MFCodes.routeDuplicate, `路由重复：${p.route}（§9）`);
      ids.add(p.id);
      routes.add(p.route);
    }
    const navTargets = new Set<string>();
    for (const e of this.project.navigation?.edges ?? []) {
      if (!ids.has(e.to)) this.push(MFCodes.navUnknownTarget, `导航目标 ${e.to} 在导航图中不存在`);
      if (!ids.has(e.from)) this.push(MFCodes.navUnknownTarget, `导航来源 ${e.from} 不存在`);
      navTargets.add(e.to);
    }
    const entry = this.project.manifest.entry_page;
    if (entry) {
      if (!ids.has(entry)) this.push(MFCodes.navUnknownTarget, `入口页 ${entry} 不存在`);
      const reachable = this.reachableFrom(entry);
      for (const id of ids) {
        if (id !== entry && !reachable.has(id)) {
          this.push(MFCodes.navIsolatedPage, `存在不可达的孤立页面：${id}`);
        }
      }
    }
    // fallback 目标存在性。
    for (const target of Object.values(this.project.navigation?.fallback ?? {})) {
      if (!ids.has(target)) this.push(MFCodes.navUnknownTarget, `fallback 目标 ${target} 不存在`);
    }
  }

  private reachableFrom(entry: string): Set<string> {
    const adj = new Map<string, string[]>();
    for (const e of this.project.navigation?.edges ?? []) {
      (adj.get(e.from) ?? adj.set(e.from, []).get(e.from)!).push(e.to);
    }
    const seen = new Set<string>([entry]);
    const queue = [entry];
    while (queue.length) {
      const cur = queue.shift()!;
      for (const next of adj.get(cur) ?? []) {
        if (!seen.has(next)) {
          seen.add(next);
          queue.push(next);
        }
      }
    }
    return seen;
  }

  private registeredIds(): Set<string> {
    return new Set(this.registryIds.keys());
  }

  private validateTree(node: MFNodeJson): void {
    const known = this.registeredIds();
    if (!known.has(node.type)) {
      this.push(MFCodes.regUnregisteredRef, `节点 ${node.id} 引用了未注册资源：${node.type}（§2.7）`);
    }
    for (const child of node.children ?? []) this.validateTree(child);
    for (const list of Object.values(node.slots ?? {})) {
      for (const child of list) this.validateTree(child);
    }
  }

  /** 生命周期锚（onEnter/onLeave）必须指向存在的绑定。 */
  private validatePageAnchors(pageId: string, onEnter?: string, onLeave?: string): void {
    const bindingIds = new Set<string>();
    for (const map of Object.values(this.project.bindingMaps ?? {})) {
      for (const b of map.bindings ?? []) bindingIds.add(b.id);
    }
    for (const [label, anchor] of [['onEnter', onEnter], ['onLeave', onLeave]] as const) {
      if (anchor && !bindingIds.has(anchor)) {
        this.push(MFCodes.refDangling, `页面 ${pageId} 的 ${label} 锚 ${anchor} 未指向任何绑定`);
      }
    }
  }

  /** 页面状态成员存在性：state.* 引用必须落在声明成员/会话/产品层（§37.2）。
   *  仅检查锚定到本页的绑定（页面树内节点锚 + 页面生命周期锚）。 */
  private validateStateMembers(p: { id: string; stateMembers?: string[]; tree: MFNodeJson }): void {
    const members = new Set(p.stateMembers ?? []);
    const anchors = new Set<string>([`${p.id}.onEnter`, `${p.id}.onLeave`]);
    for (const n of flatten(p.tree)) anchors.add(n.id);
    for (const map of Object.values(this.project.bindingMaps ?? {})) {
      for (const b of map.bindings ?? []) {
        const anchorId = b.on.split('.')[0] ?? '';
        if (!anchors.has(anchorId)) continue;
        for (const action of b.actions ?? []) {
          for (const path of exprRefPaths(action.kind === 'state' ? action.value : null)) {
            if (path.startsWith('state.')) {
              const member = path.slice('state.'.length).split('.')[0] ?? '';
              if (member && !members.has(member)) {
                this.push(MFCodes.interactionUnknownMember,
                  `绑定 ${b.id} 的 state.${member} 未在页面 ${p.id} 声明（§37.2）`);
              }
            }
          }
          // state 动作目标本身也要存在（page 作用域）。
          if (action.kind === 'state' && (action.scope ?? 'page') === 'page') {
            const target = action.target ?? action.state;
            if (target && !members.has(target.split('.')[0] ?? '')) {
              this.push(MFCodes.interactionUnknownMember,
                `绑定 ${b.id} 写入 state.${target.split('.')[0]} 未在页面 ${p.id} 声明（§37.2）`);
            }
          }
        }
      }
    }
  }

  /** 绑定图：事件锚存在 + 契约声明事件 + 动作调用已注册 + prev.<as> 引用闭合。 */
  private validateBindingMaps(): void {
    const known = this.registeredIds();
    // 事件锚 -> 该锚点所属页面树（页面树里找 node id）。
    const nodeOwner = new Map<string, string>();
    for (const p of this.project.pages ?? []) {
      for (const n of flatten(p.tree)) nodeOwner.set(n.id, p.id);
      for (const c of Object.values(this.project.components ?? {})) {
        // 组件树内节点不属于页面（组件实例 id 不同），跳过。
        void c;
      }
    }
    const pageIds = new Set((this.project.pages ?? []).map((p) => p.id));
    for (const [mapId, map] of Object.entries(this.project.bindingMaps ?? {})) {
      for (const b of map.bindings ?? []) {
        const dot = b.on.indexOf('.');
        const anchorId = dot > 0 ? b.on.slice(0, dot) : b.on;
        const event = dot > 0 ? b.on.slice(dot + 1) : '';
        // 页面生命周期锚（§8）："<pageId>.onEnter/onLeave" 合法，跳过节点检查。
        if (pageIds.has(anchorId) && (event === 'onEnter' || event === 'onLeave')) {
          this.checkActionCalls(b, mapId);
          continue;
        }
        const pageId = nodeOwner.get(anchorId);
        if (!pageId) {
          this.push(MFCodes.bindingEventUnknown, `绑定 ${b.id}（map ${mapId}）的锚 ${anchorId} 不在任何页面树中`);
          continue;
        }
        // 锚点契约必须声明事件（组件实例展开略——宿主原语契约以注册表为准）。
        const node = findNode(this.project.pages.find((p) => p.id === pageId)!.tree, anchorId);
        if (node) {
          const contract = this.registryIds.get(node.type)?.contract;
          const events = contract?.events ?? {};
          if (event && !(event in events)) {
            this.push(MFCodes.bindingEventUnknown,
              `绑定 ${b.id} 的事件 ${event} 未在 ${node.type} 契约声明（§39）`);
          }
        }
        this.checkActionCalls(b, mapId);
      }
    }
  }

  /** 动作调用注册检查 + prev.<as> 引用闭合（§39.2）+ 并发策略声明提醒。 */
  private checkActionCalls(
    b: { id: string; actions?: MFActionJson[]; concurrency?: string },
    mapId: string,
  ): void {
    const known = this.registeredIds();
    const produced = new Set<string>();
    for (const action of b.actions ?? []) {
      if (action.kind === 'function' || action.kind === 'adapter' || action.kind === 'host') {
        if (!known.has(action.call)) {
          this.push(MFCodes.regUnregisteredRef, `绑定 ${b.id}（map ${mapId}）调用了未注册资源：${action.call}`);
        }
        if (action.as) produced.add(action.as);
      }
      for (const path of exprRefPaths(action.kind === 'state' ? action.value : action)) {
        if (path.startsWith('prev.')) {
          const as = path.slice('prev.'.length).split('.')[0] ?? '';
          if (as && !produced.has(as)) {
            this.push(MFCodes.bindingResultUnknown, `绑定 ${b.id} 引用了不存在的动作结果 prev.${as}`);
          }
        }
      }
    }
    if (!b.concurrency) {
      this.diags.push(mfDiag(MFCodes.bindingNoConcurrency,
        `绑定 ${b.id} 未声明并发策略，将拒绝重复触发（§39.1）`, 'warning'));
    }
  }

  /** motion token 形状 + 替代组悬空（§36.5/§36.7）。 */
  private validateMotionTokens(): void {
    for (const set of Object.values(this.project.tokens ?? {})) {
      for (const [name, value] of Object.entries(set.tokens ?? {})) {
        if (!name.startsWith('motion.')) continue;
        if (name.endsWith('.reduced')) {
          const base = name.slice(0, -'.reduced'.length);
          if (!(base in set.tokens)) {
            this.push(MFCodes.motionAlternativeDangling, `替代组 ${name} 缺少同名基础 token ${base}（§36.7）`);
          }
        }
        const spec = asMotionSpec(value);
        if (!spec) {
          this.push(MFCodes.motionTokenInvalid, `motion token ${name} 值形状不符（§36.5：duration 0..10000 + curve 四点）`);
        }
      }
    }
  }

  /** 样式片：字面量禁用 / extends 悬空与循环 / 变体歧义（§36.4、§36.8）。 */
  private validateStyleSheets(): void {
    const sheets = Object.values(this.project.styleSheets ?? {});
    const ids = new Set(sheets.map((s) => s.id));
    for (const sheet of sheets) {
      for (const [aspect, token] of Object.entries(sheet.base ?? {})) {
        this.collectTokenRef(token);
        if (!token.includes('.')) {
          this.push(MFCodes.styleLiteralInSheet, `样式片 ${sheet.id} 的 ${aspect} 使用字面量而非 token 引用（§36.4）`);
        }
      }
      const unsorted = (sheet.variants ?? []).filter((v) => !v.order);
      if (unsorted.length > 1 && new Set(unsorted.map((v) => JSON.stringify(v.when))).size === 1) {
        this.push(MFCodes.styleVariantAmbiguous, `样式片 ${sheet.id} 同一选择器命中多个 set 且顺序未声明`);
      }
      let cur = sheet;
      let hops = 0;
      while (cur.extends && hops++ < 16) {
        const parent = sheets.find((s) => s.id === cur.extends);
        if (!parent) {
          this.push(MFCodes.refDangling, `样式片 ${sheet.id} 承接链悬空：${cur.extends}`);
          break;
        }
        if (parent.id === sheet.id) {
          this.push(MFCodes.styleCycle, `样式片承接链循环：${sheet.id}`);
          break;
        }
        cur = parent;
      }
    }
  }

  private collectStyleTokenRefs(node: MFNodeJson, pageOverrides?: Record<string, string>): void {
    for (const v of Object.values(pageOverrides ?? {})) this.collectTokenRef(v);
    if (node.style) {
      const sheet = this.project.styleSheets?.[node.style];
      if (sheet) {
        for (const token of Object.values(sheet.base ?? {})) this.collectTokenRef(token);
        for (const variant of sheet.variants ?? []) {
          for (const token of Object.values(variant.set)) this.collectTokenRef(token);
        }
      }
    }
    // 节点 props 中的 token 引用（如 {'token': 'color.x'} 形状由原语消费）。
    collectPropTokenRefs(node.props ?? {}, this.referencedTokens);
    for (const child of node.children ?? []) this.collectStyleTokenRefs(child);
    for (const list of Object.values(node.slots ?? {})) {
      for (const child of list) this.collectStyleTokenRefs(child);
    }
  }

  private collectTokenRef(token: string): void {
    if (token.includes('.')) this.referencedTokens.add(token);
  }

  private push(code: string, message: string): void {
    this.diags.push(mfDiag(code, message));
  }
}

/** 模型组合组件树校验 + 引用 token 收集。 */
function collectPropTokenRefs(props: Record<string, unknown>, into: Set<string>): void {
  for (const v of Object.values(props)) {
    if (isRef(v)) continue;
    if (typeof v === 'object' && v !== null) {
      collectPropTokenRefs(v as Record<string, unknown>, into);
    }
  }
}

export function flatten(node: MFNodeJson): MFNodeJson[] {
  return [
    node,
    ...(node.children ?? []).flatMap(flatten),
    ...Object.values(node.slots ?? {}).flatMap((list) => list.flatMap(flatten)),
  ];
}

function findNode(root: MFNodeJson, id: string): MFNodeJson | null {
  return flatten(root).find((n) => n.id === id) ?? null;
}

/** 表达式形状的 ref 路径收集（递归字面量骨架）。 */
export function exprRefPaths(value: unknown): string[] {
  const out: string[] = [];
  const walk = (v: unknown): void => {
    if (v === null || typeof v !== 'object') return;
    if (Array.isArray(v)) {
      v.forEach(walk);
      return;
    }
    const rec = v as Record<string, unknown>;
    if (typeof rec.ref === 'string') {
      out.push(rec.ref);
      return;
    }
    for (const val of Object.values(rec)) walk(val);
  };
  walk(value);
  return out;
}

/** motion token 形状检查（§36.5：duration 0..10000 num + curve 四点 list）。 */
export function asMotionSpec(value: unknown): { duration: number; curve: number[] } | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null;
  const rec = value as Record<string, unknown>;
  const duration = rec.duration;
  const curve = rec.curve;
  if (typeof duration !== 'number' || !Number.isFinite(duration) || duration < 0 || duration > 10000) return null;
  if (!Array.isArray(curve) || curve.length !== 4 || !curve.every((c) => typeof c === 'number' && Number.isFinite(c))) {
    return null;
  }
  return { duration, curve: curve as number[] };
}
