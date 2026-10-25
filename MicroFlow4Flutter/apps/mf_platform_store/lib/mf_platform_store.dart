/// mf_platform_store — 打卡平台与运营管理平台之间的业务层数据契约：
/// 同源 localStorage KV、遥测 JSONL 接收日志、采集控制开关与跨标签页通知。
///
/// 采集端（habit_tracker）通过 [TelemetryLogSink] 把框架遥测队列交付的
/// §24.2 信封批次落盘；管理端（ops_admin）读取同一日志并按 §30.2 查询/
/// 导出协议消费。采集控制开关由管理平台写入、采集端每次投递前读取。
library;

export 'src/local_kv.dart';
export 'src/telemetry_log.dart';
export 'src/telemetry_sink.dart';
