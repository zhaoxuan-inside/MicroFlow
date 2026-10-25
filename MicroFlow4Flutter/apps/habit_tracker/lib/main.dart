/// 个人习惯打卡平台（纯 Web）：MicroFlow 框架解释运行模式（§13.3）。
///
/// 业务层职责（§27 责任矩阵）只有三件事：注册真实资源实现（functions.dart）、
/// 提供遥测接收端（mf_platform_store 的 JSONL 落地 sink，供同源管理平台
/// 收集）、装配框架并启动。页面、交互与采集注记全部由项目模型声明。
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mf_platform_store/mf_platform_store.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'functions.dart';
import 'local_habit_data.dart';
import 'project.dart';
import 'registry.dart';

void main() {
  final kv = const MFLocalKV();
  final registry = buildBaseRegistry();
  registerHabitFunctions(registry, LocalHabitData(kv: kv));
  final project = buildHabitProject();

  // 遥测管道（§24/§30.1）：运行时拦截事件 → 信封校验队列 → 同源 JSONL
  // 日志。采集开关由管理平台控制；周期 flush 让小批量事件及时落盘。
  final sink = TelemetryLogSink(
    TelemetryLogStore(kv: kv),
    CollectionControl(kv: kv),
  );
  final themeSelection = ValueNotifier<String>('theme-light');
  final framework = MicroFlowFramework.create(
    project: project,
    registry: registry,
    environment: 'preview',
    releaseId: 'habit-tracker-r1',
    telemetrySink: sink,
    themeProvider: () => themeSelection.value,
  );
  Timer.periodic(const Duration(seconds: 2), (_) => framework.telemetry.flush());

  runApp(MicroFlowApp(
    project: project,
    registry: registry,
    runtime: framework.runtime,
    themeSelection: themeSelection,
    themeNames: const ['theme-light', 'theme-dark'],
    onThemeSelected: (themeId) {
      // 双层主题切换（§36.3，基线 7）：只影响新建实例——重建当前页。
      themeSelection.value = themeId;
      final current = framework.runtime.current;
      if (current != null) {
        framework.runtime.push(current.definition.id, kind: 'replace');
      }
    },
  ));
}
