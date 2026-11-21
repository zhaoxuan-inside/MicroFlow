/// web 面端到端：真实 MFRuntime + 真实 fixture 项目 + 声明式脚本 → microflow-verify-v1。
/// 这是"在真实渲染面执行"的最小证据：绑定链/适配器/导航/零埋点事件全走 4Web 运行时。
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createWebSurface } from '../src/surface/web.ts';
import { runVerifyScript } from '../src/runner.ts';
import { validateScript, toVerifyScript } from '../src/script/validate.ts';
import { extractFacts } from '../src/script/facts.ts';
import { MFValidator } from '../../MicroFlow4Web/src/validator/validator.ts';

const fixture = (name: string): string => resolve(import.meta.dirname, 'fixtures', name);

const project = JSON.parse(readFileSync(fixture('demo.project.json'), 'utf8'));
const script = JSON.parse(readFileSync(fixture('login.script.json'), 'utf8'));

describe('web 面（MFRuntime 适配）', () => {
  it('fixture 项目过 4Web 静态门禁（无 error）', () => {
    const errors = new MFValidator(project).validate().diags.filter((d) => d.severity === 'error');
    expect(errors).toEqual([]);
  });

  it('登录脚本端到端：fill→adapter→navigation→零埋点事件→back 全过', async () => {
    const diags = validateScript(script, extractFacts(project)!, new Set(['ops.page.viewed', 'ops.page.left', 'ops.feature.used']));
    expect(diags).toEqual([]);
    const surface = createWebSurface({
      project,
      impls: { 'demo.authenticate': (args) => (args['username'] === 'alice' ? 'alice' : null) },
    });
    const report = await runVerifyScript({ script: toVerifyScript(script, diags)!, surface, scriptPath: 'login.script.json', surfaceName: 'web' });
    expect(report.verdict).toBe('pass');
    expect(report.exit).toBe(0);
    expect(report.summary).toEqual({ total: 5, passed: 5, failed: 0 });
    expect(report.meta.surfaceDiagnostics).toEqual([]);
  });

  it('认证失败路径：param.user 为 null，expect_binding fail + verdict fail', async () => {
    const failingScript = {
      scriptVersion: 1,
      title: '错误凭据应停留登录页',
      steps: [
        { op: 'fill', node: 'username', value: 'mallory' },
        { op: 'tap', node: 'submit', event: 'press' },
        { op: 'expect_route', page: 'home-page' },
      ],
    };
    const surface = createWebSurface({
      project,
      impls: { 'demo.authenticate': (args) => (args['username'] === 'alice' ? 'alice' : null) },
    });
    const report = await runVerifyScript({ script: failingScript as never, surface, scriptPath: 'failing.script.json', surfaceName: 'web' });
    expect(report.verdict).toBe('fail');
    expect(report.assertions.find((a) => a.op === 'expect_route')!.verdict).toBe('fail');
    expect((report.assertions.find((a) => a.op === 'expect_route')!.detail as { expected: string; actual: string }).expected).toBe('home-page');
    expect((report.assertions.find((a) => a.op === 'expect_route')!.detail as { expected: string; actual: string }).actual).toBe('login-page');
  });
});
