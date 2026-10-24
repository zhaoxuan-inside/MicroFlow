/// Debug contract (§29): three levels (local/preview/production-controlled),
/// permission-gated reads, bounded snapshots with masking.
library;

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
  String toString() => 'debug session $sessionId 未授予 read-context';
}
