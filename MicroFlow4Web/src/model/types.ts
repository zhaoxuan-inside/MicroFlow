/// MFProject JSON 形态的类型定义（对齐 microflow_model 的数据结构；
/// 字段名采用 snake_case，由 OpcHub frontend_flutter/tool/export_model.dart 导出）。

// ---- 结构树（tree.dart）----

export interface MFNodeJson {
  id: string;
  type: string;
  /** 结构化属性值：字面量 JSON 或 {"ref": "scope.path"} 等表达式形状。 */
  props?: Record<string, unknown>;
  slotOf?: string;
  children?: MFNodeJson[];
  slots?: Record<string, MFNodeJson[]>;
  /** i18n message 引用（§42.2）；与绑定文本互斥。 */
  t?: string;
  /** 样式片引用（§36.4）。 */
  style?: string;
  constraints?: MFSelfConstraintJson | null;
  layer?: string;
}

export interface MFSelfConstraintJson {
  width?: string | number;
  height?: string | number;
  maxWidth?: number;
  minWidth?: number;
  maxHeight?: number;
  minHeight?: number;
  anchor?: Record<string, number>;
}

// ---- 绑定（bindings.dart）----

export type MFConcurrency = 'cancel-previous' | 'supersede' | 'queue' | 'reject-new' | undefined;

export interface MFBindingJson {
  id: string;
  /** "<nodeId>.<event>" 或 "<componentId>.<event>"。 */
  on: string;
  guard?: unknown;
  actions: MFActionJson[];
  concurrency?: MFConcurrency;
  errors?: Record<string, string> | string;
  findings?: string[];
}

export type MFActionJson =
  | { kind: 'state'; state?: string; target?: string; value: unknown; scope?: string }
  | { kind: 'navigation'; target: string; arguments?: Record<string, unknown> }
  | { kind: 'event'; event: string }
  | {
      kind: 'function' | 'adapter' | 'host';
      call: string;
      arguments?: Record<string, unknown>;
      as?: string;
      timeout_ms?: number;
      idempotency?: string;
    }
  | { kind: 'ui'; op?: string; node?: string };

export interface MFBindingMapJson {
  id: string;
  schema_version?: string;
  syntax_version?: string;
  bindings: MFBindingJson[];
}

// ---- 契约（contracts.dart）----

export type MFTypeSpec =
  | { type: 'string' }
  | { type: 'number' }
  | { type: 'bool' }
  | { type: 'enum'; values: string[] }
  | { type: 'object'; required_keys?: string[] }
  | { type: 'list'; item?: MFTypeSpec };

export interface ComponentContractJson {
  props?: Record<string, MFTypeSpec>;
  slots?: string[];
  events?: Record<string, MFTypeSpec>;
  states?: string[];
  layout?: { display?: string[]; sizing?: string[] };
  exposed_styles?: string[];
  motion_surfaces?: string[];
  accessibility_role?: string;
  requires_label?: boolean;
  info?: { provides?: Record<string, string>; consumes?: Record<string, boolean> };
  telemetry?: {
    events?: Record<string, string>;
    privacy_class?: string;
    sampling_ratio?: number;
    args?: string[];
  };
  trace?: { direction?: string; carrier?: string[] };
  /** 适配器 output Schema（§40）：运行时按此校验适配器输出（mf.data.output-invalid）。 */
  output?: MFTypeSpec;
}

/** 注册表资源（registry 条目）：渲染器宿主按 kind 分派实现。 */
export interface RegistryEntryJson {
  id: string;
  kind: 'primitive' | 'adapter' | 'function' | 'capability' | 'host-component';
  contract: ComponentContractJson;
  description?: string;
}

// ---- 样式与主题（styles.dart）----

export interface MFTokenSetJson {
  id: string;
  tokens: Record<string, unknown>;
}

export interface MFThemeJson {
  id: string;
  base?: string;
  extends?: string;
  overrides?: Record<string, unknown>;
}

export interface MFStyleVariantJson {
  when: Record<string, string>;
  set: Record<string, string>;
  order?: number;
}

export interface MFStyleSheetJson {
  id: string;
  extends?: string;
  base?: Record<string, string>;
  variants?: MFStyleVariantJson[];
  schema_version?: string;
}

// ---- i18n / 导航 / manifest（project.dart）----

export interface MFI18nCatalogJson {
  default_locale?: string;
  supported_locales?: string[];
  fallback?: Record<string, string>;
  /** message id -> locale -> value。 */
  messages?: Record<string, Record<string, string>>;
}

export interface MFNavEdgeJson {
  from: string;
  to: string;
  kind?: string;
}

export interface MFNavigationSpecJson {
  edges?: MFNavEdgeJson[];
  fallback?: Record<string, string>;
}

export interface MFManifestJson {
  project_id: string;
  model_version?: string;
  syntax_version?: string;
  targets?: string[];
  entry_page?: string;
  default_theme?: string;
  default_locale?: string;
  supported_locales?: string[];
  type_dialect_version?: string;
}

export interface MFPageJson {
  id: string;
  route: string;
  tree: MFNodeJson;
  stateMembers?: string[];
  parameters?: Record<string, string>;
  onEnter?: string;
  onLeave?: string;
  pageOverrides?: Record<string, string>;
  layerRegions?: {
    id: string;
    region?: string;
    scroll?: boolean;
    overlies?: string[];
    constraint?: MFSelfConstraintJson;
  }[];
  conditionalLayouts?: {
    target: string;
    schemes: { when: Record<string, string>; plan: { direction?: string; align?: string; crossAlign?: string } }[];
    defaultPlan: { direction?: string; align?: string; crossAlign?: string };
  }[];
  findings?: string[];
}

export interface MFProjectJson {
  manifest: MFManifestJson;
  pages: MFPageJson[];
  components?: Record<string, { id: string; tree: MFNodeJson; contract: ComponentContractJson; version?: string; description?: string }>;
  bindingMaps?: Record<string, MFBindingMapJson>;
  i18n?: MFI18nCatalogJson;
  tokens?: Record<string, MFTokenSetJson>;
  styleSheets?: Record<string, MFStyleSheetJson>;
  themes?: Record<string, MFThemeJson>;
  navigation?: MFNavigationSpecJson;
  /** 注册表面：原语/适配器/函数契约（实现由宿主按 id 注册）。 */
  registry?: RegistryEntryJson[];
}

// ---- 求值后的绑定（parse 产物）----

export type MFAction =
  | { kind: 'state'; target: string; value: unknown; scope: string }
  | { kind: 'navigation'; target: string; arguments: Record<string, unknown> }
  | { kind: 'event'; event: string }
  | {
      kind: 'function' | 'adapter' | 'host';
      call: string;
      arguments: Record<string, unknown>;
      as: string | null;
      timeoutMs: number;
      idempotency: string;
    }
  | { kind: 'ui'; op: string; nodeId: string | null };

export type MFPolicy = 'cancelPrevious' | 'supersede' | 'queue' | 'rejectNew' | 'undeclared';

export interface MFBinding {
  id: string;
  on: string;
  guard: unknown | null;
  actions: MFAction[];
  policy: MFPolicy;
  errorBoundary: string | null;
  mapId: string;
}

/** 宿主实现（代码平面）：适配器/函数按 id 注册；capability 降级声明。 */
export type MFAdapterImpl = (args: Record<string, unknown>, ctx: AdapterContext) => Promise<unknown> | unknown;

export interface AdapterContext {
  /** 适配器调用可用的能力探针（Web 平台面）。 */
  platform: 'web';
  signal: AbortSignal;
  runtime: unknown;
}

export interface MFRegistryEntry {
  id: string;
  kind: 'primitive' | 'adapter' | 'function' | 'capability' | 'host-component';
  contract: ComponentContractJson;
  description: string;
  impl?: MFAdapterImpl;
}
