/// 交易平台演示（纯 Web）：MicroFlow 框架解释运行模式（§13.3）。
///
/// 业务层职责（§27 责任矩阵）只有三件事：注册真实资源实现（registry.dart）、
/// 提供遥测接收端（mf_platform_store 的 JSONL 落地 sink，供同源管理平台
/// 收集——监控/运营数据面）、装配框架并启动。页面由 authoring 命令面构造
/// （project.dart），页面、交互与采集注记全部由项目模型声明。
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mf_platform_store/mf_platform_store.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'project.dart';
import 'registry.dart';

void main() {
  final kv = const MFLocalKV();
  final registry = buildTradingRegistry();
  final project = buildTradingViaAuthoring(registry: registry).session.project;

  // 遥测管道（§24/§30.1）——监控数据面：运行时拦截事件（页面浏览、
  // 加购/下单采集注记）→ 信封校验队列 → 同源 JSONL 日志，供 ops_admin
  // 管理平台收集聚合。周期 flush 让小批量事件及时落盘。
  final sink = TelemetryLogSink(
    TelemetryLogStore(kv: kv),
    CollectionControl(kv: kv),
  );
  final framework = MicroFlowFramework.create(
    project: project,
    registry: registry,
    environment: 'preview',
    releaseId: 'trading-app-r1',
    telemetrySink: sink,
  );
  Timer.periodic(const Duration(seconds: 2), (_) => framework.telemetry.flush());

  runApp(MicroFlowApp(
    project: project,
    registry: registry,
    runtime: framework.runtime,
  ));
}
