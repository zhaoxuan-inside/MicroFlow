/// 遥测接收端（§30.1 接收契约的宿主承载）：把通过完整校验管道的信封
/// 追加持久化到键值存储——打卡平台写入的日志由同源部署的管理平台读取，
/// 构成真实的运营数据回流通道。写入失败计数丢弃，不阻断调用方（§24.2）。
library;

import 'dart:convert';

import 'mf_storage.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart' show MFTelemetrySink, MFEventEnvelope;

class MFStorageSink implements MFTelemetrySink {
  MFStorageSink(this.storage, {this.key = 'telemetry.log', this.capacity = 500});

  final MFKeyValueStore storage;
  final String key;
  final int capacity;

  /// 存储层丢弃计数（写入失败或超容量裁剪）——进入数据质量口径。
  int dropped = 0;

  @override
  Future<void> accept(List<MFEventEnvelope> batch) async {
    try {
      final raw = storage.read(key);
      final list = raw == null || raw.isEmpty
          ? <Map<String, Object?>>[]
          : [for (final e in jsonDecode(raw) as List) (e as Map).cast<String, Object?>()];
      list.addAll([for (final e in batch) e.toJson()]);
      if (list.length > capacity) {
        dropped += list.length - capacity;
        list.removeRange(0, list.length - capacity);
      }
      storage.write(key, jsonEncode(list));
    } catch (_) {
      dropped += batch.length; // §24.2：采集失败不阻断用户流程
    }
  }
}
