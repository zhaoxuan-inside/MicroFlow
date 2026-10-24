/// MicroFlow 前端观测模块（§24 遥测、§29 Debug、§31 实验）的公共导出。
/// 实现了 microflow_runtime 的 MFEmissionSink：运行时是唯一发射点，
/// 本模块承载信封校验、有界队列与隐私分类。
library;
export 'src/debug.dart';
export 'src/experiment.dart';
export 'src/telemetry.dart';
