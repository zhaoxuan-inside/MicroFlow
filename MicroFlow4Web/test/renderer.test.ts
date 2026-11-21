import { describe, expect, it, beforeEach } from 'vitest';
import { MFRuntime } from '../src/runtime/runtime.ts';
import { MFInterpreter, withViewTransition } from '../src/renderer/interpreter.ts';
import { buildThemeCss } from '../src/renderer/theme-css.ts';
import { MFValidator } from '../src/validator/validator.ts';
import { miniProject } from './fixtures/mini.ts';

async function boot(impls: Record<string, (args: Record<string, unknown>) => unknown> = {}) {
  const runtime = new MFRuntime({ project: miniProject(), impls, themeProvider: () => 'theme-light' });
  await runtime.start();
  const interpreter = new MFInterpreter(runtime);
  return { runtime, interpreter };
}

describe('DOM 渲染器（§7.3 确定性 / §36.5 动效面 / 语义）', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('mini fixture 通过静态门禁', () => {
    const result = new MFValidator(miniProject()).validate();
    expect(result.diags.filter((d: { code: string; severity: string }) => d.severity === 'error')).toEqual([]);
  });

  it('页面渲染：主题级联生成 + 文本求值（§36.3 主题 CSS 化）', async () => {
    const { runtime, interpreter } = await boot();
    const root = interpreter.renderPage(runtime.current!, { platform: 'web' });
    expect(root.dataset.pageId).toBe('home-page');
    // 主题以级联样式承载：buildThemeCss 生成亮/暗块，#AARRGGBB→rgba 换格式。
    const css = buildThemeCss(runtime.project, ['theme-light', 'theme-dark']);
    expect(css).toContain('--mf-color-bg-canvas: #F2F1EC');
    expect(css).toContain('--mf-color-glass-surface-light: rgba(255, 255, 255, 0.780)');
    expect(css.split('html[data-theme="dark"]').length).toBeGreaterThan(1);
    expect(css).toContain('--mf-color-bg-canvas: #0A0B0D');
    expect(css).toContain('[data-theme="dark"]');
    const texts = [...root.querySelectorAll('.mf-text')].map((n) => n.textContent);
    expect(texts).toContain('首页');
  });

  it('按钮点击 → 绑定链 → 状态反映（重新渲染后可见）', async () => {
    const { runtime, interpreter } = await boot({
      'mini.increment': (args) => (args.current as number) + 1,
    });
    const render = () => {
      document.body.innerHTML = '';
      document.body.appendChild(interpreter.renderPage(runtime.current!, { platform: 'web' }));
    };
    render();
    const button = document.body.querySelector<HTMLButtonElement>('button.mf-button')!;
    expect(button).not.toBeNull();
    button.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(runtime.state.peek('page', 'count')).toBe(1);
    render();
    const texts = [...document.body.querySelectorAll('.mf-text')].map((n) => n.textContent);
    expect(texts).toContain('1');
  });

  it('语义：Button 原生元素 + 契约 role 落位', async () => {
    const { runtime, interpreter } = await boot();
    const root = interpreter.renderPage(runtime.current!, { platform: 'web' });
    const buttons = root.querySelectorAll('button');
    expect(buttons.length).toBe(2);
  });

  it('reduced 动效条件 → 替代组直出（§36.7）', async () => {
    const { runtime, interpreter } = await boot();
    const root = interpreter.renderPage(runtime.current!, { platform: 'web', motion: 'reduced' });
    const entrances = root.querySelectorAll('.mf-entrance');
    // reduced 下入场类不添加（替代组 duration 0 → 无动画直出）。
    expect(entrances.length).toBe(0);
    expect(runtime.diagnostics.some((d: { code: string }) => d.code === 'mf.motion.alternative-applied')).toBe(true);
  });

  it('未知原语降级 + 诊断（不静默）', async () => {
    const project = miniProject();
    project.pages![0]!.tree.children!.push({ id: 'mystery', type: 'MysteryBox', props: {} });
    const runtime = new MFRuntime({ project, themeProvider: () => 'theme-light' });
    await runtime.start();
    const interpreter = new MFInterpreter(runtime);
    const root = interpreter.renderPage(runtime.current!, { platform: 'web' });
    expect(root.querySelector('[data-mf-type="MysteryBox"]')).not.toBeNull();
    expect(runtime.diagnostics.some((d: { code: string }) => d.code === 'mf.reg.unregistered-ref')).toBe(true);
  });

  it('withViewTransition：无 API 或 reduced 时直调 update', () => {
    let called = 0;
    withViewTransition(() => {
      called += 1;
    });
    expect(called).toBe(1);
  });
});
