/// 统一诊断注册表（§41）：与 Flutter 实现（microflow_model/diagnostics.dart）
/// 逐一对应的 `mf.<area>.<name>` 诊断码。发出未登记的码是实现缺陷（§41.3）。

export type Severity = 'error' | 'warning' | 'info';
export type Stage = 'static' | 'runtime';

export interface MFDiag {
  code: string;
  message: string;
  severity: Severity;
  stage: Stage;
}

export function mfDiag(
  code: string,
  message: string,
  severity: Severity = 'error',
  stage: Stage = 'static',
): MFDiag {
  return { code, message, severity, stage };
}

/** 与 Dart MFCodes 一一对应的诊断码（单一来源原则，§41.3）。 */
export const MFCodes = {
  unknownField: 'mf.schema.unknown-field',
  schemaDialectUnsupported: 'mf.schema.dialect-unsupported',
  schemaInlineLogic: 'mf.schema.inline-logic',
  schemaTemplateParamInvalid: 'mf.schema.template-param-invalid',

  regUnregisteredRef: 'mf.reg.unregistered-ref',
  regContractMismatch: 'mf.reg.contract-mismatch',
  regUnregisteredImpl: 'mf.reg.unregistered-impl',
  regDeprecated: 'mf.reg.deprecated',

  layoutUnsatisfiable: 'mf.layout.unsatisfiable',
  layoutOverflow: 'mf.layout.overflow',
  layoutAmbiguousScheme: 'mf.layout.ambiguous-scheme',
  layoutDegraded: 'mf.layout.degraded',
  layoutUndeclaredDegradation: 'mf.layout.undeclared-degradation',

  styleLiteralInSheet: 'mf.style.literal-in-sheet',
  styleCycle: 'mf.style.cycle',
  styleVariantAmbiguous: 'mf.style.variant-ambiguous',
  styleFaceUndeclared: 'mf.style.face-undeclared',
  themeIncomplete: 'mf.theme.incomplete',

  motionSurfaceUndeclared: 'mf.motion.surface-undeclared',
  motionTokenInvalid: 'mf.motion.token-invalid',
  motionAlternativeDangling: 'mf.motion.alternative-dangling',
  motionAlternativeApplied: 'mf.motion.alternative-applied',

  refDangling: 'mf.ref.dangling',
  bindingEventUnknown: 'mf.binding.event-unknown',
  bindingNoConcurrency: 'mf.binding.no-concurrency',
  bindingCycle: 'mf.binding.cycle',
  bindingResultUnknown: 'mf.binding.result-unknown',

  interactionUnknownMember: 'mf.interaction.unknown-member',
  interactionErrorPropagation: 'mf.interaction.error-propagation',

  navUnknownTarget: 'mf.nav.unknown-target',
  navIsolatedPage: 'mf.nav.isolated-page',
  navEntryMissing: 'mf.nav.entry-missing',
  routeDuplicate: 'mf.route.duplicate',

  stateWritebackDenied: 'mf.state.writeback-denied',
  stateGhostDependency: 'mf.state.ghost-dependency',
  stateProvidedInvalid: 'mf.state.provided-invalid',

  dataOutputInvalid: 'mf.data.output-invalid',
  dataTimeout: 'mf.data.timeout',
  dataFactDuplicate: 'mf.data.fact-duplicate',

  i18nMissingTranslation: 'mf.i18n.missing-translation',
  i18nChannelConflict: 'mf.i18n.channel-conflict',

  teleManualStandardEvent: 'mf.tele.manual-standard-event',
  teleQueueOverflow: 'mf.tele.queue-overflow',
  teleSchemaInvalid: 'mf.tele.schema-invalid',
  teleAnnotationInvalid: 'mf.tele.annotation-invalid',
  teleTraceRefMissing: 'mf.tele.trace-ref-missing',

  buildRecoveryAutoRetry: 'mf.build.recovery-auto-retry',
  stateSnapshotVersionMismatch: 'mf.state.snapshot-version-mismatch',
  stateSnapshotExpired: 'mf.state.snapshot-expired',
  stateReleaseMigrationMissing: 'mf.state.release-migration-missing',

  regFindingInvalid: 'mf.reg.finding-invalid',
  capUnavailable: 'mf.cap.unavailable',
  debugUnauthorized: 'mf.debug.unauthorized',
  expAssignmentIncompatible: 'mf.exp.assignment-incompatible',
  expVariantOutOfScope: 'mf.exp.variant-out-of-scope',
} as const;

/** 标准运营事件族（§24.7 零埋点）：业务手工上报是静态错误。 */
export const MFStandardEvents = {
  pageViewed: 'ops.page.viewed',
  pageLeft: 'ops.page.left',
  featureUsed: 'ops.feature.used',
} as const;
