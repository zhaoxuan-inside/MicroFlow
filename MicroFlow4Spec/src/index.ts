/// MicroFlow4Spec 公共 API 面：类型、门禁、矩阵、证据合并、diff、CLI。
export * from './diagnostics.ts';
export * from './model/types.ts';
export { validateSpecModel, toSpecModel } from './model/validate.ts';
export { canonicalJson, canonicalDigest, sha256Hex } from './core/canonical.ts';
export { coverage, coverageDiagnostics, type CoverageReport, type CoverageRow } from './core/coverage.ts';
export {
  mergeVerify,
  type VerifyReport,
  type ScenarioEvidence,
  type EvidenceVerdict,
  type MergeResult,
} from './core/merge.ts';
export { diffSpec, type SpecDiff, type FamilyDiff } from './core/diff.ts';
export { runSpec } from './cli.ts';
