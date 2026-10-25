/// 运营管理平台（纯 Web）：MicroFlow 框架解释运行模式（§13.3）。
///
/// 业务层职责（§27 责任矩阵）：注册真实运营函数（ops_functions.dart，读
/// 同源共享遥测日志）、提供本实例的遥测接收端（自身的运营事件同样落盘
/// 收集）、把跨标签页存储事件接到当前页面的加载绑定上实现日志实时收集、
/// 装配框架并启动。
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mf_platform_store/mf_platform_store.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'download.dart';
import 'ops_functions.dart';
import 'project.dart';
import 'registry.dart';

void main() {
  final kv = const MFLocalKV();
  final logStore = TelemetryLogStore(kv: kv);
  final control = CollectionControl(kv: kv);
  late final MicroFlowFramework framework;
  final registry = buildBaseRegistry();
  registerOpsFunctions(
    registry,
    logStore,
    control,
    queueQuality: () => framework.telemetry.dataQuality(),
    downloadFile: downloadText,
  );
  final project = buildOpsProject();

  final sink = TelemetryLogSink(logStore, control);
  final themeSelection = ValueNotifier<String>('theme-light');
  framework = MicroFlowFramework.create(
    project: project,
    registry: registry,
    environment: 'preview',
    releaseId: 'ops-admin-r1',
    telemetrySink: sink,
    themeProvider: () => themeSelection.value,
  );

  // 小批量事件及时落盘（§24.2 批量预算之外的业务层承载）。
  Timer.periodic(const Duration(seconds: 2), (_) => framework.telemetry.flush());

  // 跨标签页日志实时收集：采集端写入共享日志后，重新执行当前页的加载
  // 绑定，页面数据即随最新事件更新。
  const refreshBindings = <String, String>{
    'overview-page': 'overview-refresh',
    'pages-page': 'pages-refresh',
    'features-page': 'features-refresh',
    'logs-page': 'logs-query',
    'collection-page': 'collection-enter',
  };
  onStorageChanged(() {
    final current = framework.runtime.current;
    if (current == null) return;
    final bindingId = refreshBindings[current.definition.id];
    if (bindingId != null) {
      framework.runtime.execute(bindingId);
    }
  });

  runApp(MicroFlowApp(
    project: project,
    registry: registry,
    runtime: framework.runtime,
    themeSelection: themeSelection,
    themeNames: const ['theme-light', 'theme-dark'],
    onThemeSelected: (themeId) {
      themeSelection.value = themeId;
      final current = framework.runtime.current;
      if (current != null) {
        framework.runtime.push(current.definition.id, kind: 'replace');
      }
    },
  ));
}
