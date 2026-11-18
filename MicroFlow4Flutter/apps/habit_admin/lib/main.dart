import 'package:flutter/material.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'src/admin_data.dart';
import 'src/admin_model.dart';
import 'src/mf_storage.dart';
import 'src/telemetry_sink.dart';

/// 习惯打卡运营管理平台 —— 基于 MicroFlow4Flutter 的 §30.2 查询消费面。
///
/// 数据来源是打卡平台（同源部署）经完整校验管道落盘的真实遥测日志；
/// 管理平台自身的页面访问/功能使用事件同样经运行时零埋点采集，
/// 写入独立日志键。无桩代码、无示例假数据——空数据如实显示为空态。
void main() {
  final storage = MFKeyValueStore.open();
  final data = AdminData(storage);

  final registry = MFRegistry();
  registerAdminPrimitives(registry);
  registerAdminAdapters(registry, data);

  final project = buildAdminProject();
  final validation = MFValidator(project: project, registry: registry).validate();
  if (!validation.ok) {
    throw StateError(
      'habit-admin 静态校验未通过：${validation.diagnostics.where((d) => d.severity == Severity.error).join('; ')}',
    );
  }

  final fw = MicroFlowFramework.create(
    project: project,
    registry: registry,
    environment: 'production',
    releaseId: 'habit-admin-r1',
    telemetrySink: MFStorageSink(storage, key: 'admin.telemetry.log'),
  );

  runApp(MicroFlowApp(project: project, registry: registry, runtime: fw.runtime,
      appName: '打卡运营管理'));
}
