// 浏览器端到端（-p chrome，真实 localStorage）：同一浏览器档案里先以
// 打卡平台的真实运行时产生运营事件（建习惯/打卡），再渲染管理平台验证
// 页面消费同一份真实共享日志；导出与采集控制以真实绑定直执行验证（按钮
// 级 UI 交互由真实浏览器 GUI 验证覆盖）。静态校验门禁也在此执行
// （dart:js_interop 在 VM 不可用）。
//
// 运行：flutter test --platform chrome
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:habit_tracker/functions.dart' as habit;
import 'package:habit_tracker/local_habit_data.dart' as habit;
import 'package:habit_tracker/project.dart' as habit;
import 'package:habit_tracker/registry.dart' as habit;
import 'package:mf_platform_store/mf_platform_store.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'package:ops_admin/download.dart';
import 'package:ops_admin/ops_functions.dart';
import 'package:ops_admin/project.dart';
import 'package:ops_admin/registry.dart';

void main() {
  late MFLocalKV kv;
  late TelemetryLogStore logStore;
  late CollectionControl control;
  late MFProject opsProject;
  late MFRegistry opsRegistry;
  late MicroFlowFramework opsFramework;

  setUp(() async {
    kv = const MFLocalKV();
    for (final key in [
      habit.LocalHabitData.defaultKey,
      TelemetryLogStore.defaultKey,
      TelemetryLogStore.controlKey,
    ]) {
      kv.remove(key);
    }
    logStore = TelemetryLogStore(kv: kv);
    control = CollectionControl(kv: kv);

    // 静态校验门禁（含全部注册资源）。
    opsRegistry = buildBaseRegistry();
    registerOpsFunctions(
      opsRegistry,
      logStore,
      control,
      queueQuality: () => const {},
      downloadFile: downloadText,
    );
    opsProject = buildOpsProject();
    final validation = MFValidator(project: opsProject, registry: opsRegistry).validate();
    expect(
      [for (final d in validation.diagnostics) '$d'],
      isEmpty,
      reason: '管理平台项目不应有任何诊断：${validation.diagnostics}',
    );
    opsFramework = MicroFlowFramework.create(
      project: opsProject,
      registry: opsRegistry,
      environment: 'dev',
      releaseId: 'ops-admin-test-r1',
      telemetrySink: TelemetryLogSink(logStore, control),
    );
  });

  /// 生产端：真实打卡运行时建习惯并打卡（绑定链直执行，不渲染 UI）。
  Future<void> produceHabitWithCheckin() async {
    final producerRegistry = habit.buildBaseRegistry();
    habit.registerHabitFunctions(producerRegistry, habit.LocalHabitData(kv: kv));
    final producerProject = habit.buildHabitProject();
    final producerQueue = MFTelemetryQueue(sink: TelemetryLogSink(logStore, control), batchMax: 64);
    final producer = MFRuntime(
      project: producerProject,
      registry: producerRegistry,
      ids: MFInstanceIdentifiers(projectId: 'habit-tracker', releaseId: 'habit-r1', environment: 'dev'),
      emissionSink: producerQueue,
    );
    await producer.start();
    await producer.push('habits-page');
    await producer.execute('habits-mirror-draft', props: {'value': '晨跑'});
    await producer.execute('habits-create');
    final habitItems = producer.state.peek('page', 'habitItems') as List?;
    final habitId = '${(habitItems!.first as Map)['id']}';
    await producer.push('today-page');
    await producer.execute('today-check', item: {'id': habitId, 'name': '晨跑'});
    await producerQueue.flush();
  }

  Future<void> pumpAdmin(WidgetTester tester) async {
    await opsFramework.runtime.start();
    await tester.pumpWidget(MicroFlowApp(
      project: opsProject,
      registry: opsRegistry,
      runtime: opsFramework.runtime,
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('管理平台页面消费真实共享日志：概览/页面/功能/日志', (tester) async {
    tester.view.physicalSize = const Size(1600, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await produceHabitWithCheckin();
    await pumpAdmin(tester);

    // 概览：KPI 与习惯维度行来自真实事件。
    expect(find.text('运营概览'), findsOneWidget);
    expect(find.text('打卡次数'), findsOneWidget);
    expect(find.text('晨跑'), findsOneWidget);

    // 页面分析：生产端浏览过 /today 与 /habits 路由。
    await opsFramework.runtime.execute('go-ov-pg');
    await tester.pumpAndSettle();
    expect(find.text('/today'), findsOneWidget);
    expect(find.text('/habits'), findsOneWidget);

    // 功能使用：ops.feature.used 的 feature_ref 是绑定 id。
    await opsFramework.runtime.execute('go-ov-ft');
    await tester.pumpAndSettle();
    expect(find.text('today-check'), findsOneWidget);
    expect(find.text('today-enter'), findsOneWidget);

    // 日志检索：真实分页查询，事件行可见。
    await opsFramework.runtime.execute('go-ov-lg');
    await tester.pumpAndSettle();
    expect(find.textContaining('共 '), findsOneWidget);
    expect(find.text('ops.habit.checked-in'), findsOneWidget);
  });

  testWidgets('导出与采集控制绑定执行（真实适配器与共享开关）', (tester) async {
    tester.view.physicalSize = const Size(1600, 1000);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await produceHabitWithCheckin();
    await opsFramework.runtime.start();

    // 导出：exportevents 协议 + 真实文件下载，结果文案写回页面状态。
    await opsFramework.runtime.push('export-page');
    await opsFramework.runtime.execute('export-run');

    final exportResult =
        '${opsFramework.runtime.state.peek('page', 'exportResult')}';
    expect(exportResult, startsWith('已导出'), reason: '导出结果写回状态：$exportResult');
    expect(exportResult, contains('缺口区间 0 个'));

    // 采集控制：切换绑定写共享开关并回写状态。
    await opsFramework.runtime.push('collection-page');
    expect(
      opsFramework.runtime.state.peek('page', 'statusText'),
      '采集进行中',
      reason: 'onEnter 装载采集状态',
    );
    await opsFramework.runtime.execute('collection-toggle');
    expect(opsFramework.runtime.state.peek('page', 'statusText'), '采集已暂停');
    expect(control.enabled, isFalse, reason: '开关写入共享控制面');
    await opsFramework.runtime.execute('collection-toggle');
    expect(opsFramework.runtime.state.peek('page', 'statusText'), '采集进行中');
    expect(control.enabled, isTrue);
  });
}
