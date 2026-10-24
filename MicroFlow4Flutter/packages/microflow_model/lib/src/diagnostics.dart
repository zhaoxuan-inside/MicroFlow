/// Unified diagnostic registry (frontend-framework-design §41).
///
/// Every static error and runtime diagnostic emitted by any MicroFlow
/// implementation uses a registered `mf.<area>.<name>` code. Emitting an
/// unregistered code is an implementation defect (§41.3).
library;

class MFDiag {
  const MFDiag(this.code, this.message, {this.severity = Severity.error, this.stage = Stage.static_});

  final String code;
  final String message;
  final Severity severity;
  final Stage stage;

  @override
  String toString() => '[$code] $message';
}

enum Severity { error, warning, info }

enum Stage { static_, runtime }

/// Registry of diagnostic codes emitted by the Flutter implementation.
/// Each code's meaning is fixed here and must not be reused (§41.3).
abstract final class MFCodes {
  static const unknownField = 'mf.schema.unknown-field';
  static const schemaDialectUnsupported = 'mf.schema.dialect-unsupported';
  static const schemaInlineLogic = 'mf.schema.inline-logic';
  static const schemaTemplateParamInvalid = 'mf.schema.template-param-invalid';

  // Registration (§23).
  static const regUnregisteredRef = 'mf.reg.unregistered-ref';
  static const regContractMismatch = 'mf.reg.contract-mismatch';
  static const regUnregisteredImpl = 'mf.reg.unregistered-impl';
  static const regDeprecated = 'mf.reg.deprecated';

  // Layout (§7).
  static const layoutUnsatisfiable = 'mf.layout.unsatisfiable';
  static const layoutOverflow = 'mf.layout.overflow';
  static const layoutAmbiguousScheme = 'mf.layout.ambiguous-scheme';
  static const layoutDegraded = 'mf.layout.degraded';
  static const layoutUndeclaredDegradation = 'mf.layout.undeclared-degradation';

  // Style / theme (§36).
  static const styleLiteralInSheet = 'mf.style.literal-in-sheet';
  static const styleCycle = 'mf.style.cycle';
  static const styleVariantAmbiguous = 'mf.style.variant-ambiguous';
  static const styleFaceUndeclared = 'mf.style.face-undeclared';
  static const themeIncomplete = 'mf.theme.incomplete';

  // Reference / binding (§4.3, §39).
  static const refDangling = 'mf.ref.dangling';
  static const bindingEventUnknown = 'mf.binding.event-unknown';
  static const bindingNoConcurrency = 'mf.binding.no-concurrency';
  static const bindingCycle = 'mf.binding.cycle';
  static const bindingResultUnknown = 'mf.binding.result-unknown';

  // Interaction / expression (§37).
  static const interactionUnknownMember = 'mf.interaction.unknown-member';
  static const interactionErrorPropagation = 'mf.interaction.error-propagation';

  // Route / navigation (§9).
  static const navUnknownTarget = 'mf.nav.unknown-target';
  static const navIsolatedPage = 'mf.nav.isolated-page';
  static const navEntryMissing = 'mf.nav.entry-missing';
  static const routeDuplicate = 'mf.route.duplicate';

  // State / info contract (§2.8, §11).
  static const stateWritebackDenied = 'mf.state.writeback-denied';
  static const stateGhostDependency = 'mf.state.ghost-dependency';
  static const stateProvidedInvalid = 'mf.state.provided-invalid';

  // Data (§40).
  static const dataOutputInvalid = 'mf.data.output-invalid';
  static const dataTimeout = 'mf.data.timeout';
  static const dataFactDuplicate = 'mf.data.fact-duplicate';

  // i18n (§42).
  static const i18nMissingTranslation = 'mf.i18n.missing-translation';
  static const i18nChannelConflict = 'mf.i18n.channel-conflict';

  // Telemetry (§24).
  static const teleManualStandardEvent = 'mf.tele.manual-standard-event';
  static const teleQueueOverflow = 'mf.tele.queue-overflow';
  static const teleSchemaInvalid = 'mf.tele.schema-invalid';
  static const teleAnnotationInvalid = 'mf.tele.annotation-invalid';
  static const teleTraceRefMissing = 'mf.tele.trace-ref-missing';

  // Recovery（§16.1、§22.1；诊断码归属 §41.1 固定区域）。
  static const buildRecoveryAutoRetry = 'mf.build.recovery-auto-retry';
  static const stateSnapshotVersionMismatch = 'mf.state.snapshot-version-mismatch';
  static const stateSnapshotExpired = 'mf.state.snapshot-expired';
  static const stateReleaseMigrationMissing = 'mf.state.release-migration-missing';

  // findings 回流（§43.3）。
  static const regFindingInvalid = 'mf.reg.finding-invalid';

  // Capability (§17.1, §22.1).
  static const capUnavailable = 'mf.cap.unavailable';

  // Debug / experiment.
  static const debugUnauthorized = 'mf.debug.unauthorized';
  static const expAssignmentIncompatible = 'mf.exp.assignment-incompatible';
  static const expVariantOutOfScope = 'mf.exp.variant-out-of-scope';
}

/// Diagnostic code registry resource (§41.2): code -> registered entry.
final Map<String, MFDiag> mfDiagnosticRegistry = _buildRegistry();

Map<String, MFDiag> _buildRegistry() {
  final list = <MFDiag>[
    const MFDiag(MFCodes.unknownField, '资源包含未登记字段'),
    const MFDiag(MFCodes.schemaDialectUnsupported, 'manifest 类型方言版本不受支持（§4.6、基线 14）'),
    const MFDiag(MFCodes.schemaInlineLogic, '结构树内联可执行逻辑（§2.9 三平面分离、基线 31）'),
    const MFDiag(MFCodes.regUnregisteredRef, '引用了未注册资源（§2.7）'),
    const MFDiag(MFCodes.regContractMismatch, '实现与注册契约不一致（§23.3）'),
    const MFDiag(MFCodes.regUnregisteredImpl, '实现未经声明入口到达（§23.3）'),
    const MFDiag(MFCodes.regDeprecated, '资源已废弃，应使用声明的替代资源（§23.6）', severity: Severity.warning),
    const MFDiag(MFCodes.refDangling, '悬空引用（§4.3）'),
    const MFDiag(MFCodes.bindingEventUnknown, '绑定事件目标不存在或契约未声明'),
    const MFDiag(MFCodes.bindingNoConcurrency, '绑定未声明并发策略，拒绝重复触发（§39.1、基线 26）'),
    const MFDiag(MFCodes.bindingCycle, '绑定循环缺少终止条件'),
    const MFDiag(MFCodes.bindingResultUnknown, '引用了不存在的动作结果'),
    const MFDiag(MFCodes.interactionUnknownMember, '表达式引用未声明的成员'),
    const MFDiag(MFCodes.interactionErrorPropagation, '动作链错误传播未声明'),
    const MFDiag(MFCodes.navUnknownTarget, '导航目标在导航图中不存在'),
    const MFDiag(MFCodes.navIsolatedPage, '存在不可达的孤立页面'),
    const MFDiag(MFCodes.navEntryMissing, '入口页面在导航图中缺失'),
    const MFDiag(MFCodes.routeDuplicate, '页面 id 或路由重复（§9 路由唯一）'),
    const MFDiag(MFCodes.schemaTemplateParamInvalid, '模板实例化参数缺失或未声明（§2.7）'),
    const MFDiag(MFCodes.stateWritebackDenied, '运行数据回写项目模型被拒绝'),
    const MFDiag(MFCodes.stateGhostDependency, 'consumes 不可解析到上游 provides（幽灵依赖）'),
    const MFDiag(MFCodes.stateProvidedInvalid, 'provides 形状不合法'),
    const MFDiag(MFCodes.dataOutputInvalid, '适配器输出不符合 output Schema'),
    const MFDiag(MFCodes.dataTimeout, '适配器调用超时（不当作未执行）'),
    const MFDiag(MFCodes.dataFactDuplicate, 'Business Fact 重复提交，按去重身份幂等返回既有记录（§24.1）',
        severity: Severity.info, stage: Stage.runtime),
    const MFDiag(MFCodes.i18nMissingTranslation, '缺失翻译，按回退链解析'),
    const MFDiag(MFCodes.i18nChannelConflict, '同一内容位同时声明 i18n 与内容资产'),
    const MFDiag(MFCodes.layoutUnsatisfiable, '不可满足的布局约束（§7.3）'),
    const MFDiag(MFCodes.layoutOverflow, '主轴内容溢出，记录溢出诊断'),
    const MFDiag(MFCodes.layoutAmbiguousScheme, '条件布局存在重复条件且模糊命中（§7.4）'),
    const MFDiag(MFCodes.layoutDegraded, '目标平台不支持该布局能力，按声明降级执行（基线 21）'),
    const MFDiag(MFCodes.layoutUndeclaredDegradation, '平台能力不足且未声明降级，构建拒绝'),
    const MFDiag(MFCodes.styleLiteralInSheet, '样式片使用字面量而非 token 引用（§36.4）'),
    const MFDiag(MFCodes.styleCycle, '样式片承接链循环'),
    const MFDiag(MFCodes.styleVariantAmbiguous, '样式片同选择器多 set 且顺序未声明'),
    const MFDiag(MFCodes.styleFaceUndeclared, '节点引用了未声明的样式面'),
    const MFDiag(MFCodes.themeIncomplete, '主题对被引用 token 解析不完整（§36.3）'),
    const MFDiag(MFCodes.teleManualStandardEvent, '业务代码手工上报标准事件族'),
    const MFDiag(MFCodes.teleQueueOverflow, '采集队列满载丢弃'),
    const MFDiag(MFCodes.teleSchemaInvalid, '事件信封 Schema 校验失败（§24.2）'),
    const MFDiag(MFCodes.teleAnnotationInvalid, '采集注记不合法：事件未登记、隐私分类或采样策略非法（§24.7）'),
    const MFDiag(MFCodes.teleTraceRefMissing, '声明了追踪传播但外部执行侧未返回运行引用（§24.8）',
        severity: Severity.info, stage: Stage.runtime),
    const MFDiag(MFCodes.buildRecoveryAutoRetry, 'Recovery 契约声明 auto_retry=true，违反 §16.1 固定 false（基线 27）'),
    const MFDiag(MFCodes.stateSnapshotVersionMismatch, '恢复快照 schema 版本不匹配，进入错误边界（§16.1）',
        stage: Stage.runtime),
    const MFDiag(MFCodes.stateSnapshotExpired, '恢复快照超过 max_age_s，按声明全新启动（§16.1）',
        severity: Severity.warning, stage: Stage.runtime),
    const MFDiag(MFCodes.stateReleaseMigrationMissing, 'release 变化且无显式迁移器登记，禁止恢复、全新启动（§16.1）',
        severity: Severity.warning, stage: Stage.runtime),
    const MFDiag(MFCodes.regFindingInvalid, 'findings 注记不合法：类型未知、重复登记或 regression-key 未绑定校验（§43.3）'),
    const MFDiag(MFCodes.capUnavailable, '宿主能力不可用，按声明降级'),
    const MFDiag(MFCodes.debugUnauthorized, 'Debug 会话未授予对应权限'),
    const MFDiag(MFCodes.expAssignmentIncompatible, '实验分配与平台/版本/有效期不兼容'),
    const MFDiag(MFCodes.expVariantOutOfScope, '变体改写面未登记入受控交叉清单（§2.9、基线 32）'),
  ];
  return {for (final d in list) d.code: d};
}
