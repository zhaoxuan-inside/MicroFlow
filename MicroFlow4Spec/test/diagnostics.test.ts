/// 守卫测试：诊断码单一来源——格式、唯一性、isSpecCode 一致性。
import { describe, expect, it } from 'vitest';
import { isSpecCode, SPCodes } from '../src/diagnostics.js';

describe('诊断注册表守卫', () => {
  const values = Object.values(SPCodes);

  it('码全部唯一', () => {
    expect(new Set(values).size).toBe(values.length);
  });

  it('码全部符合 spec.<area>.<name> 格式', () => {
    for (const code of values) {
      expect(code).toMatch(/^spec\.(schema|ref|coverage|verify)\.[a-z0-9-]+$/);
    }
  });

  it('isSpecCode 对登记码肯定、对未知码否定', () => {
    expect(isSpecCode(SPCodes.unknownField)).toBe(true);
    expect(isSpecCode('spec.schema.not-registered')).toBe(false);
  });
});
