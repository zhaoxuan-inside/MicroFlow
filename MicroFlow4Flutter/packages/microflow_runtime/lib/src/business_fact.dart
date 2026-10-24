/// Business Fact reliable channel (frontend-framework-design §24.1 第 4 类、
/// §30.1、§24.8): reliable business facts use an explicit submit/confirm
/// semantics with a dedup identity (idempotency key) — they never travel the
/// lossy telemetry queue, and this runtime-declared entry is the only
/// sanctioned exception to zero-instrumentation (§24.7).
///
/// Confirmation must correlate an external run reference (§24.8): a
/// confirmation without one can only enter `unknown`, never success
/// (baseline 11/28). Records are queryable by the idempotency key.
library;

import 'dart:async';

import 'package:microflow_model/microflow_model.dart';

import 'instance_ids.dart';
import 'registry.dart';
import 'runtime.dart';

/// One reliable fact record: `confirmed` (with the correlated external run
/// reference) or `unknown` (timeout / missing run reference / missing
/// implementation). Queryable by the idempotency key (baseline 28).
class MFFactRecord {
  const MFFactRecord({
    required this.factRef,
    required this.idempotencyKey,
    required this.state,
    required this.actionRequestId,
    required this.createdAt,
    this.externalRunRef,
    this.reason,
  });

  final String factRef;
  final String idempotencyKey;

  /// confirmed | unknown
  final String state;
  final String? externalRunRef;
  final String? reason;
  final String actionRequestId;
  final DateTime createdAt;

  Map<String, Object?> toJson() => {
        'fact_ref': factRef,
        'idempotency_key': idempotencyKey,
        'state': state,
        if (externalRunRef != null) 'external_run_ref': externalRunRef,
        if (reason != null) 'reason': reason,
        'action_request_id': actionRequestId,
        'created_at': createdAt.toUtc().toIso8601String(),
      };
}

/// The submission entry. Dedup identity: resubmitting an idempotency key
/// returns the existing record unchanged and raises an info diagnostic
/// (§24.1:不能用普通日志代替；确认语义 + 去重身份).
class MFBusinessFactChannel {
  MFBusinessFactChannel({required this.runtime});

  final MFRuntime runtime;
  final Map<String, MFFactRecord> _records = {};

  List<MFFactRecord> get all => List.unmodifiable(_records.values);

  MFFactRecord? query(String idempotencyKey) => _records[idempotencyKey];

  /// Submit a business fact through the registered executor [call]. The
  /// executor is a normal registered adapter/function; its result map may
  /// carry `external_run_ref` (opaque, §24.8). Timeout enters `unknown`
  /// (`mf.data.timeout`), never counts as failure-not-executed (§10).
  Future<MFFactRecord> submit({
    required String factRef,
    required String idempotencyKey,
    required String call,
    Map<String, Object?> args = const {},
    int timeoutMs = 5000,
  }) async {
    final requestId = MFInstanceIdentifiers.newRequestId();
    final existing = _records[idempotencyKey];
    if (existing != null) {
      runtime.diagSink.add(MFDiag(
        MFCodes.dataFactDuplicate,
        'Business Fact $factRef 幂等键 $idempotencyKey 重复提交，返回既有记录',
        stage: Stage.runtime,
      ));
      return existing;
    }
    final entry = runtime.registry.entry(call);
    final dynamic impl = switch (entry?.impl) {
      MFFunctionImpl f => f,
      MFAdapterImpl x => x,
      MFCapabilityImpl c => c,
      _ => null,
    };
    if (impl == null) {
      runtime.diagSink.add(MFDiag(MFCodes.capUnavailable, 'Business Fact $factRef 调用 $call 无可用实现',
          stage: Stage.runtime));
      return _record(factRef, idempotencyKey, requestId, 'unknown', reason: 'unregistered-call');
    }
    try {
      final result = await (impl as dynamic).fn(Map.of(args)).timeout(Duration(milliseconds: timeoutMs));
      final runRef = result is Map ? result['external_run_ref'] : null;
      if (runRef is String && runRef.isNotEmpty) {
        runtime.externalRunRefs.add(runRef);
        return _record(factRef, idempotencyKey, requestId, 'confirmed', externalRunRef: runRef);
      }
      // A confirmation without a correlatable run reference can only be
      // unknown (§24.8, baseline 11/28).
      return _record(factRef, idempotencyKey, requestId, 'unknown', reason: 'no-external-run-ref');
    } on TimeoutException {
      runtime.diagSink.add(
          MFDiag(MFCodes.dataTimeout, 'Business Fact $factRef 超时，进入 unknown', stage: Stage.runtime));
      return _record(factRef, idempotencyKey, requestId, 'unknown', reason: 'timeout');
    } catch (err) {
      return _record(factRef, idempotencyKey, requestId, 'unknown', reason: '$err');
    }
  }

  MFFactRecord _record(
    String factRef,
    String idempotencyKey,
    String requestId,
    String state, {
    String? externalRunRef,
    String? reason,
  }) {
    final record = MFFactRecord(
      factRef: factRef,
      idempotencyKey: idempotencyKey,
      state: state,
      externalRunRef: externalRunRef,
      reason: reason,
      actionRequestId: requestId,
      createdAt: DateTime.now().toUtc(),
    );
    _records[idempotencyKey] = record;
    return record;
  }
}
