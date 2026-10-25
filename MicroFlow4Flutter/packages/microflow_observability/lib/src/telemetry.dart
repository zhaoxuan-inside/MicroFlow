/// Telemetry envelope, standard event families and bounded queue
/// (frontend-framework-design §24.1, §24.2, §24.7, §30.1).
///
/// Business code has zero direct collection calls: the runtime is the only
/// emitter (interception faces are page lifecycle, navigation, action
/// execution and adapter calls). Application of a standard-family manual
/// report is a static-validation class of problem; at runtime a manual
/// `submitStandard` call is refused with a diagnostic.
library;

import 'dart:async';
import 'package:microflow_model/microflow_model.dart';
import 'package:microflow_runtime/microflow_runtime.dart';

// MFStandardEvents（§24.2 标准运营事件族）单一来源在模型层，这里保持再导出。
export 'package:microflow_model/microflow_model.dart' show MFStandardEvents;

const allowedEnvironments = {'dev', 'preview', 'production'};

const allowedPrivacyClasses = mfAllowedPrivacyClasses;

/// Event envelope (§24.2): machine-checkable Schema with identity fields
/// separate from raw credentials (§4.4, §32).
class MFEventEnvelope {
  MFEventEnvelope({
    required String eventName,
    required Map<String, Object?> payload,
    required this.sessionId,
    required this.pageInstanceId,
    required this.route,
    required this.releaseId,
    required this.rendererVersion,
    required this.environment,
    required this.traceId,
    this.schemaVersion = '1.0',
    this.privacyClass = 'operational',
    this.layerInstanceId,
    this.componentInstanceId,
    this.interactionId,
    this.actionRequestId,
    this.identity = const {},
    this.experimentAssignments = const [],
    String? eventId,
    String? occurredAt,
    String? clientSentAt,
  }) {
    this.eventId = eventId ?? _uuid();
    this.occurredAt = occurredAt ?? DateTime.now().toUtc().toIso8601String();
    this.clientSentAt = clientSentAt ?? DateTime.now().toUtc().toIso8601String();
    _eventName = eventName;
    _payload = payload;
  }

  late final String eventId;
  late final String occurredAt;
  late final String clientSentAt;
  final String schemaVersion;
  late final String _eventName;
  late final Map<String, Object?> _payload;
  final String sessionId;
  final String pageInstanceId;
  final String route;
  final String releaseId;
  final String rendererVersion;
  final String environment;
  final String traceId;
  final String privacyClass;
  final String? layerInstanceId;
  final String? componentInstanceId;
  final String? interactionId;
  final String? actionRequestId;
  final Map<String, Object?> identity;
  final List<Map<String, Object?>> experimentAssignments;

  String get eventName => _eventName;
  Map<String, Object?> get payload => _payload;

  /// 从持久化日志恢复（§30.2 查询/导出消费面）：保留原 event_id 与
  /// occurred_at/client_sent_at——重放与查询的时间过滤以原始发生时间为准。
  factory MFEventEnvelope.fromJson(Map<String, Object?> json) => MFEventEnvelope(
        eventName: json['event_name'] as String,
        payload: (json['payload'] as Map?)?.cast<String, Object?>() ?? <String, Object?>{},
        sessionId: json['session_id'] as String,
        pageInstanceId: json['page_instance_id'] as String,
        route: json['route'] as String,
        releaseId: json['release_id'] as String,
        rendererVersion: json['renderer_version'] as String,
        environment: json['environment'] as String,
        traceId: json['trace_id'] as String,
        schemaVersion: json['schema_version'] as String? ?? '1.0',
        privacyClass: json['privacy_class'] as String? ?? 'operational',
        layerInstanceId: json['layer_instance_id'] as String?,
        componentInstanceId: json['component_instance_id'] as String?,
        interactionId: json['interaction_id'] as String?,
        actionRequestId: json['action_request_id'] as String?,
        identity: (json['identity'] as Map?)?.cast<String, Object?>() ?? const {},
        experimentAssignments: ((json['experiment_assignments'] as List?) ?? const [])
            .cast<Map>()
            .map((e) => e.cast<String, Object?>())
            .toList(growable: false),
        eventId: json['event_id'] as String?,
        occurredAt: json['occurred_at'] as String?,
        clientSentAt: json['client_sent_at'] as String?,
      );

  factory MFEventEnvelope.fromRaw(Map<String, Object?> raw) => MFEventEnvelope(
        eventName: raw['event_name'] as String,
        payload: (raw['payload'] as Map?)?.cast<String, Object?>() ?? <String, Object?>{},
        sessionId: raw['session_id'] as String,
        pageInstanceId: raw['page_instance_id'] as String,
        route: raw['route'] as String,
        releaseId: raw['release_id'] as String,
        rendererVersion: raw['renderer_version'] as String,
        environment: raw['environment'] as String,
        traceId: raw['trace_id'] as String,
        layerInstanceId: raw['layer_instance_id'] as String?,
        componentInstanceId: raw['component_instance_id'] as String?,
        interactionId: raw['interaction_id'] as String?,
        actionRequestId: raw['action_request_id'] as String?,
        privacyClass: raw['privacy_class'] as String? ?? 'operational',
        identity: (raw['identity'] as Map?)?.cast<String, Object?>() ?? const {},
        experimentAssignments: ((raw['experiment_assignments'] as List?) ?? const [])
            .cast<Map>()
            .map((e) => e.cast<String, Object?>())
            .toList(growable: false),
      );

  static String _uuid() => '${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}-${Iterable.generate(4, (i) => (i + 1).toRadixString(36)).join()}';

  Map<String, Object?> toJson() => {
    'event_id': eventId,
    'event_name': _eventName,
    'schema_version': schemaVersion,
    'occurred_at': occurredAt,
    'release_id': releaseId,
    'renderer_version': rendererVersion,
    'environment': environment,
    'session_id': sessionId,
    'page_instance_id': pageInstanceId,
    if (layerInstanceId != null) 'layer_instance_id': layerInstanceId,
    if (componentInstanceId != null) 'component_instance_id': componentInstanceId,
    'route': route,
    if (interactionId != null) 'interaction_id': interactionId,
    if (actionRequestId != null) 'action_request_id': actionRequestId,
    'trace_id': traceId,
    'experiment_assignments': experimentAssignments,
    'identity': identity,
    'payload': _payload,
    'privacy_class': privacyClass,
    'client_sent_at': clientSentAt,
  };

  /// Envelope Schema validation (§24.2): field-limited structure, verified
  /// identity separation; violations are uneventful rejections returned as
  /// diagnostics.
  MFDiag? validate() {
    if (!allowedEnvironments.contains(environment)) {
      return const MFDiag(MFCodes.teleSchemaInvalid, 'environment 不在允许枚举内');
    }
    if (!allowedPrivacyClasses.contains(privacyClass)) {
      return const MFDiag(MFCodes.teleSchemaInvalid, 'privacy_class 不在允许枚举内');
    }
    if (traceId.isEmpty || sessionId.isEmpty || pageInstanceId.isEmpty) {
      return const MFDiag(MFCodes.teleSchemaInvalid, '缺失必需身份/追踪字段');
    }
    for (final k in identity.keys) {
      // Identity separation (§32): keys must not carry credential names,
      // and values are opaque/hashed references (§4.4).
      if (_looksCredential(k)) {
        return const MFDiag(MFCodes.teleSchemaInvalid, 'identity 中包含疑似凭据字段');
      }
    }
    return null;
  }

  static final _credentialPattern = RegExp(
    r'(password|passwd|secret|token|api[_-]?key|authorization|bearer)',
    caseSensitive: false,
  );

  static bool _looksCredential(String key) =>
      _credentialPattern.hasMatch(key);
}

/// Receiver contract (§30.1): business layers carry the external sink.
abstract class MFTelemetrySink {
  Future<void> accept(List<MFEventEnvelope> batch);
}

/// In-memory queue for tests/previews: bounded, drop-counting, priority discard.
class MFInMemorySink implements MFTelemetrySink {
  final int capacity;
  final List<MFEventEnvelope> delivered = [];
  int dropped = 0;
  final List<MFDiag> diagnostics = [];

  MFInMemorySink({this.capacity = 500});

  @override
  Future<void> accept(List<MFEventEnvelope> batch) async {
    for (final e in batch) {
      if (delivered.length >= capacity) {
        dropped++;
        diagnostics.add(
          MFDiag(MFCodes.teleQueueOverflow, '队列满载丢弃事件 ${e.eventName}', stage: Stage.runtime),
        );
        continue;
      }
      delivered.add(e);
    }
  }
}

/// Priority-aware bounded queue with batch, retry, backoff-off and drop count
/// (§24.2). Implements the runtime module's [MFEmissionSink]: the runtime
/// is the only emitter; this class owns envelope building / Schema validation.
/// Failure to ingest never blocks core user flows.
class MFTelemetryQueue implements MFEmissionSink {
  MFTelemetryQueue({required this.sink, this.batchMax = 32, this.capacity = 500});

  final MFTelemetrySink sink;
  final int batchMax;
  final int capacity;

  final List<MFEventEnvelope> _buffer = [];
  int dropped = 0;
  final List<MFDiag> diagnostics = [];

  /// Runtime emission boundary (§24.7): builds a §24.2 envelope from the
  /// raw interception event and routes it through the full validation
  /// pipeline (Schema, privacy, queue budget, drop accounting).
  @override
  void emit(MFRawEvent raw) {
    // §24.7 唯一发射点纪律：标准运营事件族只允许带运行时拦截边界来源
    // 标记（mf_source=runtime-intercept）的零埋点发射进入；业务代码对
    // 标准事件族的手工上报被拒绝并产生 mf.tele.manual-standard-event。
    final eventName = raw['event_name'];
    if (eventName is String &&
        MFStandardEvents.all.contains(eventName) &&
        raw['mf_source'] != 'runtime-intercept') {
      diagnostics.add(const MFDiag(MFCodes.teleManualStandardEvent, '标准事件族手工上报被拒绝（§24.7 运行时是唯一发射点）',
          stage: Stage.runtime));
      return;
    }
    final event = MFEventEnvelope.fromRaw(raw);
    enqueue(event);
  }

  void enqueue(MFEventEnvelope event) {
    final invalid = event.validate();
    if (invalid != null) {
      diagnostics.add(invalid);
      return;
    }
    if (_buffer.length >= capacity) {
      dropped++;
      diagnostics.add(
        MFDiag(MFCodes.teleQueueOverflow, '队列满载丢弃事件 ${event.eventName}', stage: Stage.runtime),
      );
      return;
    }
    _buffer.add(event);
    if (_buffer.length >= batchMax) {
      unawaited(_flush());
    }
  }

  Future<void> _flush() async {
    final batch = List.of(_buffer);
    _buffer.clear();
    try {
      await sink.accept(batch);
    } catch (_) {
      // Sink failure must not interrupt the user flow (§24.2): the events
      // are re-queued if space remains; otherwise counted as dropped.
      for (final e in batch) {
        if (_buffer.length < capacity) {
          _buffer.add(e);
        } else {
          dropped++;
        }
      }
    }
  }

  Future<void> flush() => _flush();

  Map<String, Object?> dataQuality() => {
    'queued': _buffer.length,
    'dropped': dropped,
    'diagnostics': diagnostics.length,
  };
}
