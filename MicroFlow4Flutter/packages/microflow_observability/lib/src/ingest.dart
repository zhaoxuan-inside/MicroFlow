/// Telemetry Ingest 参考实现（frontend-framework-design §30.1）：批量、退避
/// 重试、断网缓存、event_id 去重与数据质量指标，作为可注入 MFTelemetrySink
/// 的默认承载。接收端服务由业务层按协议承载（§27）；本实现面向测试与预览，
/// 传输函数可替换为任意业务侧投递通道。
library;

import 'dart:async';
import 'dart:convert';

import 'package:microflow_model/microflow_model.dart';

import 'telemetry.dart';

/// 业务侧投递通道：接收一批信封并承诺按 §30.1 交付。
typedef MFIngestTransport = Future<void> Function(List<MFEventEnvelope> batch);

/// 参考实现：面向 [MFIngestTransport] 的可靠投递层。
///
/// - 批量：按 [batchMax] 切批；退避：指数退避重试至 [maxAttempts]；
/// - 断网缓存：传输最终失败时进入有界离线缓存并记录缺口区间（offline
///   window），恢复后由 [drainOffline] 补齐；
/// - event_id 去重：重复投递幂等；
/// - 数据质量：接收/去重/交付/丢弃/重试/丢失率/缺口区间全量暴露。
class MFReliableIngest implements MFTelemetrySink {
  MFReliableIngest({
    required this.transport,
    this.batchMax = 32,
    this.maxAttempts = 3,
    this.offlineCapacity = 500,
    this.compressor,
    Duration Function(int attempt)? backoff,
  }) : _backoff = backoff ?? ((attempt) => Duration(milliseconds: 100 * (1 << (attempt - 1))));

  final MFIngestTransport transport;
  final int batchMax;
  final int maxAttempts;
  final int offlineCapacity;

  /// 压缩钩子（§30.1 压缩职责的可插拔承载）：提供后 [encodedBatch] 输出
  /// 压缩字节，供业务传输层使用；默认 JSON 文本体。
  final List<int> Function(String body)? compressor;

  final Duration Function(int attempt) _backoff;

  final Set<String> _seenEventIds = {};
  final List<MFEventEnvelope> _outbox = [];
  final List<MFEventEnvelope> _offline = [];
  final List<Map<String, String>> offlineWindows = [];
  bool _offlineActive = false;

  int received = 0;
  int deduplicated = 0;
  int delivered = 0;
  int dropped = 0;
  int attempts = 0;

  final List<MFDiag> diagnostics = [];

  @override
  Future<void> accept(List<MFEventEnvelope> batch) async {
    for (final e in batch) {
      received++;
      if (!_seenEventIds.add(e.eventId)) {
        deduplicated++;
        continue;
      }
      if (_offlineActive) {
        _cacheOffline(e);
      } else {
        _outbox.add(e);
      }
    }
    await _drainOutbox();
  }

  Future<void> _drainOutbox() async {
    while (_outbox.isNotEmpty) {
      final take = batchMax.clamp(1, _outbox.length);
      final batch = _outbox.sublist(0, take);
      var ok = false;
      for (var attempt = 1; attempt <= maxAttempts && !ok; attempt++) {
        attempts++;
        try {
          await transport(batch);
          ok = true;
        } catch (_) {
          if (attempt < maxAttempts) {
            await Future<void>.delayed(_backoff(attempt));
          }
        }
      }
      _outbox.removeRange(0, take);
      if (ok) {
        delivered += take;
        if (_offlineActive) {
          _closeOfflineWindow();
        }
      } else {
        if (!_offlineActive) {
          _openOfflineWindow();
        }
        for (final e in batch) {
          _cacheOffline(e);
        }
        break;
      }
    }
  }

  /// 恢复在线：关闭断网窗口并重试离线缓存（补齐缺口，迟到数据进入后续
  /// 增量，禁止静默改写已交付数据，§30.2）。
  Future<void> drainOffline() async {
    if (_offlineActive) {
      _closeOfflineWindow();
    }
    _outbox.insertAll(0, _offline);
    _offline.clear();
    await _drainOutbox();
  }

  void _openOfflineWindow() {
    _offlineActive = true;
    offlineWindows.add({'from': DateTime.now().toUtc().toIso8601String(), 'reason': 'transport-failure'});
  }

  void _closeOfflineWindow() {
    _offlineActive = false;
    if (offlineWindows.isNotEmpty) {
      offlineWindows.last['to'] = DateTime.now().toUtc().toIso8601String();
    }
  }

  void _cacheOffline(MFEventEnvelope e) {
    if (_offline.length >= offlineCapacity) {
      dropped++;
      diagnostics.add(const MFDiag(MFCodes.teleQueueOverflow, '断网缓存满载丢弃（§30.1）', stage: Stage.runtime));
      return;
    }
    _offline.add(e);
  }

  /// §30.1 压缩职责承载：默认 JSON 文本体；提供 compressor 时输出压缩体。
  Object encodedBatch(List<MFEventEnvelope> batch) {
    final body = jsonEncode([for (final e in batch) e.toJson()]);
    final compress = compressor;
    return compress == null ? body : compress(body);
  }

  Map<String, Object?> dataQuality() {
    final total = delivered + dropped;
    return {
      'received': received,
      'deduplicated': deduplicated,
      'delivered': delivered,
      'dropped': dropped,
      'offline_cached': _offline.length,
      'outbox': _outbox.length,
      'attempts': attempts,
      'loss_rate': total == 0 ? 0.0 : dropped / total,
      'offline_windows': [for (final w in offlineWindows) Map<String, String>.of(w)],
      'diagnostics': diagnostics.length,
    };
  }
}
