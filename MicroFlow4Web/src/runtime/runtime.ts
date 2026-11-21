/// MFRuntime（§13.2 Level 1 解释运行时，Web 移植）：页面实例/导航/绑定执行/
/// 三层状态/并发策略/guard/超时 unknown/标准事件零埋点/History 同步。

import type {
  MFProjectJson,
  MFPageJson,
  MFNodeJson,
  MFRegistryEntry,
  MFAdapterImpl,
  MFAction,
} from '../model/types.ts';
import { loadProject, type MFProjectParsed, type MFBindingJsonParsed } from '../model/loader.ts';
import { MFStateStore, type MFStateScope } from './state-store.ts';
import { MFExpressionEvaluator, type EvalScopes } from './evaluator.ts';
import { mfDiag, MFCodes, MFStandardEvents, type MFDiag } from '../diagnostics.ts';

export interface MFPageInstance {
  id: string;
  definition: MFPageJson;
  params: Record<string, unknown>;
  frozen: { theme: string; locale: string };
}

export interface MFRuntimeOptions {
  project: MFProjectJson;
  /** 宿主实现注册（适配器/函数）；契约来自项目 registry 面。 */
  impls?: Record<string, MFAdapterImpl>;
  registryEntries?: { id: string; kind: string; contract: import('../model/types.ts').ComponentContractJson }[];
  themeProvider?: () => string;
  locale?: string;
  releaseId?: string;
  environment?: string;
  /** History 同步（浏览器；测试环境可省略）。 */
  history?: { pushUrl(url: string): void; replaceUrl(url: string): void };
  /** 页面 id -> 路径（History 同步用；缺省用页面定义 route）。 */
  routeResolver?: (pageId: string, params: Record<string, unknown>) => string;
}

export interface MFActionContext {
  instance: MFPageInstance;
  scopes: EvalScopes;
  requestId: string;
  signal: AbortSignal;
}

export interface MFActionResult {
  results: Record<string, unknown>;
  aborted: boolean;
}

const STANDARD_EVENTS = new Set<string>(Object.values(MFStandardEvents));

export class MFRuntime {
  readonly project: MFProjectParsed;
  readonly state = new MFStateStore();
  private readonly impls: Record<string, MFAdapterImpl>;
  private readonly contractById: Map<string, import('../model/types.ts').ComponentContractJson>;
  private readonly evaluator = new MFExpressionEvaluator((id) => {
    const impl = this.impls[id];
    if (!impl) return undefined;
    return (args, ctx) => impl(args, { platform: 'web', signal: new AbortController().signal, runtime: this }) ?? null;
  });
  private readonly diagList: MFDiag[] = [];
  private readonly debugEventList: { kind: string; [k: string]: unknown }[] = [];
  private readonly listeners = new Set<() => void>();
  private readonly inflight = new Map<string, { controller: AbortController; queued: (() => void)[] }>();
  private themeProvider?: () => string;
  private localeValue: string;
  private releaseId: string;
  private environment: string;
  private history?: MFRuntimeOptions['history'];
  private routeResolver?: MFRuntimeOptions['routeResolver'];
  private revision = 0;
  private instanceCounter = 0;
  private started = false;

  /** 页面实例栈（栈顶为当前页）。 */
  stack: MFPageInstance[] = [];
  /** 渲染代数信号：任何状态写入/导航后递增（渲染器重建）。 */
  generation: { value: number; subscribe(fn: () => void): () => void } = {
    value: 0,
    subscribe: (fn) => {
      this.listeners.add(fn);
      return () => this.listeners.delete(fn);
    },
  };

  /** 宿主 UI 动作处理面（fn.ui.* 由渲染器壳注册；§39 ui 动作）。 */
  uiHandler?: (op: string, nodeId: string | null, payload: Record<string, unknown>) => void;

  constructor(options: MFRuntimeOptions) {
    this.project = loadProject(options.project);
    this.impls = options.impls ?? {};
    this.contractById = new Map();
    for (const e of options.registryEntries ?? this.project.registry) {
      this.contractById.set(e.id, e.contract);
    }
    this.themeProvider = options.themeProvider;
    this.localeValue = options.locale ?? this.project.manifest.default_locale ?? 'zh-CN';
    this.releaseId = options.releaseId ?? 'release-local';
    this.environment = options.environment ?? 'preview';
    this.history = options.history;
    this.routeResolver = options.routeResolver;
  }

  // ---- 诊断与观测 ----

  get diagnostics(): MFDiag[] {
    return this.diagList;
  }

  diagSink = {
    add: (diag: MFDiag) => {
      this.diagList.push(diag);
    },
  };

  get debugEvents(): { kind: string; [k: string]: unknown }[] {
    return this.debugEventList;
  }

  private debug(kind: string, payload: Record<string, unknown>): void {
    this.debugEventList.push({ kind, ...payload });
  }

  /** 零埋点标准事件（§24.7）：运行时拦截边界产生；宿主 sink 消费。 */
  emissionSink?: (envelope: Record<string, unknown>) => void;

  private emitStandard(event: string, payload: Record<string, unknown>, instance: MFPageInstance): void {
    if (!STANDARD_EVENTS.has(event)) {
      this.diagSink.add(mfDiag(MFCodes.teleManualStandardEvent,
        `业务代码手工上报标准事件族：${event}`, 'error', 'runtime'));
      return;
    }
    this.emissionSink?.({
      event,
      timestamp: new Date().toISOString(),
      release_id: this.releaseId,
      environment: this.environment,
      page_definition_id: instance.definition.id,
      page_instance_id: instance.id,
      locale: instance.frozen.locale,
      payload,
    });
  }

  private bump(): void {
    this.revision += 1;
    this.generation.value = this.revision;
    for (const fn of this.listeners) fn();
  }

  // ---- 启动与导航 ----

  get current(): MFPageInstance | null {
    return this.stack.at(-1) ?? null;
  }

  async start(): Promise<void> {
    if (this.started) return;
    this.started = true;
    const entry = this.project.manifest.entry_page;
    if (entry) {
      await this.push(entry, {}, 'replace');
    }
  }

  /** 契约事件分发入口（渲染器事件锚 → 绑定链）。 */
  async dispatchEvent(
    nodeId: string,
    event: string,
    opts: { payload?: Record<string, unknown>; item?: unknown } = {},
  ): Promise<void> {
    const bindings = this.project.bindingsFor.get(`${nodeId}.${event}`) ?? [];
    for (const binding of bindings) {
      await this.runBinding(binding, {
        payload: opts.payload ?? {},
        item: opts.item,
        instance: this.current!,
      });
    }
  }

  /** 生命周期锚执行（onEnter/onLeave）。 */
  async execute(bindingId: string, instance: MFPageInstance = this.current!): Promise<void> {
    const binding = this.project.bindingById.get(bindingId);
    if (!binding) {
      this.diagSink.add(mfDiag(MFCodes.refDangling, `生命周期锚 ${bindingId} 未指向任何绑定`, 'error', 'runtime'));
      return;
    }
    await this.runBinding(binding, { instance });
  }

  async push(
    targetName: string,
    args: Record<string, unknown> = {},
    kind: 'push' | 'replace' | 'back' = 'push',
  ): Promise<void> {
    const project = this.project;
    const target = project.pageById.get(targetName);
    if (!target) {
      this.diagSink.add(mfDiag(MFCodes.navUnknownTarget, `导航目标 ${targetName} 不存在`, 'error', 'runtime'));
      return;
    }
    if (kind === 'replace' || kind === 'back') {
      this.stack.pop();
      if (kind === 'back') {
        const prev = this.stack.at(-1)!;
        this.emitStandard(MFStandardEvents.pageViewed,
          { entry: 'back', referrer_route: target.route }, prev);
        this.syncUrl(prev);
        this.bump();
        return;
      }
    }
    await this.open(target, args);
  }

  private async open(target: MFPageJson, args: Record<string, unknown>): Promise<void> {
    const instance: MFPageInstance = {
      id: `pi_${++this.instanceCounter}`,
      definition: target,
      params: args,
      frozen: { theme: this.themeProvider?.() ?? this.project.manifest.default_theme ?? 'theme-light', locale: this.localeValue },
    };
    this.stack.push(instance);
    this.debug('navigation', {
      page_definition_id: target.id,
      page_instance_id: instance.id,
      route: target.route,
      entry: this.stack.length === 1 ? 'external' : 'push',
    });
    this.emitStandard(MFStandardEvents.pageViewed, {
      page_definition_id: target.id,
      entry: this.stack.length === 1 ? 'external' : 'push',
      referrer_route: null,
      locale: instance.frozen.locale,
    }, instance);
    this.syncUrl(instance);
    this.bump();
    if (target.onEnter) {
      await this.execute(target.onEnter, instance);
    }
  }

  private syncUrl(instance: MFPageInstance): void {
    if (!this.history) return;
    const path = this.routeResolver
      ? this.routeResolver(instance.definition.id, instance.params)
      : instance.definition.route;
    this.history.replaceUrl(path);
  }

  // ---- 绑定链执行（§39）----

  private async runBinding(
    binding: MFBindingJsonParsed,
    ctx: { payload?: Record<string, unknown>; item?: unknown; instance: MFPageInstance },
  ): Promise<void> {
    // 并发策略（§39.1）：undeclared/rejectNew 拒绝重复触发。
    const inflight = this.inflight.get(binding.id);
    if (inflight) {
      switch (binding.policy) {
        case 'rejectNew':
        case 'undeclared':
          this.debug('binding-rejected', { binding_id: binding.id, policy: binding.policy });
          return;
        case 'cancelPrevious':
          inflight.controller.abort();
          break;
        case 'supersede':
          inflight.controller.abort();
          break;
        case 'queue':
          await new Promise<void>((resolve) => inflight.queued.push(resolve));
          break;
      }
    }
    const controller = new AbortController();
    const queued: (() => void)[] = [];
    this.inflight.set(binding.id, { controller, queued });
    try {
      await this.executeChain(binding, ctx, controller.signal);
    } finally {
      this.inflight.delete(binding.id);
      for (const resolve of queued) resolve();
    }
  }

  private scopesFor(instance: MFPageInstance, payload: Record<string, unknown>, item: unknown, prev: Record<string, unknown>): EvalScopes {
    return {
      param: instance.params,
      state: (this.state.peek('page', '') as Record<string, unknown>) ?? {},
      session: (this.state.peek('session', '') as Record<string, unknown>) ?? {},
      product: (this.state.peek('product', '') as Record<string, unknown>) ?? {},
      prev,
      item,
      payload,
    } as unknown as EvalScopes;
  }

  private async executeChain(
    binding: MFBindingJsonParsed,
    ctx: { payload?: Record<string, unknown>; item?: unknown; instance: MFPageInstance },
    signal: AbortSignal,
  ): Promise<void> {
    const instance = ctx.instance;
    const requestId = `ar_${binding.id}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    const scopes = this.scopesFor(instance, ctx.payload ?? {}, ctx.item, {});
    const evaluator = new MFExpressionEvaluator((id) => {
      const impl = this.impls[id];
      if (!impl) return undefined;
      return (args, fnCtx) => impl(args, { platform: 'web', signal, runtime: this }) ?? null;
    });
    // guard：false → 本条不执行（不是错误，§39.1）。
    if (binding.guard !== null && binding.guard !== undefined) {
      if (!truthy(evaluator.eval(binding.guard, scopes))) return;
    }
    const results: Record<string, unknown> = { last: null };
    // 链级共享作用域：adapter 的 as 结果写回 scopes.prev（同一引用），后续
    // 动作的 prev.<as> 引用即时可见（§39.2）。
    const scopesWithPrev: EvalScopes = { ...scopes, prev: results };
    this.debug('action-request', { request_id: requestId, binding_id: binding.id });
    try {
      for (const action of binding.actions) {
        if (signal.aborted) {
          results.last = { aborted: true };
          break;
        }
        const value = await this.runAction(action, scopesWithPrev, instance, requestId, signal);
        results.last = value;
      }
    } catch (err) {
      // 错误边界：声明了 errors.* 才传播；否则按 unknown 记录（§37.4）。
      const message = err instanceof Error ? err.message : String(err);
      if (binding.errorBoundary && binding.errorBoundary !== '*') {
        this.diagSink.add(mfDiag(MFCodes.interactionErrorPropagation,
          `绑定 ${binding.id} 错误落入边界 ${binding.errorBoundary}：${message}`, 'warning', 'runtime'));
      } else {
        this.diagSink.add(mfDiag(MFCodes.interactionErrorPropagation,
          `绑定 ${binding.id} 执行错误：${message}`, 'warning', 'runtime'));
      }
      results.last = { error: message };
    }
    this.bump();
  }

  private async runAction(
    action: MFAction,
    scopes: EvalScopes,
    instance: MFPageInstance,
    requestId: string,
    signal: AbortSignal,
  ): Promise<unknown> {
    switch (action.kind) {
      case 'state': {
        if (action.scope === 'component') {
          throw new Error('component 状态只能写组件内部，不进入页面绑定（§6）');
        }
        const evaluator = new MFExpressionEvaluator();
        const value = evaluator.eval(action.value, scopes);
        const scope = (['session', 'product'].includes(action.scope) ? action.scope : 'page') as MFStateScope;
        this.state.writeDeep(scope, action.target, value);
        this.debug('state', { target: action.target, scope, action_request_id: requestId });
        return value;
      }
      case 'navigation': {
        const evaluator = new MFExpressionEvaluator();
        const args: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(action.arguments)) args[k] = evaluator.eval(v, scopes);
        await this.push(action.target, args);
        return { navigated: action.target };
      }
      case 'event':
        return action.event;
      case 'function':
      case 'adapter':
      case 'host': {
        const impl = this.impls[action.call];
        if (!impl) {
          this.diagSink.add(mfDiag(MFCodes.capUnavailable,
            `适配器 ${action.call} 无宿主实现，按声明降级`, 'warning', 'runtime'));
          return null;
        }
        const evaluator = new MFExpressionEvaluator();
        const args: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(action.arguments)) args[k] = evaluator.eval(v, scopes);
        // 超时（§40）：超时不当作未执行，dataTimeout 诊断。
        const controller = new AbortController();
        signal.addEventListener('abort', () => controller.abort());
        const timer = setTimeout(() => controller.abort(), action.timeoutMs);
        try {
          let result: unknown;
          try {
            result = await impl(args, { platform: 'web', signal: controller.signal, runtime: this });
          } finally {
            clearTimeout(timer);
          }
          if (controller.signal.aborted && result === undefined) {
            this.diagSink.add(mfDiag(MFCodes.dataTimeout,
              `适配器 ${action.call} 调用超时（${action.timeoutMs}ms，不当作未执行）`, 'warning', 'runtime'));
          }
          // output Schema 校验（§40 mf.data.output-invalid）。
          const contract = this.contractById.get(action.call);
          if (contract?.output) {
            const { typeCheck } = await import('../model/loader.ts');
            if (!typeCheck(contract.output, result)) {
              this.diagSink.add(mfDiag(MFCodes.dataOutputInvalid,
                `适配器 ${action.call} 输出不符合 output Schema`, 'warning', 'runtime'));
            }
          }
          if (action.as) scopes.prev = { ...(scopes.prev ?? {}), [action.as]: result };
          return result;
        } catch (err) {
          if (controller.signal.aborted) {
            this.diagSink.add(mfDiag(MFCodes.dataTimeout,
              `适配器 ${action.call} 调用超时（${action.timeoutMs}ms，不当作未执行）`, 'warning', 'runtime'));
            return null;
          }
          throw err;
        }
      }
      case 'ui': {
        this.uiHandler?.(action.op, action.nodeId, { request_id: requestId });
        return { ui: action.op };
      }
      default:
        return null;
    }
  }
}

function truthy(v: unknown): boolean {
  return v !== null && v !== undefined && v !== false && v !== 0 && v !== '';
}
