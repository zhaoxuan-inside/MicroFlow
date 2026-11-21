/// diff：增删改按 id 对齐，确定性排序；digest 反映内容。
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { toSpecModel, validateSpecModel } from '../src/model/validate.js';
import { diffSpec } from '../src/core/diff.js';

const fixture = (name: string): string => resolve(import.meta.dirname, 'fixtures', name);

function load(name: string) {
  const raw = JSON.parse(readFileSync(fixture(name), 'utf8'));
  const diags = validateSpecModel(raw);
  expect(diags).toEqual([]);
  return toSpecModel(raw, diags)!;
}

describe('diffSpec', () => {
  it('同模型 diff 全空且摘要相等', () => {
    const diff = diffSpec(load('valid.model.json'), load('valid.model.json'));
    expect(diff.requirements).toEqual({ added: [], removed: [], changed: [] });
    expect(diff.scenarios).toEqual({ added: [], removed: [], changed: [] });
    expect(diff.digestOld).toBe(diff.digestNew);
  });

  it('新增/删除/修改逐项报告，数组按 id 排序', () => {
    const oldModel = load('holes.model.json');
    const newRaw = JSON.parse(readFileSync(fixture('holes.model.json'), 'utf8')) as {
      requirements: { id: string; statement: string }[];
    };
    newRaw.requirements = [
      { ...newRaw.requirements[0]!, id: 'R-099', statement: '向前插入' },
      { ...newRaw.requirements[1]!, statement: '改了描述' },
    ];
    const newModel = toSpecModel(newRaw, [])!;
    const diff = diffSpec(oldModel, newModel);
    expect(diff.requirements.added).toEqual(['R-099']);
    expect(diff.requirements.removed).toEqual(['R-100']);
    expect(diff.requirements.changed).toEqual(['R-101']);
    expect(diff.digestOld).not.toBe(diff.digestNew);
  });
});
