/// 管理平台数据面：读取同源存储里打卡平台落盘的遥测日志
/// （MFStorageSink 持久化的信封 JSON），经 §30.2 本地查询引擎
/// 提供运营指标。损坏行计入丢弃口径——数据质量如实反映。
library;

import 'dart:convert';

import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'mf_storage.dart';

class AdminData {
  AdminData(this.storage);

  final MFKeyValueStore storage;

  int _corrupt = 0;

  /// 打卡平台遥测日志（同源键 'telemetry.log'）。
  List<MFEventEnvelope> loadTrackerEvents() {
    _corrupt = 0;
    final raw = storage.read('telemetry.log');
    if (raw == null || raw.isEmpty) return const [];
    final out = <MFEventEnvelope>[];
    for (final e in jsonDecode(raw) as List) {
      try {
        out.add(MFEventEnvelope.fromJson((e as Map).cast<String, Object?>()));
      } catch (_) {
        _corrupt++;
      }
    }
    return out;
  }

  int get corruptCount => _corrupt;

  /// 打卡平台采集队列/存储的丢弃计数（同源键 'telemetry.quality'）。
  int trackerDropped() {
    final raw = storage.read('telemetry.quality');
    if (raw == null || raw.isEmpty) return 0;
    final q = (jsonDecode(raw) as Map).cast<String, Object?>();
    return ((q['queue_dropped'] as num?)?.toInt() ?? 0) + ((q['sink_dropped'] as num?)?.toInt() ?? 0);
  }

  /// 数据质量口径（丢失/丢弃与交付同源一致，§30.2）。
  Map<String, Object?> qualityOf(List<MFEventEnvelope> events) => {
        'delivered': events.length,
        'dropped': trackerDropped() + _corrupt,
      };

  MFLocalQueryEngine engine(List<MFEventEnvelope> events) =>
      MFLocalQueryEngine(events: () => events, dataQuality: () => qualityOf(events));

  static String fmtTime(Object? iso) {
    if (iso is! String || iso.isEmpty) return '';
    final t = DateTime.tryParse(iso)?.toLocal();
    if (t == null) return '';
    final day = '${t.month.toString().padLeft(2, '0')}-${t.day.toString().padLeft(2, '0')}';
    return '$day ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }
}
