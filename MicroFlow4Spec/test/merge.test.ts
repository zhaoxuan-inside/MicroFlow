/// 证据合并：对号入座、pending/fail 语义、坏信封/坏报告拒绝、自证报告（failed>0 却 pass）拒绝。
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { SPCodes } from '../src/diagnostics.js';
import { toSpecModel, validateSpecModel } from '../src/model/validate.js';
import { mergeVerify } from '../src/core/merge.js';

const fixture = (name: string): string => resolve(import.meta.dirname, 'fixtures', name);

function load(name: string) {
  const raw = JSON.parse(readFileSync(fixture(name), 'utf8'));
  const diags = validateSpecModel(raw);
  expect(diags).toEqual([]);
  return toSpecModel(raw, diags)!;
}

function report(overrides: Record<string, unknown>): Record<string, unknown> {
  return {
    envelope: 'microflow-verify-v1',
    script: 'verify/login.json',
    verdict: 'pass',
    summary: { total: 2, passed: 2, failed: 0 },
    ...overrides,
  };
}

describe('mergeVerify', () => {
  it('报告对号入座：ui_script 场景获得 pass 证据', () => {
    const result = mergeVerify(load('valid.model.json'), [JSON.parse(readFileSync(fixture('login-report.json'), 'utf8'))]);
    const evidence = Object.fromEntries(result.evidence.map((e) => [e.scenarioId, e]));
    expect(evidence['S-002']!.verdict).toBe('pass');
    expect(evidence['S-002']!.reportDigest).toMatch(/^sha256:[0-9a-f]{64}$/);
    // 非 ui_script 场景不参与本合并面（边界：backend_run/orch_scenario 证据属后续切片）
    expect(evidence['S-001']).toBeUndefined();
    expect(evidence['S-003']).toBeUndefined();
    const blocking = result.diagnostics.filter((d) => d.severity === 'error');
    expect(blocking).toEqual([]);
  });

  it('缺报告 → pending；fail 报告 → failed-scenario error', () => {
    const noReport = mergeVerify(load('valid.model.json'), []);
    expect(noReport.evidence.find((e) => e.scenarioId === 'S-002')!.verdict).toBe('pending');
    expect(codes(noReport.diagnostics)).toContain(SPCodes.pendingScenario);

    const failReport = mergeVerify(load('valid.model.json'), [report({ verdict: 'fail', summary: { total: 2, passed: 1, failed: 1 } })]);
    expect(failReport.evidence.find((e) => e.scenarioId === 'S-002')!.verdict).toBe('fail');
    expect(codes(failReport.diagnostics)).toContain(SPCodes.failedScenario);
  });

  it('未匹配报告 → warning 不拦截；坏信封 → error', () => {
    const unmatched = mergeVerify(load('valid.model.json'), [report({ script: 'verify/ghost.json' })]);
    expect(codes(unmatched.diagnostics)).toEqual([SPCodes.unmatchedReport, SPCodes.pendingScenario]);

    const bad = mergeVerify(load('valid.model.json'), [{ envelope: 'other-v1' }]);
    expect(codes(bad.diagnostics)).toEqual([SPCodes.badEnvelope, SPCodes.pendingScenario]);
  });

  it('自证报告拒绝：failed>0 却 verdict=pass', () => {
    const lying = mergeVerify(load('valid.model.json'), [report({ summary: { total: 2, passed: 2, failed: 1 } })]);
    expect(codes(lying.diagnostics)).toEqual([SPCodes.badReport, SPCodes.pendingScenario]);
  });
});

function codes(diags: { code: string }[]): string[] {
  return diags.map((d) => d.code);
}
