/// 采集端落地 sink：把框架遥测队列交付的信封批次写入共享 JSONL 日志
/// （§30.1 接收端由业务层承载；采集失败不进入用户主路径）。
library;

import 'package:microflow_observability/microflow_observability.dart';

import 'telemetry_log.dart';

/// 业务层 [MFTelemetrySink]：采集关闭时整批抑制并计数，开启时逐信封落盘。
class TelemetryLogSink implements MFTelemetrySink {
  TelemetryLogSink(this._store, this._control);

  final TelemetryLogStore _store;
  final CollectionControl _control;

  @override
  Future<void> accept(List<MFEventEnvelope> batch) async {
    if (!_control.enabled) {
      _store.metrics.suppressed += batch.length;
      return;
    }
    _store.append([for (final envelope in batch) envelope.toJson()]);
  }
}
