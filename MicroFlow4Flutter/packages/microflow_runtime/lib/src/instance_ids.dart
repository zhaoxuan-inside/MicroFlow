/// Deterministic runtime identifiers (§12.1, §13.2): every page instance,
/// component instance and render revision gets an id used in telemetry and
/// diagnostics (§22.3).
library;

class MFInstanceIdentifiers {
  MFInstanceIdentifiers({
    required this.projectId,
    required this.releaseId,
    required this.environment,
    this.rendererPackage = 'microflow4_flutter',
    this.rendererVersion = '0.2.0',
    String? sessionId,
    String? traceId,
  })  : sessionId = sessionId ?? _newId('ses'),
        traceId = traceId ?? _newId('tr');

  final String projectId;
  final String releaseId;
  final String environment;
  final String rendererPackage;
  final String rendererVersion;
  final String sessionId;
  final String traceId;

  static int _seq = 0;

  static String _newId(String prefix) {
    final n = DateTime.now().microsecondsSinceEpoch.toRadixString(36) + (++_seq).toRadixString(36);
    return '$prefix-$n';
  }

  /// Public id minting for cross-module core use (e.g. boundary capture,
  /// event request ids).
  static String newRequestId() => _newId('ar');

  String pageInstanceId() => _newId('pg');

  String componentInstanceId(String pageInstanceId, String ownerId) => '$pageInstanceId/$ownerId';

  int renderRevision() => ++_seq;
}
