/// 校验门禁：合法模型 0 诊断；未知字段/缺必填/坏枚举/坏类型/悬空引用/重复 id/方言不支持逐项挂账。
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { SPCodes } from '../src/diagnostics.js';
import { validateSpecModel, toSpecModel } from '../src/model/validate.js';

const fixture = (name: string): string => resolve(import.meta.dirname, 'fixtures', name);

const validRaw: unknown = JSON.parse(readFileSync(fixture('valid.model.json'), 'utf8'));

function codesOf(diags: { code: string }[]): string[] {
  return diags.map((d) => d.code);
}

describe('validateSpecModel', () => {
  it('合法模型 0 诊断，且产出模型', () => {
    const diags = validateSpecModel(validRaw);
    expect(diags).toEqual([]);
    expect(toSpecModel(validRaw, diags)).toBeDefined();
  });

  it('有 error 诊断时拒绝产出半成品', () => {
    expect(toSpecModel(validRaw, [{ code: SPCodes.unknownField, message: 'x', severity: 'error' }])).toBeUndefined();
    expect(
      toSpecModel(validRaw, [{ code: SPCodes.orphanScenario, message: 'x', severity: 'warning' }]),
    ).toBeDefined();
  });

  it('根非对象拒绝', () => {
    const diags = validateSpecModel([1, 2]);
    expect(codesOf(diags)).toEqual([SPCodes.badType]);
    expect(diags[0]!.path).toBe('$');
  });

  it('未知字段拒绝（根/需求/场景/期望面逐层）', () => {
    const diags = validateSpecModel({
      specVersion: 1,
      project: 'p',
      extra: true,
      requirements: [{ id: 'R-1', title: 't', statement: 's', priority: 'must', status: 'open', owner: 'a' }],
      scenarios: [
        { id: 'S-1', title: 't', kind: 'ui_script', requirementRefs: ['R-1'], expectation: { script: 'a.json', inject: 'js' } },
      ],
    });
    expect(codesOf(diags)).toEqual([SPCodes.unknownField, SPCodes.unknownField, SPCodes.unknownField]);
    expect(diags.map((d) => d.path)).toEqual(['$.extra', 'requirements[0].owner', 'scenarios[0].expectation.inject']);
  });

  it('方言不支持', () => {
    const diags = validateSpecModel({ specVersion: 2, project: 'p', requirements: [], scenarios: [] });
    expect(codesOf(diags)).toContain(SPCodes.dialectUnsupported);
  });

  it('缺必填字段', () => {
    const diags = validateSpecModel({ specVersion: 1, requirements: [], scenarios: [] });
    expect(codesOf(diags)).toEqual([SPCodes.missingRequired]);
    expect(diags[0]!.path).toBe('$.project');
  });

  it('坏枚举', () => {
    const diags = validateSpecModel(validRaw);
    expect(codesOf(diags)).toEqual([]);
    const bad = JSON.parse(readFileSync(fixture('invalid.model.json'), 'utf8'));
    const codes = codesOf(validateSpecModel(bad));
    expect(codes).toContain(SPCodes.badEnum);
    expect(codes).toContain(SPCodes.unknownField);
    expect(codes).toContain(SPCodes.duplicateId);
    expect(codes).toContain(SPCodes.danglingRequirement);
    expect(codes).toContain(SPCodes.missingRequired);
  });

  it('悬空需求引用给出索引定位', () => {
    const bad = JSON.parse(readFileSync(fixture('invalid.model.json'), 'utf8')) as {
      scenarios: { requirementRefs: string[] }[];
    };
    const diags = validateSpecModel(JSON.parse(readFileSync(fixture('invalid.model.json'), 'utf8')));
    const dangling = diags.filter((d) => d.code === SPCodes.danglingRequirement);
    expect(dangling).toHaveLength(1);
    expect(dangling[0]!.path).toBe('scenarios[0].requirementRefs[0]');
    expect(bad.scenarios[0]!.requirementRefs[0]).toBe('R-404');
  });

  it('requirementRefs 空数组合法（待挂接），坏元素类型报错', () => {
    const ok = validateSpecModel({
      specVersion: 1,
      project: 'p',
      requirements: [{ id: 'R-1', title: 't', statement: 's', priority: 'must', status: 'open' }],
      scenarios: [{ id: 'S-1', title: 't', kind: 'manual', requirementRefs: [], expectation: { note: 'n' } }],
    });
    expect(ok).toEqual([]);

    const bad = validateSpecModel({
      specVersion: 1,
      project: 'p',
      requirements: [],
      scenarios: [{ id: 'S-1', title: 't', kind: 'manual', requirementRefs: [''], expectation: { note: 'n' } }],
    });
    expect(codesOf(bad)).toEqual([SPCodes.badType]);
  });

  it('四种期望面各自校验必填', () => {
    const base = { specVersion: 1, project: 'p', requirements: [] as unknown[], scenarios: [] as unknown[] };
    const mk = (kind: string, expectation: Record<string, unknown>) => ({
      ...base,
      scenarios: [{ id: 'S-1', title: 't', kind, requirementRefs: [], expectation }],
    });
    expect(validateSpecModel(mk('backend_run', {})).map((d) => d.code)).toEqual([SPCodes.missingRequired]);
    expect(validateSpecModel(mk('orch_scenario', { scenario: 's' })).map((d) => d.code)).toEqual([SPCodes.missingRequired]);
    expect(validateSpecModel(mk('ui_script', {})).map((d) => d.code)).toEqual([SPCodes.missingRequired]);
    expect(validateSpecModel(mk('manual', {})).map((d) => d.code)).toEqual([SPCodes.missingRequired]);
    expect(validateSpecModel(mk('manual', { note: 'n', verdict: 'ok' })).map((d) => d.code)).toEqual([SPCodes.unknownField]);
  });

  it('载体校验：未知 kind 报错，合法载体通过', () => {
    const diags = validateSpecModel({
      specVersion: 1,
      project: 'p',
      requirements: [],
      scenarios: [
        {
          id: 'S-1',
          title: 't',
          kind: 'manual',
          requirementRefs: [],
          carriers: [{ kind: 'flow', id: 'auth.login' }, { kind: 'weird', id: 'x' }],
          expectation: { note: 'n' },
        },
      ],
    });
    expect(codesOf(diags)).toEqual([SPCodes.badEnum]);
    expect(diags[0]!.path).toBe('scenarios[0].carriers[1].kind');
  });
});
