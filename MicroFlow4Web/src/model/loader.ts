/// 模型加载与解析（对齐 microflow_model 的构造语义）。
/// JSON 由 export_model.dart 导出；本模块做形状规范化 + 绑定动作解析 +
/// token/样式求解器（MFStyleResolver 移植）。

import type {
  MFProjectJson,
  MFPageJson,
  MFNodeJson,
  MFBindingJson,
  MFBindingMapJson,
  MFAction,
  MFActionJson,
  MFPolicy,
  ComponentContractJson,
  MFTypeSpec,
  RegistryEntryJson,
  MFTokenSetJson,
  MFThemeJson,
  MFStyleSheetJson,
} from './types.ts';
import { mfDiag, MFCodes, type MFDiag } from '../diagnostics.ts';

// ---- 绑定动作解析（对齐 MFAction.parse）----

export function parseAction(json: MFActionJson): MFAction {
  switch (json.kind) {
    case 'state':
      return {
        kind: 'state',
        target: (json.state ?? json.target) as string,
        value: json.value,
        scope: json.scope ?? 'page',
      };
    case 'navigation':
      return { kind: 'navigation', target: json.target, arguments: json.arguments ?? {} };
    case 'event':
      return { kind: 'event', event: json.event };
    case 'function':
    case 'adapter':
    case 'host':
      return {
        kind: json.kind,
        call: json.call,
        arguments: json.arguments ?? {},
        as: json.as ?? null,
        timeoutMs: json.timeout_ms ?? 5000,
        idempotency: json.idempotency ?? 'read',
      };
    case 'ui':
      return { kind: 'ui', op: json.op ?? 'noop', nodeId: json.node ?? null };
    default:
      throw new Error(`unknown action kind: ${(json as { kind?: string }).kind}`);
  }
}

const POLICY_MAP: Record<string, MFPolicy> = {
  'cancel-previous': 'cancelPrevious',
  supersede: 'supersede',
  queue: 'queue',
  'reject-new': 'rejectNew',
};

export function parseBinding(json: MFBindingJson, mapId: string): MFBindingJsonParsed {
  const errors = json.errors;
  const errorBoundary =
    typeof errors === 'string' ? errors : errors && typeof errors === 'object' ? (errors['*'] ?? null) : null;
  return {
    id: json.id,
    on: json.on,
    guard: json.guard ?? null,
    actions: (json.actions ?? []).map(parseAction),
    policy: (json.concurrency && POLICY_MAP[json.concurrency]) || 'undeclared',
    errorBoundary,
    mapId,
  };
}

export interface MFBindingJsonParsed {
  id: string;
  on: string;
  guard: unknown | null;
  actions: MFAction[];
  policy: MFPolicy;
  errorBoundary: string | null;
  mapId: string;
}

export interface MFBindingMapParsed {
  id: string;
  schemaVersion: string;
  syntaxVersion: string;
  bindings: MFBindingJsonParsed[];
}

// ---- 项目加载 ----

export interface MFProjectParsed {
  manifest: NonNullable<MFProjectJson['manifest']>;
  pages: MFPageJson[];
  pageById: Map<string, MFPageJson>;
  components: Record<string, NonNullable<MFProjectJson['components']>[string]>;
  bindingMaps: Map<string, MFBindingMapParsed>;
  /** 事件锚（"<nodeId>.<event>"）-> 绑定列表（声明顺序）。 */
  bindingsFor: Map<string, MFBindingJsonParsed[]>;
  /** 绑定 id -> 绑定（onEnter 等生命周期锚解析用）。 */
  bindingById: Map<string, MFBindingJsonParsed>;
  i18n: NonNullable<MFProjectJson['i18n']>;
  tokens: Record<string, MFTokenSetJson>;
  styleSheets: Record<string, MFStyleSheetJson>;
  themes: Record<string, MFThemeJson>;
  navigation: NonNullable<MFProjectJson['navigation']>;
  registry: RegistryEntryJson[];
}

export function loadProject(json: MFProjectJson): MFProjectParsed {
  const bindingMaps = new Map<string, MFBindingMapParsed>();
  const bindingsFor = new Map<string, MFBindingJsonParsed[]>();
  const bindingById = new Map<string, MFBindingJsonParsed>();
  for (const [mapId, map] of Object.entries(json.bindingMaps ?? {})) {
    const parsed: MFBindingMapParsed = {
      id: map.id,
      schemaVersion: map.schema_version ?? '1.0',
      syntaxVersion: map.syntax_version ?? '1.0',
      bindings: (map.bindings ?? []).map((b) => parseBinding(b, mapId)),
    };
    bindingMaps.set(mapId, parsed);
    for (const b of parsed.bindings) {
      const list = bindingsFor.get(b.on) ?? [];
      list.push(b);
      bindingsFor.set(b.on, list);
      bindingById.set(b.id, b);
    }
  }
  return {
    manifest: json.manifest,
    pages: json.pages ?? [],
    pageById: new Map((json.pages ?? []).map((p) => [p.id, p])),
    components: json.components ?? {},
    bindingMaps,
    bindingsFor,
    bindingById,
    i18n: json.i18n ?? {},
    tokens: json.tokens ?? {},
    styleSheets: json.styleSheets ?? {},
    themes: json.themes ?? {},
    navigation: json.navigation ?? {},
    registry: json.registry ?? [],
  };
}

export function page(page: MFPageJson): MFPageJson & { stateMembersList: string[] } {
  return { ...page, stateMembersList: page.stateMembers ?? [] };
}

// ---- i18n 解析（§42.5 回退链，对齐 MFI18nCatalog.resolve）----

export interface I18nResult {
  text: string | null;
  fellBack: boolean;
}

export function resolveI18n(
  catalog: NonNullable<MFProjectJson['i18n']>,
  id: string,
  locale: string,
  args: Record<string, unknown> = {},
): I18nResult {
  const variants = catalog.messages?.[id];
  if (!variants) return { text: null, fellBack: false };
  const defaultLocale = catalog.default_locale ?? 'zh-CN';
  const fallback = catalog.fallback ?? {};
  let current = locale;
  const visited = new Set<string>();
  const interpolate = (tpl: string) =>
    Object.entries(args).reduce((out, [k, v]) => out.replaceAll(`{${k}}`, `${v}`), tpl);
  while (!visited.has(current)) {
    visited.add(current);
    const value = variants[current];
    if (value !== undefined) return { text: interpolate(value), fellBack: current !== locale };
    if (current === defaultLocale) {
      const fallbackValue = variants[defaultLocale];
      return {
        text: fallbackValue !== undefined ? interpolate(fallbackValue) : null,
        fellBack: locale !== defaultLocale,
      };
    }
    const next = fallback[current] ?? defaultLocale;
    if (next === current) break;
    current = next;
  }
  return { text: null, fellBack: false };
}

// ---- 样式求解器（MFStyleResolver 移植）----

const MAX_REF_DEPTH = 8;

function deepResolveRefs(tokens: Record<string, unknown>): Record<string, unknown> {
  const ground = (token: string, visiting: Set<string>, depth: number): unknown => {
    if (depth > MAX_REF_DEPTH) return null;
    if (visiting.has(token)) return null;
    visiting.add(token);
    const v = tokens[token];
    if (isRef(v)) return ground(v.ref, visiting, depth + 1);
    return v;
  };
  const resolved: Record<string, unknown> = {};
  for (const [key, v] of Object.entries(tokens)) {
    resolved[key] = isRef(v) ? ground(v.ref, new Set(), 0) : v;
  }
  return resolved;
}

export function isRef(v: unknown): v is { ref: string } {
  return typeof v === 'object' && v !== null && !Array.isArray(v) && typeof (v as { ref?: unknown }).ref === 'string';
}

export class MFStyleResolver {
  readonly defaultThemeId: string;

  constructor(
    private readonly tokenSets: Record<string, MFTokenSetJson>,
    private readonly styleSheets: Record<string, MFStyleSheetJson>,
    private readonly themes: Record<string, MFThemeJson>,
    defaultThemeId?: string,
  ) {
    this.defaultThemeId = defaultThemeId ?? 'theme-light';
  }

  /** 主题生效 token 视图（extends 链 + overrides 重定向 + ref 深解析，§36.3）。 */
  effectiveTokens(themeId: string, visiting: Set<string> = new Set()): Record<string, unknown> {
    if (visiting.has(themeId)) return {};
    const theme = this.themes[themeId];
    const effective: Record<string, unknown> = {};
    const next = new Set([...visiting, themeId]);
    if (!theme) {
      return deepResolveRefs(this.tokenSets[themeId]?.tokens ?? {});
    }
    if (theme.base) Object.assign(effective, this.tokenSets[theme.base]?.tokens ?? {});
    if (theme.extends) Object.assign(effective, this.effectiveTokens(theme.extends, next));
    Object.assign(effective, this.tokenSets[themeId]?.tokens ?? {});
    for (const [key, v] of Object.entries(theme.overrides ?? {})) {
      if (key in effective) {
        effective[key] = isRef(v) ? effective[v.ref] : v;
      }
    }
    return deepResolveRefs(effective);
  }

  /** 主题完备性（§36.3）：每个主题都必须解析全部被引用 token。 */
  completenessDiagnostics(referencedTokens: Iterable<string>): MFDiag[] {
    const diags: MFDiag[] = [];
    const themeIds = [...Object.keys(this.themes), this.defaultThemeId];
    for (const themeId of new Set(themeIds)) {
      const effective = this.effectiveTokens(themeId);
      for (const token of referencedTokens) {
        if (effective[token] === undefined || effective[token] === null) {
          diags.push(
            mfDiag(MFCodes.themeIncomplete, `主题 ${themeId} 无法解析被引用 token ${token}（§36.3）`),
          );
        }
      }
    }
    return diags;
  }

  /** 节点样式面解析（§36.6 覆盖链）：页面覆盖 > 样式片 > token 直取。 */
  resolveNode(
    aspect: string,
    opts: { styleSheetId?: string; pageOverrides?: Record<string, string>; themeId?: string } = {},
  ): { token: string; value: unknown; resolved: boolean } {
    const themeId = opts.themeId ?? this.defaultThemeId;
    const effective = this.effectiveTokens(themeId);
    const pageAspect = opts.pageOverrides?.[aspect];
    if (pageAspect && effective[pageAspect] !== undefined) {
      return { token: pageAspect, value: effective[pageAspect], resolved: true };
    }
    if (opts.styleSheetId) {
      const r = this.resolveSheet(opts.styleSheetId, aspect, { themeId });
      if (r.resolved) return r;
    }
    return { token: aspect, value: effective[aspect], resolved: effective[aspect] !== undefined };
  }

  /** 样式片解析（§36.4）：变体按声明序命中（后者胜），extends 链承接。 */
  resolveSheet(
    sheetId: string,
    aspect: string,
    opts: { conditions?: Record<string, string | null>; themeId?: string; visiting?: Set<string> } = {},
  ): { token: string; value: unknown; resolved: boolean } {
    if (opts.visiting?.has(sheetId)) return { token: aspect, value: null, resolved: false };
    const sheet = this.styleSheets[sheetId];
    if (!sheet) return { token: aspect, value: null, resolved: false };
    const conditions = opts.conditions ?? {};
    const matches = (sheet.variants ?? [])
      .filter((v) => Object.entries(v.when).every(([k, val]) => conditions[k] === val))
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    for (const variant of matches.reverse()) {
      const token = variant.set[aspect];
      if (token) return this.aspectResolved(token, opts.themeId);
    }
    const baseToken = sheet.base?.[aspect];
    if (baseToken) return this.aspectResolved(baseToken, opts.themeId);
    if (sheet.extends) {
      return this.resolveSheet(sheet.extends, aspect, {
        ...opts,
        visiting: new Set([...(opts.visiting ?? []), sheetId]),
      });
    }
    return { token: aspect, value: null, resolved: false };
  }

  private aspectResolved(token: string, themeId?: string) {
    const value = this.effectiveTokens(themeId ?? this.defaultThemeId)[token];
    return { token, value, resolved: value !== undefined };
  }
}

// ---- 契约类型检查（MFTypes.check 对位）----

export function typeCheck(spec: MFTypeSpec | undefined, value: unknown): boolean {
  if (!spec) return true;
  switch (spec.type) {
    case 'string':
      return typeof value === 'string';
    case 'number':
      return typeof value === 'number' && Number.isFinite(value);
    case 'bool':
      return typeof value === 'boolean';
    case 'enum':
      return typeof value === 'string' && spec.values.includes(value);
    case 'object':
      return typeof value === 'object' && value !== null && !Array.isArray(value) &&
        (spec.required_keys ?? []).every((k) => k in (value as Record<string, unknown>));
    case 'list':
      return Array.isArray(value) && (!spec.item || value.every((v) => typeCheck(spec.item, v)));
    default:
      return false;
  }
}

export function contractOf(entry: RegistryEntryJson): ComponentContractJson {
  return entry.contract ?? {};
}
