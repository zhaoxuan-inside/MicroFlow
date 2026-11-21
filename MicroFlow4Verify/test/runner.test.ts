/// runner 面中性逻辑：FakeSurface 覆盖 pass/fail/skip/事件子集匹配——不 import 任何渲染器。
import { describe, expect, it } from 'vitest';
import { runVerifyScript } from '../src/runner.ts';
import type { VerifySurface, SurfacePage, CapturedEvent, SurfaceDiag } from '../src/surface/port.ts';
import type { VerifyScript } from '../src/script/types.ts';

/** 可编程假面：状态/页/事件/抛错点全部可控。 */
function fakeSurface(options: {
  pages?: Record<string, string>;
  initial?: string;
  evaluate?: (expr: unknown) => unknown;
  throwOnDispatch?: string;
} = {}): VerifySurface & { events: CapturedEvent[] } {
  let currentId: string | null = options.initial ?? null;
  const events: CapturedEvent[] = [];
  return {
    events,
    start: async () => {
      if (options.initial !== undefined) currentId = options.initial;
    },
    open: async (page) => {
      currentId = page;
      events.push({ event: 'ops.page.viewed', payload: { page_definition_id: page } });
    },
    back: async () => {
      currentId = null;
    },
    dispatch: async (nodeId) => {
      if (options.throwOnDispatch === nodeId) throw new Error('dispatch exploded');
      events.push({ event: 'ops.feature.used', payload: { node: nodeId } });
    },
    evaluate: (expr) => options.evaluate?.(expr) ?? null,
    current: (): SurfacePage | null => (currentId ? { id: currentId } : null),
    capturedEvents: () => events,
    surfaceDiagnostics: (): readonly SurfaceDiag[] => [],
  };
}

describe('runVerifyScript', () => {
  it('pass 路径：动作步 + 断言步全过，verdict pass', async () => {
    const surface = fakeSurface({ initial: 'home-page', evaluate: (expr) => ((expr as { ref?: string }).ref === 'state.count' ? 3 : null) });
    const script: VerifyScript = {
      scriptVersion: 1,
      title: '计数',
      steps: [
        { op: 'tap', node: 'inc', event: 'press' },
        { op: 'expect_binding', expr: { ref: 'state.count' }, equals: 3 },
        { op: 'expect_event', event: 'ops.feature.used', payload: { node: 'inc' } },
        { op: 'expect_route', page: 'home-page' },
      ],
    };
    const report = await runVerifyScript({ script, surface, scriptPath: 's.json', surfaceName: 'fake' });
    expect(report.verdict).toBe('pass');
    expect(report.exit).toBe(0);
    expect(report.summary).toEqual({ total: 3, passed: 3, failed: 0 });
    expect(report.assertions.map((a) => a.id)).toEqual(['a1', 'a2', 'a3']);
    expect(report.assertions.every((a) => a.verdict === 'pass')).toBe(true);
    expect(report.meta.surface).toBe('fake');
  });

  it('fail 路径：mismatch 断言给 expected/actual，verdict fail', async () => {
    const surface = fakeSurface({ initial: 'home-page', evaluate: () => 'actual-value' });
    const script: VerifyScript = {
      scriptVersion: 1,
      title: 'mismatch',
      steps: [{ op: 'expect_binding', expr: { ref: 'state.count' }, equals: 'expected-value' }],
    };
    const report = await runVerifyScript({ script, surface, scriptPath: 's.json' });
    expect(report.verdict).toBe('fail');
    expect(report.exit).toBe(1);
    expect(report.summary).toEqual({ total: 1, passed: 0, failed: 1 });
    expect(report.assertions[0]!.detail).toEqual({ expected: 'expected-value', actual: 'actual-value' });
  });

  it('事件子集匹配：多捕获中命中即过；payload 键缺失即败', async () => {
    const surface = fakeSurface({ initial: 'p1' });
    await surface.open('p2');
    await surface.dispatch('btn', 'press');
    const script: VerifyScript = {
      scriptVersion: 1,
      title: '事件',
      steps: [
        { op: 'expect_event', event: 'ops.page.viewed', payload: { page_definition_id: 'p2' } },
        { op: 'expect_event', event: 'ops.page.viewed', payload: { page_definition_id: 'ghost' } },
        { op: 'expect_event', event: 'ops.feature.used', payload: { node: 'btn' } },
      ],
    };
    const report = await runVerifyScript({ script, surface, scriptPath: 's.json' });
    expect(report.assertions.map((a) => a.verdict)).toEqual(['pass', 'fail', 'pass']);
  });

  it('抛错中断：当前步合成失败断言，后续 expect 记 skipped', async () => {
    const surface = fakeSurface({ throwOnDispatch: 'bomb' });
    const script: VerifyScript = {
      scriptVersion: 1,
      title: '中断',
      steps: [
        { op: 'tap', node: 'bomb', event: 'press' },
        { op: 'expect_route', page: 'anywhere' },
      ],
    };
    const report = await runVerifyScript({ script, surface, scriptPath: 's.json' });
    expect(report.verdict).toBe('fail');
    expect(report.assertions[0]!.verdict).toBe('fail');
    expect(report.assertions[0]!.detail).toEqual({ error: 'dispatch exploded' });
    expect(report.assertions[1]!.verdict).toBe('skipped');
    expect(report.summary).toEqual({ total: 2, passed: 0, failed: 2 });
  });

  it('expect_event 未捕获任何事件 → fail 带捕获数', async () => {
    const surface = fakeSurface({ initial: 'p1' });
    const script: VerifyScript = {
      scriptVersion: 1,
      title: '无捕获',
      steps: [{ op: 'expect_event', event: 'ops.page.viewed', payload: { page_definition_id: 'p9' } }],
    };
    const report = await runVerifyScript({ script, surface, scriptPath: 's.json' });
    expect(report.assertions[0]!.verdict).toBe('fail');
    expect(report.assertions[0]!.detail).toEqual({ expected: { event: 'ops.page.viewed', payload: { page_definition_id: 'p9' } }, captured: 0 });
  });
});
