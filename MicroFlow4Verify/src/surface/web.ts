/// web 面适配：MicroFlow4Web MFRuntime → VerifySurface。
/// 本文件是 Verify 中唯一 import 渲染器实现的模块——面切换只动这里。
import type { MFAdapterImpl, MFProjectJson } from '../../../MicroFlow4Web/src/model/types.ts';
import { MFRuntime } from '../../../MicroFlow4Web/src/runtime/runtime.ts';
import { MFExpressionEvaluator } from '../../../MicroFlow4Web/src/runtime/evaluator.ts';
import { MFStandardEvents } from '../../../MicroFlow4Web/src/diagnostics.ts';
import type { VerifySurface, SurfaceOptions, SurfacePage, CapturedEvent, SurfaceDiag } from './port.ts';

/** 标准事件族（供脚本静态门禁做成员检查——单一来源透传，不在 Verify 重复声明）。 */
export const webStandardEvents: ReadonlySet<string> = new Set(Object.values(MFStandardEvents));

export function createWebSurface(options: SurfaceOptions): VerifySurface {
  const impls = (options.impls ?? {}) as unknown as Record<string, MFAdapterImpl>;
  const runtime = new MFRuntime({ project: options.project as MFProjectJson, impls });
  const captured: CapturedEvent[] = [];
  runtime.emissionSink = (envelope) => {
    captured.push({
      event: String(envelope['event']),
      payload: ((envelope['payload'] as Record<string, unknown>) ?? {}) as Record<string, unknown>,
    });
  };

  const currentPage = (): SurfacePage | null => {
    const current = runtime.current;
    return current ? { id: current.definition.id, route: current.definition.route } : null;
  };

  return {
    start: () => runtime.start(),
    open: (pageId, params) => runtime.push(pageId, params ?? {}),
    back: async () => {
      const target = runtime.current?.definition.id;
      if (target !== undefined) await runtime.push(target, {}, 'back');
    },
    dispatch: (nodeId, event, opts) => runtime.dispatchEvent(nodeId, event, opts ?? {}),
    evaluate: (expr) => {
      const scopes = {
        param: runtime.current?.params ?? {},
        state: (runtime.state.peek('page', '') as Record<string, unknown>) ?? {},
        session: (runtime.state.peek('session', '') as Record<string, unknown>) ?? {},
        product: (runtime.state.peek('product', '') as Record<string, unknown>) ?? {},
      };
      return new MFExpressionEvaluator().eval(expr, scopes);
    },
    current: currentPage,
    capturedEvents: () => captured,
    surfaceDiagnostics: (): readonly SurfaceDiag[] => runtime.diagnostics,
  };
}
