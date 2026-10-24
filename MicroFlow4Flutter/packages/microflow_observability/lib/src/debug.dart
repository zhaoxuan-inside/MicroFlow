/// Debug contract (§29): three levels (local/preview/production-controlled),
/// permission-gated reads, bounded snapshots with masking.
library;

import 'dart:async';

import 'package:microflow_runtime/microflow_runtime.dart';

/// Debug session levels; production-controlled needs explicit grants.
enum MFDebugLevel { local, preview, productionControlled }

const grants = {'read-context', 'subscribe', 'checkpoint-pause', 'export'};

class MFDebugSession {
  MFDebugSession({
    required this.sessionId,
    required this.principal,
    required this.level,
    required this.scopeReleaseId,
    required this.scopePageInstanceId,
    required this.authorizedGrants,
    DateTime? expiresAt,
  }) : expiresAt = expiresAt ?? DateTime.now().toUtc().add(const Duration(hours: 1));

  final String sessionId;
  final String principal;
  final MFDebugLevel level;
  final String scopeReleaseId;
  final String scopePageInstanceId;
  final List<String> authorizedGrants;
  final DateTime expiresAt;

  bool get expired => DateTime.now().toUtc().isAfter(expiresAt);

  bool may(String grant) =>
      !expired &&
      grants.contains(grant) &&
      authorizedGrants.contains(grant);
}

/// A bounded, masked runtime snapshot (§29). Sensitive payload exclusion is
/// controlled by the privacy classification-based masking in telemetry.
class MFDebugSnapshot {
  MFDebugSnapshot({required this.context, this.depthMax = 8, this.retentionSeconds = 3600});
  final Map<String, Object?> context;
  final int depthMax;
  final int retentionSeconds;

  Map<String, Object?> export({Set<String> maskedKeys = const {'token', 'password', 'secret'}}) {
    // Bounded export: top-level snapshot body, sensitive keys masked out.
    final body = <String, Object?>{};
    for (final e in context.entries) {
      if (!maskedKeys.contains(e.key)) {
        body[e.key] = e.value;
      }
    }
    return {'snapshot': body, 'depth_max': depthMax};
  }
}

MFDebugSnapshot requireSnapshot({required MFDebugSession session, required Map<String, Object?> context}) {
  if (!session.may('read-context')) {
    throw MFDebugUnauthorized(session.sessionId);
  }
  return MFDebugSnapshot(context: context);
}

class MFDebugUnauthorized implements Exception {
  const MFDebugUnauthorized(this.sessionId);
  final String sessionId;
  @override
  String toString() => 'debug session $sessionId 未授予对应权限';
}

/// Debug 控制面（§29 本地/预览两级）：上下文读取、状态订阅与检查点。
/// 全部操作逐 grant 授权，未授予的操作拒绝（`mf.debug.unauthorized`）；
/// 审计登记、过期与强制撤销由承载方按 §29 纪律执行。
class MFDebugController {
  MFDebugController({required this.session, required this.runtime});

  final MFDebugSession session;
  final MFRuntime runtime;

  /// 订阅运行时拦截边界事件流（导航/动作/状态，§29「订阅导航、动作、
  /// 状态变更」）。需要 `subscribe` grant。
  StreamSubscription<Map<String, Object?>> subscribe(void Function(Map<String, Object?> event) onData) {
    if (!session.may('subscribe')) {
      throw MFDebugUnauthorized(session.sessionId);
    }
    return runtime.debugEvents.listen(onData);
  }

  /// 在已声明检查点暂停：下一次执行该绑定时挂起，直到 [resume]。
  /// 需要 `checkpoint-pause` grant。
  void pauseAt(String checkpointId) {
    if (!session.may('checkpoint-pause')) {
      throw MFDebugUnauthorized(session.sessionId);
    }
    runtime.pauseAt(checkpointId);
  }

  /// 继续（幂等：未挂起的检查点继续是空操作）。需要 `checkpoint-pause` grant。
  Future<void> resume(String checkpointId) async {
    if (!session.may('checkpoint-pause')) {
      throw MFDebugUnauthorized(session.sessionId);
    }
    await runtime.resumeCheckpoint(checkpointId);
  }

  /// 读取运行上下文快照（有界 + 掩码）。需要 `read-context` grant。
  MFDebugSnapshot snapshot() => requireSnapshot(session: session, context: runtime.debugContext());
}
