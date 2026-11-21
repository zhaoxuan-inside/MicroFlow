/// 守卫测试：诊断码单一来源——格式、唯一性、isVrfCode 一致性。
import { describe, expect, it } from 'vitest';
import { isVrfCode, VRFCodes } from '../src/diagnostics.ts';

describe('诊断注册表守卫', () => {
  const values = Object.values(VRFCodes);

  it('码全部唯一', () => {
    expect(new Set(values).size).toBe(values.length);
  });

  it('码全部符合 vrf.<area>.<name> 格式', () => {
    for (const code of values) {
      expect(code).toMatch(/^vrf\.(schema|ref|op)\.[a-z0-9-]+$/);
    }
  });

  it('isVrfCode 对登记码肯定、对未知码否定', () => {
    expect(isVrfCode(VRFCodes.unknownField)).toBe(true);
    expect(isVrfCode('vrf.schema.not-registered')).toBe(false);
  });
});
