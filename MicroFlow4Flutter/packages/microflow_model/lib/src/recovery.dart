/// Recovery Contract（frontend-framework-design §16.1）：恢复与迁移规则必须是
/// 显式契约，运行时按契约执行恢复（§22.1）。契约缺失时运行时禁止执行恢复，
/// 进入全新启动并上报诊断。
library;

/// 恢复契约资源（§16.1 Schema 的 Dart 承载）。
class MFRecoveryContract {
  const MFRecoveryContract({
    required this.id,
    this.schemaVersion = '1.0',
    this.snapshotRoute = true,
    this.snapshotParameters = true,
    this.snapshotPageState = true,
    this.snapshotPendingActions = true,
    this.snapshotStateRevision = true,
    this.snapshotVersion = '1.0',
    this.unknownSideEffectsAutoRetry = false,
    this.migrators = const [],
    this.maxAgeSeconds = 86400,
    this.onExpired = 'fresh-start',
  });

  final String id;
  final String schemaVersion;

  // snapshot 组（§16.1）：布尔项声明该类内容是否进入恢复快照。
  // session_state 固定 declared-only：只携带显式声明的会话状态成员。
  final bool snapshotRoute;
  final bool snapshotParameters;
  final bool snapshotPageState;
  final bool snapshotPendingActions;
  final bool snapshotStateRevision;
  final String snapshotVersion;

  /// §16.1 固定为 false：未知结果的副作用不得自动重试（§22.1、基线 27）。
  /// 声明为 true 是静态构建错误（mf.build.recovery-auto-retry）。
  final bool unknownSideEffectsAutoRetry;

  /// 迁移器登记（§22.3 版本迁移纪律）；release 变化时仅按登记的迁移器
  /// 显式迁移，无登记则禁止恢复、全新启动。
  final List<String> migrators;

  final int maxAgeSeconds;

  /// 过期策略（§16.1 示例口径：fresh-start）。
  final String onExpired;
}
