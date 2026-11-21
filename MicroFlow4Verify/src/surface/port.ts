/// 渲染面中性端口：runner 只依赖本接口——web 面（MFRuntime 适配）与将来的
/// flutter 面（integration_test 驱动）实现同一端口，脚本格式跨面通用。

export interface SurfacePage {
  id: string;
  route?: string;
}

export interface CapturedEvent {
  event: string;
  payload: Record<string, unknown>;
}

export interface SurfaceDiag {
  code: string;
  message: string;
  severity: string;
}

export interface VerifySurface {
  /** 装载入口页（manifest.entry_page + onEnter）；无入口页时为空栈。 */
  start(): Promise<void>;
  /** push 导航到目标页。 */
  open(pageId: string, params?: Record<string, unknown>): Promise<void>;
  /** 回退一步（栈顶弹出）。 */
  back(): Promise<void>;
  /** 事件锚分发：契约事件 → 绑定链（与渲染器同语义）。 */
  dispatch(nodeId: string, event: string, opts?: { payload?: Record<string, unknown>; item?: unknown }): Promise<void>;
  /** 面内求值器（与生产同语义）：MFExpr 深求值，作用域 = 当前页 param/state/session/product。 */
  evaluate(expr: unknown): unknown;
  current(): SurfacePage | null;
  /** 零埋点标准事件捕获（emissionSink 边界）。 */
  capturedEvents(): readonly CapturedEvent[];
  /** 面运行诊断（透明披露进信封 meta，不参与断言判定——判定只看断言）。 */
  surfaceDiagnostics(): readonly SurfaceDiag[];
}

/** 宿主实现（代码平面）：registry id → 真实函数。 */
export type SurfaceImpls = Record<string, (args: Record<string, unknown>, ctx: { signal: AbortSignal }) => unknown>;

export interface SurfaceOptions {
  project: unknown;
  impls?: SurfaceImpls;
}
