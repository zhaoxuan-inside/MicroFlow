import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'src/habit_store.dart';
import 'src/mf_storage.dart';
import 'src/telemetry_sink.dart';
import 'src/tracker_model.dart';

/// 个人习惯打卡平台 —— MicroFlow4Flutter 模型驱动的纯 Web 应用。
///
/// 全部交互经项目模型 + 绑定映射驱动（零埋点采集、Business Fact 打卡、
/// 声明式列表绑定）；宿主只注册真实实现（HabitStore 本地持久化 + 连击
/// 计算 + §16.1 跨会话恢复），无桩代码、无内存假数据。
void main() {
  final storage = MFKeyValueStore.open();
  final habits = HabitStore(storage)..load();

  final runtimeReady = Completer<MFRuntime>();
  final registry = MFRegistry();
  registerTrackerPrimitives(registry);
  registerTrackerAdapters(registry, habits, runtimeReady);

  final project = buildTrackerProject();
  final validation = MFValidator(project: project, registry: registry).validate();
  if (!validation.ok) {
    throw StateError(
      'habit-tracker 静态校验未通过：${validation.diagnostics.where((d) => d.severity == Severity.error).join('; ')}',
    );
  }

  final fw = MicroFlowFramework.create(
    project: project,
    registry: registry,
    environment: 'production',
    releaseId: 'habit-tracker-r1',
    telemetrySink: MFStorageSink(storage),
  );
  runtimeReady.complete(fw.runtime);

  // 跨会话恢复（§16.1）：启动恢复上次快照（路由 + 参数 + 页面状态 +
  // 声明会话状态）；运行中快照随渲染代持久化，供下次会话恢复。
  _attachRecovery(fw, project, storage);
  _restoreSession(fw.runtime, storage, project.recoveryContracts['recovery-default']!);

  runApp(MicroFlowApp(project: project, registry: registry, runtime: fw.runtime,
      appName: '习惯打卡'));
}

/// 运行中持久化：恢复快照 + 数据质量口径（丢弃计数供管理平台汇总）。
void _attachRecovery(MicroFlowFramework fw, MFProject project, MFKeyValueStore storage) {
  fw.runtime.generation.addListener(() {
    final contract = project.recoveryContracts['recovery-default']!;
    final snapshot = fw.runtime.recovery.collect(contract);
    storage.write('recovery.snapshot', jsonEncode(snapshot.toJson()));
    final q = fw.telemetry.dataQuality();
    final sinkDropped = (fw.telemetry.sink as MFStorageSink).dropped;
    storage.write('telemetry.quality', jsonEncode({
      'queue_dropped': q['dropped'],
      'sink_dropped': sinkDropped,
    }));
  });
}

/// 启动恢复：快照过期/版本不符/release 变化时按契约全新启动（诊断可见）。
Future<void> _restoreSession(MFRuntime runtime, MFKeyValueStore storage, MFRecoveryContract? contract) async {
  final raw = storage.read('recovery.snapshot');
  if (raw == null || contract == null) return;
  try {
    final outcome = await runtime.recovery.restore(
      MFRecoverySnapshot.fromJson((jsonDecode(raw) as Map).cast<String, Object?>()),
      contract: contract,
    );
    for (final d in outcome.diagnostics) {
      runtime.diagSink.add(d);
    }
  } catch (err) {
    runtime.diagSink.add(MFDiag(
      MFCodes.stateSnapshotVersionMismatch,
      '恢复快照不可解析，全新启动：$err',
      stage: Stage.runtime,
      severity: Severity.warning,
    ));
  }
}
