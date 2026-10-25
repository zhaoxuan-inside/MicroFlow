/// 遥测接收端本地承载（frontend-framework-design §30.1/§30.2 接收端由业务层
/// 承载）：把 §24.2 事件信封按行（JSONL）追加到共享存储，供管理平台按
/// MFLocalQueryEngine 协议查询、导出与做数据质量统计。
library;

import 'dart:convert';

import 'local_kv.dart';

/// 信封 <-> JSONL 行编解码。损坏行可被识别（返回 null），不静默吞掉。
class TelemetryLogCodec {
  const TelemetryLogCodec._();

  static String encode(Map<String, Object?> envelope) => jsonEncode(envelope);

  static Map<String, Object?>? decode(String line) {
    try {
      final value = jsonDecode(line);
      return value is Map ? value.cast<String, Object?>() : null;
    } catch (_) {
      return null;
    }
  }
}

/// 接收端数据质量计数（§30.1）：损坏、容量淘汰与采集关闭期间的抑制。
class TelemetryLogMetrics {
  int corrupt = 0;
  int evicted = 0;
  int suppressed = 0;

  Map<String, Object?> toMap() =>
      {'corrupt': corrupt, 'evicted': evicted, 'suppressed': suppressed};
}

/// 追加式事件日志（JSONL，单键）。容量上限按声明淘汰最旧事件并计数，
/// 不静默改写已交付内容。
class TelemetryLogStore {
  TelemetryLogStore({
    required this.kv,
    this.key = defaultKey,
    this.capacity = 5000,
  });

  static const defaultKey = 'mf.telemetry.events.v1';
  static const controlKey = 'mf.telemetry.control.v1';

  final MFLocalKV kv;
  final String key;
  final int capacity;
  final TelemetryLogMetrics metrics = TelemetryLogMetrics();

  List<String> _readLines() {
    final raw = kv.read(key);
    if (raw == null || raw.isEmpty) return const [];
    return LineSplitter().convert(raw);
  }

  void _writeLines(List<String> lines) => kv.write(key, lines.join('\n'));

  /// 追加一批已校验信封（§24.2）；超容量时淘汰最旧行并计入质量指标。
  void append(List<Map<String, Object?>> envelopes) {
    if (envelopes.isEmpty) return;
    final lines = List<String>.of(_readLines());
    for (final envelope in envelopes) {
      lines.add(TelemetryLogCodec.encode(envelope));
    }
    if (lines.length > capacity) {
      final excess = lines.length - capacity;
      lines.removeRange(0, excess);
      metrics.evicted += excess;
    }
    _writeLines(lines);
  }

  /// 按追加序读取全部事件；空行跳过，损坏行计入质量指标后跳过。
  List<Map<String, Object?>> readAll() {
    final out = <Map<String, Object?>>[];
    for (final line in _readLines()) {
      if (line.trim().isEmpty) continue;
      final decoded = TelemetryLogCodec.decode(line);
      if (decoded == null) {
        metrics.corrupt++;
        continue;
      }
      out.add(decoded);
    }
    return out;
  }

  /// 保留期清理（日志管理）：删除早于 [age] 的事件行，返回删除条数。
  /// 损坏行不删除——它们是数据质量面的证据（§30.2 禁止静默改写）。
  int pruneOlderThan(Duration age, {DateTime? now}) {
    final cutoff =
        ((now ?? DateTime.now()).toUtc().subtract(age)).toIso8601String();
    final kept = <String>[];
    var removed = 0;
    for (final line in _readLines()) {
      final envelope = TelemetryLogCodec.decode(line);
      final at = envelope?['occurred_at'];
      final keep =
          envelope == null || at is! String || at.compareTo(cutoff) >= 0;
      if (keep) {
        kept.add(line);
      } else {
        removed++;
      }
    }
    if (removed > 0) _writeLines(kept);
    return removed;
  }
}

/// 采集控制开关（管理平台写入，采集端每次投递前读取）。未写入过 = 开启。
class CollectionControl {
  CollectionControl({required this.kv, this.key = TelemetryLogStore.controlKey});

  static const valueOn = 'on';
  static const valueOff = 'off';

  final MFLocalKV kv;
  final String key;

  bool get enabled => kv.read(key) != valueOff;

  set enabled(bool value) => kv.write(key, value ? valueOn : valueOff);
}
