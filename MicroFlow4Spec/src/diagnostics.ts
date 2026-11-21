/// 统一诊断注册表：`spec.<area>.<name>` 诊断码，单一来源原则。
/// 发出未登记的码是实现缺陷（与 4Web §41.3 同纪律，守卫测试固定格式与唯一性）。

export type Severity = 'error' | 'warning' | 'info';

export interface SpecDiag {
  code: string;
  message: string;
  severity: Severity;
  /** 诊断定位：`requirements[3].priority` 这样的点路径。 */
  path?: string;
}

export function specDiag(
  code: string,
  message: string,
  options?: { severity?: Severity; path?: string },
): SpecDiag {
  return { code, message, severity: options?.severity ?? 'error', path: options?.path };
}

/** 诊断码（单一来源）：schema=结构面 / ref=引用面 / coverage=矩阵面 / verify=证据面。 */
export const SPCodes = {
  dialectUnsupported: 'spec.schema.dialect-unsupported',
  missingRequired: 'spec.schema.missing-required',
  badType: 'spec.schema.bad-type',
  badEnum: 'spec.schema.bad-enum',
  unknownField: 'spec.schema.unknown-field',

  duplicateId: 'spec.ref.duplicate-id',
  danglingRequirement: 'spec.ref.dangling-requirement',

  uncoveredRequirement: 'spec.coverage.uncovered-requirement',
  orphanScenario: 'spec.coverage.orphan-scenario',
  manualOnlyRequirement: 'spec.coverage.manual-only-requirement',

  badEnvelope: 'spec.verify.bad-envelope',
  badReport: 'spec.verify.bad-report',
  unmatchedReport: 'spec.verify.unmatched-report',
  failedScenario: 'spec.verify.failed-scenario',
  pendingScenario: 'spec.verify.pending-scenario',
} as const;

export function isSpecCode(code: string): boolean {
  return Object.values(SPCodes).includes(code as (typeof SPCodes)[keyof typeof SPCodes]);
}
