/// 覆盖矩阵：行聚合、summary 计数、矩阵洞诊断、确定性排序、内容寻址摘要。
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { SPCodes } from '../src/diagnostics.js';
import { toSpecModel, validateSpecModel } from '../src/model/validate.js';
import { canonicalJson } from '../src/core/canonical.js';
import { coverage, coverageDiagnostics } from '../src/core/coverage.js';

const fixture = (name: string): string => resolve(import.meta.dirname, 'fixtures', name);

function load(name: string) {
  const raw = JSON.parse(readFileSync(fixture(name), 'utf8'));
  const diags = validateSpecModel(raw);
  expect(diags).toEqual([]);
  return toSpecModel(raw, diags)!;
}

describe('coverage', () => {
  it('valid 模型：全绿 + manualOnly 如实披露', () => {
    const report = coverage(load('valid.model.json'));
    expect(report.summary).toEqual({ requirements: 3, scenarios: 4, covered: 3, uncovered: 0, manualOnly: 1 });
    expect(report.orphans).toEqual([]);
    const r1 = report.rows.find((row) => row.id === 'R-001')!;
    expect(r1.covered).toBe(true);
    expect(r1.manualOnly).toBe(false);
    expect(r1.scenarios.map((s) => s.id)).toEqual(['S-001', 'S-002']);
    expect(r1.carriers.map((c) => c.id)).toEqual(['auth.login', 'verify_password']);
    const r3 = report.rows.find((row) => row.id === 'R-003')!;
    expect(r3.manualOnly).toBe(true);
    expect(codesOf(coverageDiagnostics(report))).toEqual([SPCodes.manualOnlyRequirement]);
  });

  it('矩阵洞：uncovered 需求 + orphan 场景，行按 id 确定性排序', () => {
    const report = coverage(load('holes.model.json'));
    expect(report.rows.map((row) => row.id)).toEqual(['R-100', 'R-101']);
    expect(report.orphans.map((o) => o.id)).toEqual(['S-900']);
    expect(report.summary.uncovered).toBe(1);
    const codes = codesOf(coverageDiagnostics(report));
    expect(codes).toContain(SPCodes.uncoveredRequirement);
    expect(codes).toContain(SPCodes.orphanScenario);
    expect(codes).toContain(SPCodes.manualOnlyRequirement); // R-101 只挂 manual 场景，如实披露
  });

  it('digest 只由内容决定（键序无关）', () => {
    const raw = JSON.parse(readFileSync(fixture('valid.model.json'), 'utf8')) as Record<string, unknown>;
    const reordered = { scenarios: raw['scenarios'], requirements: raw['requirements'], project: raw['project'], specVersion: raw['specVersion'] };
    expect(canonicalJson(reordered)).toBe(canonicalJson(raw));
    expect(coverage(toSpecModel(reordered, [])!).digest).toBe(coverage(load('valid.model.json')).digest);
  });
});

function codesOf(diags: { code: string }[]): string[] {
  return diags.map((d) => d.code);
}
