/// Recovery executor (frontend-framework-design §16.1, §22.1): collects and
/// restores runtime snapshots strictly per the declared Recovery Contract.
///
/// Invariants: `unknown_side_effects.auto_retry` is pinned false (baseline
/// 27) — restored unknown side effects surface as unknown, stay queryable in
/// the ledger and are never re-run; snapshot schema-version mismatch enters
/// the error boundary; release change migrates only through explicitly
/// registered migrators; an expired snapshot starts fresh per contract.
library;

import 'package:microflow_model/microflow_model.dart';

import 'error_boundary.dart';
import 'instance_ids.dart';
import 'runtime.dart';

/// A recovery snapshot (§16.1): content is collected per the contract's
/// `snapshot` group switches. Session state is declared-only by schema.
class MFRecoverySnapshot {
  MFRecoverySnapshot({
    required this.snapshotVersion,
    required this.releaseId,
    required this.createdAt,
    this.route,
    this.parameters = const {},
    this.pageState = const {},
    this.sessionState = const {},
    this.pendingActions = const [],
    this.stateRevision = 0,
    this.unknownSideEffects = const [],
  });

  final String snapshotVersion;
  final String releaseId;
  final DateTime createdAt;

  /// Page definition id of the interrupted instance (contract: route).
  final String? route;
  final Map<String, Object?> parameters;

  /// Declared page state members only.
  final Map<String, Object?> pageState;

  /// Declared session state (declared-only, §16.1).
  final Map<String, Object?> sessionState;
  final List<String> pendingActions;
  final int stateRevision;

  /// Unknown side effects at snapshot time (surface-as-unknown, §16.1).
  final List<Map<String, Object?>> unknownSideEffects;

  /// 序列化（§16.1）：快照必须可持久化才能跨进程恢复；字段与构造面一一对应。
  Map<String, Object?> toJson() => {
        'snapshot_version': snapshotVersion,
        'release_id': releaseId,
        'created_at': createdAt.toUtc().toIso8601String(),
        'route': route,
        'parameters': parameters,
        'page_state': pageState,
        'session_state': sessionState,
        'pending_actions': pendingActions,
        'state_revision': stateRevision,
        'unknown_side_effects': unknownSideEffects,
      };

  factory MFRecoverySnapshot.fromJson(Map<String, Object?> json) => MFRecoverySnapshot(
        snapshotVersion: json['snapshot_version'] as String? ?? '1.0',
        releaseId: json['release_id'] as String? ?? '',
        createdAt: DateTime.tryParse(json['created_at'] as String? ?? '') ?? DateTime.now().toUtc(),
        route: json['route'] as String?,
        parameters: (json['parameters'] as Map?)?.cast<String, Object?>() ?? const {},
        pageState: (json['page_state'] as Map?)?.cast<String, Object?>() ?? const {},
        sessionState: (json['session_state'] as Map?)?.cast<String, Object?>() ?? const {},
        pendingActions: ((json['pending_actions'] as List?) ?? const []).cast<String>().toList(growable: false),
        stateRevision: (json['state_revision'] as num?)?.toInt() ?? 0,
        unknownSideEffects: ((json['unknown_side_effects'] as List?) ?? const [])
            .cast<Map>()
            .map((e) => e.cast<String, Object?>())
            .toList(growable: false),
      );
}

/// Restore outcome: either the instance was restored or the runtime started
/// fresh with a stated cause; every denial carries diagnostics.
class MFRecoveryOutcome {
  const MFRecoveryOutcome({required this.restored, required this.reason, this.diagnostics = const []});
  final bool restored;

  /// restored | `fresh-start:<cause>`
  final String reason;
  final List<MFDiag> diagnostics;
}

/// Migrators transform a snapshot's page state across releases (§22.3
/// version-migration discipline); they must be registered explicitly.
typedef MFSnapshotMigrator = Map<String, Object?> Function(Map<String, Object?> pageState);

class MFRecoveryExecutor {
  MFRecoveryExecutor({required this.runtime});

  final MFRuntime runtime;
  final Map<String, MFSnapshotMigrator> _migrators = {};

  void registerMigrator(String id, MFSnapshotMigrator fn) => _migrators[id] = fn;

  /// Collect a snapshot of the current instance per [contract] switches.
  MFRecoverySnapshot collect(MFRecoveryContract contract) {
    final page = runtime.current;
    return MFRecoverySnapshot(
      snapshotVersion: contract.snapshotVersion,
      releaseId: runtime.ids.releaseId,
      createdAt: DateTime.now().toUtc(),
      route: contract.snapshotRoute ? page?.definition.id : null,
      parameters: contract.snapshotParameters ? Map.of(page?.params ?? const {}) : const {},
      pageState: contract.snapshotPageState ? Map.of(runtime.state.pageState()) : const {},
      sessionState: Map.of(runtime.state.snapshotSession()),
      pendingActions: contract.snapshotPendingActions ? runtime.inFlightBindings : const [],
      stateRevision: contract.snapshotStateRevision ? runtime.generation.value : 0,
      unknownSideEffects: List.of(runtime.unknownResults),
    );
  }

  /// Restore [snapshot] per [contract]. Denials return a fresh-start outcome
  /// with diagnostics; version mismatch additionally enters the error
  /// boundary (§16.1).
  Future<MFRecoveryOutcome> restore(MFRecoverySnapshot snapshot, {required MFRecoveryContract contract}) async {
    final diags = <MFDiag>[];
    if (contract.unknownSideEffectsAutoRetry) {
      // Defensive: the static gate already rejects such contracts.
      diags.add(const MFDiag(MFCodes.buildRecoveryAutoRetry, '恢复契约声明 auto_retry=true（§16.1 固定 false）'));
      return MFRecoveryOutcome(restored: false, reason: 'fresh-start:recovery-auto-retry', diagnostics: diags);
    }
    if (snapshot.snapshotVersion != contract.snapshotVersion) {
      final diag = MFDiag(MFCodes.stateSnapshotVersionMismatch,
          '快照版本 ${snapshot.snapshotVersion} 与契约 ${contract.snapshotVersion} 不匹配（§16.1）');
      diags.add(diag);
      runtime.boundaryHandler.capture(
        MFInstanceIdentifiers.newRequestId(),
        MFBoundaryInfo(boundaryId: 'recovery:${contract.id}', error: diag),
      );
      return MFRecoveryOutcome(restored: false, reason: 'fresh-start:snapshot-version-mismatch', diagnostics: diags);
    }
    final age = DateTime.now().toUtc().difference(snapshot.createdAt);
    if (age.inSeconds > contract.maxAgeSeconds) {
      diags.add(MFDiag(MFCodes.stateSnapshotExpired, '快照年龄 ${age.inSeconds}s 超过 max_age_s=${contract.maxAgeSeconds}',
          severity: Severity.warning, stage: Stage.runtime));
      return MFRecoveryOutcome(restored: false, reason: 'fresh-start:expired', diagnostics: diags);
    }
    var pageState = Map.of(snapshot.pageState);
    if (snapshot.releaseId != runtime.ids.releaseId) {
      MFSnapshotMigrator? migrator;
      for (final id in contract.migrators) {
        final m = _migrators[id];
        if (m != null) {
          migrator = m;
          break;
        }
      }
      if (migrator == null) {
        diags.add(MFDiag(MFCodes.stateReleaseMigrationMissing,
            'release ${snapshot.releaseId} → ${runtime.ids.releaseId} 无显式迁移器登记，禁止恢复（§16.1）',
            severity: Severity.warning, stage: Stage.runtime));
        return MFRecoveryOutcome(restored: false, reason: 'fresh-start:release-migration-missing', diagnostics: diags);
      }
      pageState = migrator(pageState);
    }
    // Revalidation (§16.1 revalidation): the snapshot route must still exist
    // in the running release.
    final routeId = snapshot.route;
    if (routeId == null || runtime.project.page(routeId) == null) {
      diags.add(MFDiag(MFCodes.refDangling, '恢复快照路由 $routeId 在当前发布中不存在'));
      return MFRecoveryOutcome(restored: false, reason: 'fresh-start:route-missing', diagnostics: diags);
    }
    // Restore: a new instance with the current frozen context (§4.5), page
    // state replayed for declared members only, declared session state
    // restored. Pending actions and unknown side effects surface as unknown
    // in the ledger — surfaced, queryable, never re-run (baseline 27).
    await runtime.push(routeId, kind: 'replace', args: snapshot.parameters);
    final instance = runtime.current!;
    for (final e in pageState.entries) {
      if (instance.definition.stateMembers.contains(e.key)) {
        runtime.state.writeDeep('page', e.key, e.value);
      }
    }
    runtime.state.restoreSession(snapshot.sessionState);
    for (final pending in snapshot.pendingActions) {
      runtime.recordUnknown(
          call: pending, requestId: MFInstanceIdentifiers.newRequestId(), reason: 'restore-pending-action');
    }
    return MFRecoveryOutcome(restored: true, reason: 'restored', diagnostics: diags);
  }
}
