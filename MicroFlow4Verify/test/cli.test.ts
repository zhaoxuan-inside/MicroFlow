/// CLI 契约：报告即信封；退出码 0/1/2；--out 落盘；决策字段确定性。
import { describe, expect, it } from 'vitest';
import { readFileSync, existsSync, rmSync } from 'node:fs';
import { resolve } from 'node:path';
import { runVerifyCli } from '../src/cli.ts';

const fixture = (name: string): string => resolve(import.meta.dirname, 'fixtures', name);

describe('runVerifyCli', () => {
  it('pass 脚本：exit 0 + verdict pass + 断言明细', async () => {
    const report = await runVerifyCli(['--script', fixture('login.script.json'), '--model', fixture('demo.project.json'), '--impls', fixture('demo.impls.mjs')]);
    expect(report.exit).toBe(0);
    expect(report.verdict).toBe('pass');
    expect(report.envelope).toBe('microflow-verify-v1');
    expect(report.summary).toEqual({ total: 5, passed: 5, failed: 0 });
  });

  it('fail 脚本（无 impls 时 authenticate 降级 null）：exit 1', async () => {
    const report = await runVerifyCli(['--script', fixture('login.script.json'), '--model', fixture('demo.project.json')]);
    expect(report.exit).toBe(1);
    expect(report.verdict).toBe('fail');
    expect(report.summary.failed).toBeGreaterThan(0);
  });

  it('静态门禁不过：exit 2 + requestFailed + 诊断', async () => {
    const report = await runVerifyCli(['--script', fixture('invalid.script.json'), '--model', fixture('demo.project.json')]);
    expect(report.exit).toBe(2);
    expect((report as unknown as { requestFailed: boolean }).requestFailed).toBe(true);
    const diags = (report as unknown as { diagnostics: { code: string }[] }).diagnostics;
    expect(diags.length).toBeGreaterThan(0);
  });

  it('缺参数 / 未知参数 / 文件不可读：exit 2', async () => {
    expect((await runVerifyCli([])).exit).toBe(2);
    expect((await runVerifyCli(['--script', fixture('login.script.json')])).exit).toBe(2);
    expect((await runVerifyCli(['--wat', 'x', '--script', 'a', '--model', 'b'])).exit).toBe(2);
    expect((await runVerifyCli(['--script', 'nope.json', '--model', fixture('demo.project.json')])).exit).toBe(2);
    expect((await runVerifyCli(['--script', fixture('login.script.json'), '--model', 'nope.json'])).exit).toBe(2);
  });

  it('--out 落盘 + 决策字段确定性（两次运行 assertions 一致）', async () => {
    const out = resolve(import.meta.dirname, 'fixtures', '.out-report.json');
    try {
      const a = await runVerifyCli(['--script', fixture('login.script.json'), '--model', fixture('demo.project.json'), '--impls', fixture('demo.impls.mjs'), '--out', out]);
      expect(existsSync(out)).toBe(true);
      const written = JSON.parse(readFileSync(out, 'utf8')) as { verdict: string };
      expect(written.verdict).toBe('pass');
      const b = await runVerifyCli(['--script', fixture('login.script.json'), '--model', fixture('demo.project.json'), '--impls', fixture('demo.impls.mjs')]);
      // 时钟性字段在 meta；决策字段（verdict/assertions/summary）逐字节一致。
      expect(JSON.stringify({ v: a.verdict, a: a.assertions, s: a.summary })).toBe(JSON.stringify({ v: b.verdict, a: b.assertions, s: b.summary }));
    } finally {
      rmSync(out, { force: true });
    }
  });
});
