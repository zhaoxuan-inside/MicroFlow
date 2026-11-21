import { describe, expect, it } from 'vitest';
import { MFRuntime } from '../src/runtime/runtime.ts';
import { miniProject } from './fixtures/mini.ts';

function makeRuntime() {
  const impls = {
    'mini.increment': (args: Record<string, unknown>) => (args.current as number) + 1,
  };
  return new MFRuntime({ project: miniProject(), impls, themeProvider: () => 'theme-light' });
}

describe('运行时（§13.2 Level 1 解释模式）', () => {
  it('start → 入口页 + onEnter 链写状态', async () => {
    const runtime = makeRuntime();
    await runtime.start();
    expect(runtime.current?.definition.id).toBe('home-page');
    expect(runtime.state.peek('page', 'title')).toBe('首页');
    expect(runtime.state.peek('page', 'count')).toBe(0);
  });

  it('事件分发 → adapter 链 → prev 结果落状态', async () => {
    const runtime = makeRuntime();
    await runtime.start();
    await runtime.dispatchEvent('inc', 'press');
    expect(runtime.state.peek('page', 'count')).toBe(1);
    await runtime.dispatchEvent('inc', 'press');
    expect(runtime.state.peek('page', 'count')).toBe(2);
  });

  it('navigation 动作 → push + ops.page.viewed 零埋点', async () => {
    const runtime = makeRuntime();
    const envelopes: Record<string, unknown>[] = [];
    runtime.emissionSink = (envelope: Record<string, unknown>) => envelopes.push(envelope);
    await runtime.start();
    await runtime.dispatchEvent('goto', 'press');
    expect(runtime.current?.definition.id).toBe('detail-page');
    const viewed = envelopes.filter((e) => e['event'] === 'ops.page.viewed');
    expect(viewed.length).toBeGreaterThanOrEqual(2);
  });

  it('rejectNew 策略拒绝重复触发（§39.1 基线 26）', async () => {
    let calls = 0;
    const impls = {
      'mini.increment': async (args: Record<string, unknown>) => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 30));
        return (args.current as number) + 1;
      },
    };
    const runtime = new MFRuntime({ project: miniProject(), impls });
    await runtime.start();
    // 首次触发进行中；第二次触发应被拒绝。
    const first = runtime.dispatchEvent('inc', 'press');
    await runtime.dispatchEvent('inc', 'press');
    await first;
    expect(calls).toBe(1);
  });

  it('guard 为 false → 链不执行（不是错误）', async () => {
    const project = miniProject();
    project.bindingMaps!['map-home']!.bindings.push({
      id: 'guarded',
      on: 'goto.press',
      guard: { eq: [{ ref: 'state.count' }, 99] },
      concurrency: 'reject-new',
      actions: [{ kind: 'state', target: 'count', value: 999, scope: 'page' }],
    });
    const impls = { 'mini.increment': (a: Record<string, unknown>) => (a.current as number) + 1 };
    const runtime = new MFRuntime({ project, impls });
    await runtime.start();
    await runtime.dispatchEvent('goto', 'press');
    expect(runtime.state.peek('page', 'count')).toBe(0);
  });

  it('未知导航目标 → mf.nav.unknown-target 诊断', async () => {
    const runtime = makeRuntime();
    await runtime.start();
    await runtime.push('nope');
    expect(runtime.diagnostics.some((d) => d.code === 'mf.nav.unknown-target')).toBe(true);
  });

  it('generation 在状态写入后递增', async () => {
    const runtime = makeRuntime();
    await runtime.start();
    const before = runtime.generation.value;
    await runtime.dispatchEvent('inc', 'press');
    expect(runtime.generation.value).toBeGreaterThan(before);
  });
});
