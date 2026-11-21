/// 面中性 runner：顺序执行脚本步骤，expect_* 产断言，动作步产副作用。
/// 判定只看断言（面诊断透明披露进 meta——判定与披露分离，不混政策）。
import type { VerifyScript } from './script/types.ts';
import type { VerifySurface } from './surface/port.ts';

export type AssertionVerdict = 'pass' | 'fail' | 'skipped';

export interface VerifyAssertion {
  id: string;
  /** 步骤序号（1 起）。 */
  step: number;
  op: string;
  verdict: AssertionVerdict;
  detail?: Record<string, unknown>;
}

export interface VerifyReport {
  envelope: 'microflow-verify-v1';
  script: string;
  verdict: 'pass' | 'fail';
  assertions: VerifyAssertion[];
  summary: { total: number; passed: number; failed: number };
  meta: {
    startedAt: string;
    durationMs: number;
    surface: string;
    surfaceDiagnostics: { code: string; message: string; severity: string }[];
  };
  exit: 0 | 1 | 2;
}

export interface RunVerifyOptions {
  script: VerifyScript;
  surface: VerifySurface;
  /** 报告中的脚本标识（文件路径或 Spec 场景引用名）。 */
  scriptPath: string;
  /** 面标识（meta 披露）。 */
  surfaceName?: string;
}

/** 结构深比较：规范 JSON 逐字节相等（数组有序、对象键序无关）。 */
function deepEquals(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) {
    return Number.isNaN(a as number) && Number.isNaN(b as number) ? true : a === b;
  }
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((v, i) => deepEquals(v, b[i]));
  }
  const ka = Object.keys(a as Record<string, unknown>).sort();
  const kb = Object.keys(b as Record<string, unknown>).sort();
  if (ka.length !== kb.length || ka.some((k, i) => k !== kb[i])) return false;
  return ka.every((k) => deepEquals((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]));
}

/** payload 子集匹配：期望中的每个键在信封 payload 中深相等。 */
function payloadMatches(expected: Record<string, unknown> | undefined, actual: Record<string, unknown>): boolean {
  if (expected === undefined) return true;
  return Object.keys(expected).every((key) => key in actual && deepEquals(expected[key], actual[key]));
}

function jsonSafe(value: unknown): unknown {
  return value === undefined ? null : value;
}

export async function runVerifyScript(options: RunVerifyOptions): Promise<VerifyReport> {
  const startedAt = new Date().toISOString();
  const startedClock = Date.now();
  const { script, surface } = options;
  const assertions: VerifyAssertion[] = [];
  let aborted = false;
  let abortError: string | undefined;

  const pushAssertion = (step: number, op: string, verdict: AssertionVerdict, detail?: Record<string, unknown>): void => {
    assertions.push({ id: `a${assertions.length + 1}`, step, op, verdict, ...(detail ? { detail } : {}) });
  };

  try {
    await surface.start();
    for (let index = 0; index < script.steps.length; index += 1) {
      const step = script.steps[index]!;
      const stepNo = index + 1;
      if (aborted) {
        if (step.op.startsWith('expect_')) pushAssertion(stepNo, step.op, 'skipped');
        continue;
      }
      try {
        switch (step.op) {
          case 'open':
            await surface.open(step.page, step.params);
            break;
          case 'back':
            await surface.back();
            break;
          case 'tap':
            await surface.dispatch(step.node, step.event, { payload: step.payload, item: step.item });
            break;
          case 'fill':
            // fill 语义镜像真实 DOM（Playwright fill 派发 input 事件）——
            // 模型侧逐键同步绑定 input；change 仍派发以兼容失焦提交类绑定。
            await surface.dispatch(step.node, 'input', { payload: { value: jsonSafe(step.value) } });
            await surface.dispatch(step.node, 'change', { payload: { value: jsonSafe(step.value) } });
            break;
          case 'expect_binding': {
            const actual = surface.evaluate(step.expr);
            const ok = deepEquals(actual, step.equals);
            pushAssertion(stepNo, step.op, ok ? 'pass' : 'fail', ok ? undefined : { expected: jsonSafe(step.equals), actual: jsonSafe(actual) });
            break;
          }
          case 'expect_event': {
            const matched = surface
              .capturedEvents()
              .some((captured) => captured.event === step.event && payloadMatches(step.payload, captured.payload));
            pushAssertion(stepNo, step.op, matched ? 'pass' : 'fail', matched
              ? undefined
              : { expected: { event: step.event, payload: jsonSafe(step.payload) }, captured: surface.capturedEvents().length });
            break;
          }
          case 'expect_route': {
            const current = surface.current();
            const ok = current?.id === step.page;
            pushAssertion(stepNo, step.op, ok ? 'pass' : 'fail', ok ? undefined : { expected: step.page, actual: current?.id ?? null });
            break;
          }
          case 'screenshot':
            pushAssertion(stepNo, step.op, 'fail', { error: 'screenshot 未实现（静态门禁应已拒绝；到达此处是实现缺陷）' });
            break;
        }
      } catch (error) {
        abortError = error instanceof Error ? error.message : String(error);
        aborted = true;
        pushAssertion(stepNo, step.op, 'fail', { error: abortError });
      }
    }
  } catch (error) {
    abortError = error instanceof Error ? error.message : String(error);
    aborted = true;
  }

  const failed = assertions.filter((a) => a.verdict !== 'pass').length;
  const surfaceDiags = surface.surfaceDiagnostics().map((d) => ({ code: d.code, message: d.message, severity: d.severity }));
  return {
    envelope: 'microflow-verify-v1',
    script: options.scriptPath,
    verdict: failed === 0 && !aborted ? 'pass' : 'fail',
    assertions,
    summary: { total: assertions.length, passed: assertions.length - failed, failed },
    meta: {
      startedAt,
      durationMs: Date.now() - startedClock,
      surface: options.surfaceName ?? 'unknown',
      surfaceDiagnostics: surfaceDiags,
    },
    exit: failed === 0 && !aborted ? 0 : 1,
  };
}
