/// MFInterpreter：MFNode 树 → DOM。每次 renderPage 是纯函数（同节点 + 同
/// 已解析状态 → 同 DOM 形状，§7.3 基线 18）；宿主在 generation 变化时重建，
/// 页面切换经 View Transitions API 承接（§ user-experience）。
///
/// 动效面纪律（§36.5）：只对契约 motionSurfaces 声明的面施加；未声明面记录
/// mf.motion.surface-undeclared。token → CSS 自定义属性注入页面根（oklch 值
/// 原样透传）。语义/无障碍：契约 accessibility_role / requires_label 落位，
/// 文本节点经 i18n 回退链（缺失翻译上报诊断，§42.5）。

import type { MFNodeJson, MFPageJson, ComponentContractJson } from '../model/types.ts';
import { resolveI18n, MFStyleResolver } from '../model/loader.ts';
import { mfDiag, MFCodes, type MFDiag } from '../diagnostics.ts';
import { resolveMotion, cubicBezierCss, type MFMotionResolution } from './motion.ts';
import { mfColorToCss, tokenToCssValue } from './color.ts';
import { createPrimitiveTable, type MFPrimitiveBuilder, type MFNodeView, type MFPrimitiveTable } from './primitives.ts';
import type { MFRuntime, MFPageInstance } from '../runtime/runtime.ts';

export interface MFRenderConditions {
  platform?: string;
  breakpoint?: string;
  /** 'reduced' → 减少动效替代组命中（§36.7；映射 prefers-reduced-motion）。 */
  motion?: string | null;
  [key: string]: string | null | undefined;
}

export interface MFRenderContext {
  props: Record<string, unknown>;
  onEvent: (nodeId: string, event: string, payload?: Record<string, unknown>) => void;
  tokenColor: (token: string) => string;
  motionSurfaces: Set<string>;
  resolveMotion: (token: string) => MFMotionResolution;
  recordMotionDiag: (diag: MFDiag) => void;
  conditions: MFRenderConditions;
}

export interface MFInterpreterOptions {
  /** 宿主原语覆盖表（type -> builder；缺省用 Tier A/B 默认实现）。 */
  builders?: Record<string, MFPrimitiveBuilder>;
  /** i18n 回退链；缺省用项目 i18n + 缺失翻译诊断。 */
  localize?: (messageId: string, locale: string) => string;
  /** 颜色 token 解析（缺省取主题生效 token 的字符串值）。 */
  resolveColor?: (token: string) => unknown;
}

export class MFInterpreter {
  private readonly table: MFPrimitiveTable;
  private readonly resolver: MFStyleResolver;
  private localizeFn: (messageId: string, locale: string) => string;

  constructor(
    private readonly runtime: MFRuntime,
    options: MFInterpreterOptions = {},
  ) {
    this.table = createPrimitiveTable();
    for (const [type, builder] of Object.entries(options.builders ?? {})) {
      this.table.builders.set(type, builder);
    }
    const model = runtime.project;
    this.resolver = new MFStyleResolver(model.tokens, model.styleSheets, model.themes, runtime.project.manifest.default_theme);
    this.localizeFn =
      options.localize ??
      ((messageId, locale) => {
        const r = resolveI18n(runtime.project.i18n, messageId, locale);
        if (r.text === null) {
          runtime.diagSink.add(mfDiag(MFCodes.i18nMissingTranslation,
            `message ${messageId} 缺失翻译（locale=${locale}）`, 'warning', 'runtime'));
          return messageId;
        }
        if (r.fellBack) {
          runtime.diagSink.add(mfDiag(MFCodes.i18nMissingTranslation,
            `message ${messageId} 回退链展示（locale=${locale}）`, 'info', 'runtime'));
        }
        return r.text;
      });
    void options.resolveColor;
  }

  /** 渲染整页：返回页面根元素（语义结构；主题经 theme-css 级联承载）。 */
  renderPage(instance: MFPageInstance, conditions: MFRenderConditions = {}): HTMLElement {
    const tokens = this.resolver.effectiveTokens(this.documentThemeId());
    const root = document.createElement('div');
    root.className = 'mf-page';
    root.dataset.pageId = instance.definition.id;
    root.lang = instance.frozen.locale;
    const stateLayer = (this.runtime.state.peek('page', '') as Record<string, unknown>) ?? {};
    const ctxBase: Omit<MFRenderContext, 'props' | 'motionSurfaces' | 'resolveMotion'> = {
      onEvent: (nodeId, event, payload) => {
        void this.runtime.dispatchEvent(nodeId, event, { payload });
      },
      tokenColor: (token) => {
        const v = tokens[token];
        return typeof v === 'string' ? mfColorToCss(v) : '';
      },
      recordMotionDiag: (diag) => this.runtime.diagSink.add(diag),
      conditions,
    };
    root.appendChild(
      this.buildNode(instance.definition.tree, instance, conditions, tokens, ctxBase, stateLayer, null),
    );
    return root;
  }

  /** 文档当前主题 id（宿主经 data-mf-theme 声明；缺省回落 manifest 默认）。 */
  private documentThemeId(): string {
    const attr = document.documentElement.dataset.mfTheme;
    if (attr && this.runtime.project.themes[attr]) return attr;
    return this.runtime.project.manifest.default_theme ?? 'theme-light';
  }

  /**
   * 声明式列表绑定（对齐 Dart interpreter._renderItemTemplates）：List 节点
   * 携带求值后的 items（List<Map>）时，children 是项模板——每项以 item
   * 作用域渲染模板子树，事件经 dispatchEvent 携带项上下文执行；>30 项走
   * content-visibility 虚拟化面。
   */
  private renderItemTemplates(
    node: MFNodeJson,
    items: unknown[],
    instance: MFPageInstance,
    conditions: MFRenderConditions,
    tokens: Record<string, unknown>,
    ctxBase: Omit<MFRenderContext, 'props' | 'motionSurfaces' | 'resolveMotion'>,
    stateLayer: Record<string, unknown>,
  ): HTMLElement {
    const wrap = document.createElement('div');
    wrap.className = 'mf-list-templates';
    wrap.style.cssText = 'display:flex;flex-direction:column;min-width:0';
    const virtualize = items.length > 30;
    items.forEach((raw, i) => {
      if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
        this.runtime.diagSink.add(mfDiag(MFCodes.interactionUnknownMember,
          `列表绑定第 ${i} 项不是结构化对象，已跳过（node=${node.id}）`, 'warning', 'runtime'));
        return;
      }
      const item = raw as Record<string, unknown>;
      const row = document.createElement('div');
      row.className = 'mf-list-templates__row';
      if (virtualize) {
        row.style.contentVisibility = 'auto';
        row.style.containIntrinsicSize = 'auto 72px';
      }
      // 项模板子树：item 作用域 + 事件携带项上下文执行（§39 列表模板语义）。
      const itemEventBase: typeof ctxBase = {
        ...ctxBase,
        onEvent: (nodeId, event, payload) => {
          void this.runtime.dispatchEvent(nodeId, event, { payload, item });
        },
      };
      for (const template of node.children ?? []) {
        const built = this.buildNode(template, instance, conditions, tokens, itemEventBase, stateLayer, item);
        if (built instanceof HTMLElement) row.appendChild(built);
      }
      wrap.appendChild(row);
    });
    return wrap;
  }

  private buildNode(
    node: MFNodeJson,
    instance: MFPageInstance,
    conditions: MFRenderConditions,
    tokens: Record<string, unknown>,
    ctxBase: Omit<MFRenderContext, 'props' | 'motionSurfaces' | 'resolveMotion'>,
    stateLayer: Record<string, unknown>,
    item: unknown,
  ): HTMLElement | Text {
    // 条件渲染（visible 结构化谓词，0.8.0）。
    const visibleRaw = (node.props ?? {})['visible'];
    if (visibleRaw !== undefined) {
      const resolved = evalPredicate(visibleRaw, { param: instance.params, state: stateLayer, item });
      if (!resolved) return document.createTextNode('');
    }
    const nodeProps = node.props ?? {};
    const contract = this.contractFor(node.type);
    const scopes = { param: instance.params, state: stateLayer, session: this.runtime.state.peek('session', '') ?? {}, product: this.runtime.state.peek('product', '') ?? {}, item } as Record<string, unknown>;
    const props = evaluateProps(nodeProps, scopes);
    // 声明式列表绑定（§39 列表模板语义）：List 携带 items（List<Map>）时
    // children 是项模板——项级渲染在通用构建之前短路。
    if (node.type === 'List' && Array.isArray(props['items'])) {
      return this.renderItemTemplates(
        node,
        props['items'] as unknown[],
        instance,
        conditions,
        tokens,
        ctxBase,
        stateLayer,
      );
    }
    // i18n 文本通道（§42.2）：t 与绑定文本互斥。
    if (node.t && !('text' in props)) {
      props['text'] = this.localizeFn(node.t, instance.frozen.locale);
    }
    const motionSurfaces = new Set(contract?.motion_surfaces ?? []);
    const reduceMotion = conditions['motion'] === 'reduced';
    const renderCtx: MFRenderContext = {
      ...ctxBase,
      props,
      motionSurfaces,
      resolveMotion: (token) =>
        resolveMotion(token, tokens, reduceMotion, (diag) => this.runtime.diagSink.add(diag)),
    };
    // 子树构建（默认槽 + 命名槽），列表模板 item 经 list 作用域传递。
    const children = (node.children ?? []).map((c) => this.buildNode(c, instance, conditions, tokens, ctxBase, stateLayer, item));
    const slots: Record<string, HTMLElement[]> = {};
    for (const [slot, list] of Object.entries(node.slots ?? {})) {
      slots[slot] = list.map((c) => {
        const built = this.buildNode(c, instance, conditions, tokens, ctxBase, stateLayer, item);
        return built instanceof HTMLElement ? built : el('span');
      });
    }
    const builder = this.table.builders.get(node.type);
    let element: HTMLElement;
    if (builder) {
      element = builder(renderCtx, { node, children: children.filter(isHTMLElement), slots });
    } else {
      element = document.createElement('div');
      element.className = 'mf-unknown';
      element.dataset.mfType = node.type;
      element.append(...children.filter(isHTMLElement));
      this.runtime.diagSink.add(mfDiag(MFCodes.regUnregisteredRef,
        `节点 ${node.id} 无渲染实现：${node.type}（降级为容器）`, 'warning', 'runtime'));
    }
    element.dataset.mfNode = node.id;
    applyContractSemantics(element, contract, props);
    applySelfConstraint(element, node.constraints);
    this.applyEntranceMotion(element, node, motionSurfaces, tokens, reduceMotion);
    return element;
  }

  /** 入场动效（§36.5 entrance 面）：CSS transition + @starting-style 风格。 */
  private applyEntranceMotion(
    element: HTMLElement,
    node: MFNodeJson,
    surfaces: Set<string>,
    tokens: Record<string, unknown>,
    reduceMotion: boolean,
  ): void {
    if (!surfaces.has('entrance') || (node.props ?? {})['entrance'] === false) return;
    const resolution = resolveMotion('motion.entrance', tokens, reduceMotion, (diag) =>
      this.runtime.diagSink.add(diag));
    if (!resolution.spec || resolution.spec.durationMs <= 0) return;
    element.classList.add('mf-entrance');
    element.style.transitionDuration = `${resolution.spec.durationMs}ms`;
    element.style.transitionTimingFunction = cubicBezierCss(resolution.spec.curve);
    // 首帧后进入终态（requestAnimationFrame 一跳触发 transition）。
    requestAnimationFrame(() => element.classList.add('mf-entrance--done'));
  }

  private contractFor(type: string): ComponentContractJson | null {
    const entry = this.runtime.project.registry.find((e) => e.id === type);
    if (entry) return entry.contract;
    return this.runtime.project.components[type]?.contract ?? null;
  }
}

// ---- 帮助函数 ----

function isHTMLElement(v: HTMLElement | Text): v is HTMLElement {
  return v instanceof HTMLElement;
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
}

/** props 深求值：ref/表达式形状 → 值；字面量骨架保持。 */
function evaluateProps(props: Record<string, unknown>, scopes: Record<string, unknown>): Record<string, unknown> {
  const evalV = (v: unknown): unknown => {
    if (v === null || typeof v !== 'object') return v;
    if (Array.isArray(v)) return v.map(evalV);
    const rec = v as Record<string, unknown>;
    if (typeof rec['ref'] === 'string') return resolveScopePath(rec['ref'] as string, scopes);
    if (typeof rec['call'] === 'string') return null; // 渲染期不执行函数调用（代码平面）。
    const out: Record<string, unknown> = {};
    for (const [k, val] of Object.entries(rec)) out[k] = evalV(val);
    return out;
  };
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(props)) out[k] = evalV(v);
  return out;
}

function resolveScopePath(path: string, scopes: Record<string, unknown>): unknown {
  const parts = path.split('.');
  let cur: unknown = scopes[parts[0]!];
  for (const p of parts.slice(1)) {
    if (cur !== null && typeof cur === 'object') cur = (cur as Record<string, unknown>)[p];
    else return null;
  }
  return cur ?? null;
}

/** 结构化谓词求值（visible/guard 形状：比较/逻辑/ref/literal）。 */
function evalPredicate(value: unknown, scopes: Record<string, unknown>): boolean {
  if (value === null || typeof value !== 'object') return Boolean(value);
  if (Array.isArray(value)) return value.every((v) => evalPredicate(v, scopes));
  const rec = value as Record<string, unknown>;
  for (const op of ['gt', 'gte', 'lt', 'lte', 'eq', 'neq'] as const) {
    if (op in rec) {
      const [rawA, rawB] = rec[op] as unknown[];
      const a = typeof rawA === 'object' && rawA !== null && 'ref' in (rawA as Record<string, unknown>)
        ? resolveScopePath((rawA as { ref: string }).ref, scopes)
        : evalPredicate(rawA, scopes) ? rawA : resolveValue(rawA, scopes);
      const b = typeof rawB === 'object' && rawB !== null && 'ref' in (rawB as Record<string, unknown>)
        ? resolveScopePath((rawB as { ref: string }).ref, scopes)
        : resolveValue(rawB, scopes);
      switch (op) {
        case 'gt': return (a as number) > (b as number);
        case 'gte': return (a as number) >= (b as number);
        case 'lt': return (a as number) < (b as number);
        case 'lte': return (a as number) <= (b as number);
        case 'eq': return a === b;
        case 'neq': return a !== b;
      }
    }
  }
  if ('and' in rec) return (rec['and'] as unknown[]).every((v) => evalPredicate(v, scopes));
  if ('or' in rec) return (rec['or'] as unknown[]).some((v) => evalPredicate(v, scopes));
  if ('not' in rec) return !evalPredicate(rec['not'], scopes);
  if (typeof rec['ref'] === 'string') return Boolean(resolveScopePath(rec['ref'] as string, scopes));
  return Boolean(value);
}

function resolveValue(v: unknown, scopes: Record<string, unknown>): unknown {
  if (typeof v === 'object' && v !== null && 'ref' in (v as Record<string, unknown>)) {
    return resolveScopePath((v as { ref: string }).ref, scopes);
  }
  return v;
}

function applyContractSemantics(
  element: HTMLElement,
  contract: ComponentContractJson | null,
  props: Record<string, unknown>,
): void {
  if (!contract) return;
  if (contract.accessibility_role) element.setAttribute('role', contract.accessibility_role);
  if (contract.requires_label) {
    const label = props['label'] ?? props['text'] ?? props['ariaLabel'];
    if (typeof label === 'string' && label) element.setAttribute('aria-label', label);
  }
}

function applySelfConstraint(
  element: HTMLElement,
  constraints: MFNodeJson['constraints'],
): void {
  if (!constraints) return;
  if (constraints.width === 'fill') element.style.width = '100%';
  else if (typeof constraints.width === 'number') element.style.width = `${constraints.width}px`;
  if (constraints.height === 'fill') element.style.height = '100%';
  else if (typeof constraints.height === 'number') element.style.height = `${constraints.height}px`;
  if (typeof constraints.maxWidth === 'number') element.style.maxWidth = `${constraints.maxWidth}px`;
  if (typeof constraints.minWidth === 'number') element.style.minWidth = `${constraints.minWidth}px`;
  if (typeof constraints.maxHeight === 'number') element.style.maxHeight = `${constraints.maxHeight}px`;
  if (typeof constraints.minHeight === 'number') element.style.minHeight = `${constraints.minHeight}px`;
}

/** View Transitions API 页面切换（§ user-experience）：宿主换页包装。 */
export function withViewTransition(update: () => void): void {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (typeof doc.startViewTransition === 'function' && !reduceMotion) {
    doc.startViewTransition(update);
  } else {
    update();
  }
}
