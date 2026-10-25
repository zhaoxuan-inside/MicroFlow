// 浏览器端到端（-p chrome，真实 localStorage 与真实遥测管道）：
// 框架装配 → 打卡 → 运营事件落盘（共享 JSONL 日志）→ 采集开关抑制。
// 必须在真实浏览器执行：dart test 框架下无 localStorage。
//
// 运行：flutter test test/browser_test.dart -p chrome
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mf_platform_store/mf_platform_store.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'package:habit_tracker/functions.dart';
import 'package:habit_tracker/local_habit_data.dart';
import 'package:habit_tracker/project.dart';
import 'package:habit_tracker/registry.dart';

void main() {
  late MFLocalKV kv;
  late TelemetryLogStore logStore;
  late CollectionControl control;
  late MFProject project;
  late MFRegistry registry;
  late MicroFlowFramework framework;

  setUp(() async {
    kv = const MFLocalKV();
    for (final key in [
      LocalHabitData.defaultKey,
      TelemetryLogStore.defaultKey,
      TelemetryLogStore.controlKey,
    ]) {
      kv.remove(key);
    }
    logStore = TelemetryLogStore(kv: kv);
    control = CollectionControl(kv: kv);
    registry = buildBaseRegistry();
    registerHabitFunctions(registry, LocalHabitData(kv: kv));
    project = buildHabitProject();
    framework = MicroFlowFramework.create(
      project: project,
      registry: registry,
      environment: 'dev',
      releaseId: 'browser-test-r1',
      telemetrySink: TelemetryLogSink(logStore, control),
    );
  });

  Future<void> pumpApp(WidgetTester tester) async {
    await framework.runtime.start();
    await tester.pumpWidget(MicroFlowApp(
      project: project,
      registry: registry,
      runtime: framework.runtime,
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('打卡数据与运营事件真实落盘；采集关闭后整批抑制', (tester) async {
    await pumpApp(tester);

    // 创建习惯（真实持久化）。
    await tester.tap(find.text('习惯管理'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField), '晨跑');
    await tester.tap(find.text('添加'));
    await tester.pumpAndSettle();
    final habitRaw = kv.read(LocalHabitData.defaultKey);
    expect(habitRaw, isNotNull, reason: '习惯数据写入 localStorage');
    expect(habitRaw!, contains('晨跑'));

    // 打卡 → 注记事件经完整管道进入共享日志。
    await tester.tap(find.text('返回今日'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, '打卡'));
    await tester.pumpAndSettle();
    expect(find.text('已完成 1/1'), findsOneWidget);
    await framework.telemetry.flush();

    final envelopes = logStore.readAll();
    final checkins = [
      for (final e in envelopes)
        if (e['event_name'] == 'ops.habit.checked-in') e,
    ];
    expect(checkins, isNotEmpty, reason: 'ops.habit.checked-in 注记事件落地共享日志');
    final payload = checkins.last['payload'] as Map;
    expect(payload['name'], '晨跑');
    expect(checkins.last['environment'], 'dev');
    expect(checkins.last['release_id'], 'browser-test-r1');

    // 页面浏览/功能使用等标准事件族同样零埋点产出并落盘。
    final names = envelopes.map((e) => e['event_name']).toSet();
    expect(names, containsAll(['ops.page.viewed', 'ops.feature.used']));

    // 管理平台关闭采集 → 新事件整批抑制并计数。
    control.enabled = false;
    await tester.tap(find.widgetWithText(OutlinedButton, '取消打卡'));
    await tester.pumpAndSettle();
    await framework.telemetry.flush();
    expect(logStore.metrics.suppressed, greaterThanOrEqualTo(1));
    final countAfterOff = logStore.readAll().length;
    expect(countAfterOff, envelopes.length, reason: '关闭期间不追加新事件行');

    // 恢复采集后事件继续进入日志。
    control.enabled = true;
    await tester.tap(find.widgetWithText(FilledButton, '打卡'));
    await tester.pumpAndSettle();
    await framework.telemetry.flush();
    expect(logStore.readAll().length, greaterThan(countAfterOff));
  });
}
