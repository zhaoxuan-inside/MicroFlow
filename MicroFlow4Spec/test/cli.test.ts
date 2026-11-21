/// CLI 契约：统一信封、退出码 0/1/2、确定性输出、未知命令拒绝。
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runSpec } from '../src/cli.js';

const fixture = (name: string): string => resolve(import.meta.dirname, 'fixtures', name);

describe('runSpec', () => {
  it('check：合法模型 exit 0 + 摘要；非法模型 exit 1 + 诊断', () => {
    const ok = runSpec(['check', fixture('valid.model.json')]);
    expect(ok.exit).toBe(0);
    expect(ok.ok).toBe(true);
    expect(ok.envelope).toBe('microflow-spec-v1');
    expect(ok.command).toBe('check');
    const spec = ok.spec as { project: string; digest: string };
    expect(spec.project).toBe('demo-product');
    expect(spec.digest).toMatch(/^sha256:[0-9a-f]{64}$/);

    const bad = runSpec(['check', fixture('invalid.model.json')]);
    expect(bad.exit).toBe(1);
    expect((bad.diagnostics as unknown[]).length).toBeGreaterThan(0);
  });

  it('coverage：全绿 exit 0；矩阵洞 exit 1', () => {
    expect(runSpec(['coverage', fixture('valid.model.json')]).exit).toBe(0);
    const holes = runSpec(['coverage', fixture('holes.model.json')]);
    expect(holes.exit).toBe(1);
    expect(holes.ok).toBe(false);
    expect((holes.summary as { uncovered: number }).uncovered).toBe(1);
  });

  it('verify：ui_script 证据齐全 exit 0；缺证据 exit 1', () => {
    // valid.model.json 唯一的 ui_script 场景是 S-002（verify/login.json）
    const full = runSpec(['verify', fixture('valid.model.json'), fixture('login-report.json')]);
    expect(full.exit).toBe(0);
    expect(full.ok).toBe(true);
    const evidence = full.evidence as { scenarioId: string; verdict: string }[];
    expect(evidence.find((e) => e.scenarioId === 'S-002')!.verdict).toBe('pass');
    expect(full.diagnostics as unknown[]).toEqual([]);

    const missing = runSpec(['verify', fixture('valid.model.json')]);
    expect(missing.exit).toBe(1);
    expect((missing.evidence as { verdict: string }[]).some((e) => e.verdict === 'pending')).toBe(true);
  });

  it('diff：结构差异与摘要，exit 恒 0（信息性命令）', () => {
    const diff = runSpec(['diff', fixture('holes.model.json'), fixture('valid.model.json')]);
    expect(diff.exit).toBe(0);
    const body = diff.diff as { requirements: { added: string[]; removed: string[] }; scenarios: { added: string[]; removed: string[] } };
    expect(body.requirements.added).toEqual(['R-001', 'R-002', 'R-003']);
    expect(body.requirements.removed).toEqual(['R-100', 'R-101']);
    expect(body.scenarios.added).toEqual(['S-001', 'S-002', 'S-003', 'S-004']);
    expect(body.scenarios.removed).toEqual(['S-800', 'S-900']);
  });

  it('请求失败：无法解析的模型 exit 2；未知命令 exit 2；参数缺失 exit 2', () => {
    expect(runSpec(['check', fixture('broken.model.json')]).exit).toBe(2);
    expect(runSpec(['nope', 'x']).exit).toBe(2);
    expect(runSpec(['check']).exit).toBe(2);
    expect(runSpec(['verify', fixture('valid.model.json'), fixture('broken.model.json')]).exit).toBe(2);
  });

  it('确定性输出：同输入两次运行字节一致', () => {
    const a = JSON.stringify(runSpec(['coverage', fixture('holes.model.json')]));
    const b = JSON.stringify(runSpec(['coverage', fixture('holes.model.json')]));
    expect(a).toBe(b);
    // 覆盖 fixture 读取（防未使用告警的诚实方式）：broken fixture 存在且为非法 JSON
    expect(() => JSON.parse(readFileSync(fixture('broken.model.json'), 'utf8'))).toThrow();
  });
});
