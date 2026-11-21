/// 统一诊断注册表：`vrf.<area>.<name>` 诊断码，单一来源原则。
/// 发出未登记的码是实现缺陷（守卫测试固定格式与唯一性，同 4Web §41.3 纪律）。

export type Severity = 'error' | 'warning' | 'info';

export interface VrfDiag {
  code: string;
  message: string;
  severity: Severity;
  /** 诊断定位：`steps[3].node` 这样的点路径。 */
  path?: string;
}

export function vrfDiag(
  code: string,
  message: string,
  options?: { severity?: Severity; path?: string },
): VrfDiag {
  return { code, message, severity: options?.severity ?? 'error', path: options?.path };
}

/** 诊断码（单一来源）：schema=脚本结构面 / ref=锚点引用面 / op=步骤能力面。 */
export const VRFCodes = {
  dialectUnsupported: 'vrf.schema.dialect-unsupported',
  missingRequired: 'vrf.schema.missing-required',
  badType: 'vrf.schema.bad-type',
  badEnum: 'vrf.schema.bad-enum',
  unknownField: 'vrf.schema.unknown-field',

  unknownPage: 'vrf.ref.unknown-page',
  unknownNode: 'vrf.ref.unknown-node',
  unregisteredNodeType: 'vrf.ref.unregistered-node-type',
  unknownEvent: 'vrf.ref.unknown-event',
  unknownStandardEvent: 'vrf.ref.unknown-standard-event',

  opUnimplemented: 'vrf.op.unimplemented',
} as const;

export function isVrfCode(code: string): boolean {
  return Object.values(VRFCodes).includes(code as (typeof VRFCodes)[keyof typeof VRFCodes]);
}
