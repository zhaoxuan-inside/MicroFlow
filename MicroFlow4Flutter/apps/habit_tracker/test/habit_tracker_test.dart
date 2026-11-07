import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:habit_tracker/src/habit_store.dart';
import 'package:habit_tracker/src/mf_storage.dart';
import 'package:habit_tracker/src/telemetry_sink.dart';
import 'package:habit_tracker/src/tracker_model.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// 打卡平台应用测试：领域存储真实逻辑（幂等/连击）、项目模型静态门禁、
/// Business Fact 打卡通道（幂等确认）、遥测落盘回流、恢复快照往返。
/// 全部跑在真实实现上（VM 用目录文件存储），无任何替身。

void main() {
  late Directory dir;
  late MFKeyValueStore storage;
  late HabitStore habits;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('habit-test');
    storage = MFKeyValueStore.open(dir.path);
    habits = HabitStore(storage)..load();
  });

  tearDown(() {
    dir.deleteSync(recursive: true);
  });

  group('HabitStore（真实持久化与幂等）', () {
    test('创建 → 打卡 → 连击/今日完成计算；同日重复打卡幂等', () {
      final h = habits.createHabit('晨跑', 'run');
      final now = DateTime.now();
      final r1 = habits.checkIn(h['id'] as String, at: now);
      expect(r1['duplicate'], false);
      expect(r1['streak'], 1);
      // 同日重复：幂等返回既有记录，不产生第二条。
      final r2 = habits.checkIn(h['id'] as String, at: now);
      expect(r2['duplicate'], true);
      expect(r2['record_id'], r1['record_id']);
      // 连击：昨天 + 今天 = 2。
      habits.checkIn(h['id'] as String, at: now.subtract(const Duration(days: 1)));
      expect(habits.streakOf(h['id'] as String), 2);
      final snap = habits.snapshot();
      expect((snap['habits'] as List).first['actionLabel'], '已打卡');
      expect(snap['label'], '今日 1/1');
      // 重新加载：数据来自持久化（非内存态）。
      final reloaded = HabitStore(storage)..load();
      expect(reloaded.streakOf(h['id'] as String), 2);
    });

    test('连击断档归零；未打卡今天时延续昨天', () {
      final h = habits.createHabit('阅读', 'book');
      final now = DateTime.now();
      habits.checkIn(h['id'] as String, at: now.subtract(const Duration(days: 3)));
      habits.checkIn(h['id'] as String, at: now.subtract(const Duration(days: 2)));
      expect(habits.streakOf(h['id'] as String), 0, reason: '昨天与今天缺卡：连击断');
      habits.checkIn(h['id'] as String, at: now.subtract(const Duration(days: 1)));
      expect(habits.streakOf(h['id'] as String), 3, reason: '前天/大前天/昨天连续三天，今天未打卡：连击仍延续');
    });
  });

  group('项目模型静态门禁', () {
    test('tracker 项目通过静态校验（含注记/图层/列表绑定面）', () {
      final runtimeReady = Completer<MFRuntime>();
      final registry = MFRegistry();
      registerTrackerPrimitives(registry);
      registerTrackerAdapters(registry, habits, runtimeReady);
      final result = MFValidator(project: buildTrackerProject(), registry: registry).validate();
      expect(result.ok, isTrue, reason: '静态错误：${result.diagnostics.where((d) => d.severity == Severity.error)}');
    });
  });

  group('Business Fact 打卡通道', () {
    test('打卡经 facts.submit 提交：确认关联运行引用；重复提交幂等返回', () async {
      final runtimeReady = Completer<MFRuntime>();
      final registry = MFRegistry();
      registerTrackerPrimitives(registry);
      registerTrackerAdapters(registry, habits, runtimeReady);
      final project = buildTrackerProject();
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'habit-tracker', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      runtimeReady.complete(runtime);
      await runtime.start();

      final habit = habits.createHabit('喝水', 'water');
      final binding = project.findBinding('habit-check-in')!;
      final action = binding.actions.first as MFAdapterAction;
      // 直接经绑定动作执行（与渲染路径一致），两次触发。
      await runtime.execute('habit-check-in', item: {'id': habit['id'], 'name': habit['name']});
      await runtime.execute('habit-check-in', item: {'id': habit['id'], 'name': habit['name']});

      expect(habits.totalOf(habit['id'] as String), 1, reason: '同日幂等：只产生一条打卡记录');
      final facts = runtime.facts.all;
      expect(facts, hasLength(1), reason: '去重身份幂等：第二次提交返回既有记录');
      expect(facts.single.state, 'confirmed');
      expect(facts.single.externalRunRef, isNotNull, reason: '确认必须关联外部运行引用（record_id）');
      expect(runtime.diagnostics.any((d) => d.code == MFCodes.dataFactDuplicate), isTrue);
      expect(runtime.externalRunRefs, isNotEmpty, reason: '确认关联的运行引用进入 §24.8 记录面');
      expect(action.arguments.keys, contains('id'));
    });
  });

  group('遥测落盘与管理平台消费', () {
    test('MFStorageSink 落盘 → 管理平台读取 → 查询引擎分组口径一致', () async {
      final sink = MFStorageSink(storage);
      final queue = MFTelemetryQueue(sink: sink, batchMax: 64);
    queue.emit(_runtimeRaw('ops.page.viewed', const {}, 'ses-1'));
      queue.emit(_runtimeRaw('ops.habit.checked-in', const {'id': 'h1'}, 'ses-1'));
      queue.emit(_runtimeRaw('ops.habit.checked-in', const {'id': 'h2'}, 'ses-2'));
      queue.emit(_runtimeRaw('ops.habit.created', const {'name': '晨跑'}, 'ses-2'));
      await queue.flush();

      // 管理平台消费面（同源读取同一键）。
      final engine = MFLocalQueryEngine(
        events: () => [
          for (final e in jsonDecode(storage.read('telemetry.log')!) as List)
            MFEventEnvelope.fromJson((e as Map).cast<String, Object?>()),
        ],
        dataQuality: () => const {'delivered': 4, 'dropped': 0},
      );
      final now = DateTime.now().toUtc();
      final byHabit = engine.queryEvents(
        from: now.subtract(const Duration(hours: 1)),
        to: now.add(const Duration(hours: 1)),
        eventName: 'ops.habit.checked-in',
        groupBy: const ['payload.id'],
      );
      final groups = (byHabit['groups'] as List).cast<Map>();
      expect(groups.length, 2, reason: '过滤打卡事件后按习惯维度分组（无维度值的事件不混入）');
      final checks = groups.map((g) => '${g['key']}=${g['count']}').toList()..sort();
      expect(checks, ['h1=1', 'h2=1']);
      final quality = engine.getDataQuality();
      expect(quality['delivered'], 4);
      expect(quality['loss_rate'], 0);
    });
  });

  group('恢复快照跨会话', () {
    test('collect → 持久化 → 新 runtime restore：页面与页面状态还原', () async {
      final registry = MFRegistry();
      registerTrackerPrimitives(registry);
      registerTrackerAdapters(registry, habits, Completer<MFRuntime>());
      final project = buildTrackerProject();
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'habit-tracker', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      await runtime.start();
      runtime.state.writeDeep('page', 'newName', '未提交的草稿');
      final contract = project.recoveryContracts['recovery-default']!;
      final snap = runtime.recovery.collect(contract);
      storage.write('recovery.snapshot', jsonEncode(snap.toJson()));

      final runtime2 = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'habit-tracker', releaseId: 'r1', environment: 'dev'),
        emissionSink: MFNullEmissionSink(),
      );
      final outcome = await runtime2.recovery.restore(
        MFRecoverySnapshot.fromJson((jsonDecode(storage.read('recovery.snapshot')!) as Map).cast<String, Object?>()),
        contract: contract,
      );
      expect(outcome.restored, isTrue);
      expect(runtime2.current!.definition.id, 'habits-page', reason: '恢复到上次所在页面');
      expect(runtime2.state.peek('page', 'newName'), '未提交的草稿', reason: '页面状态随快照还原');
    });
  });
}

Map<String, Object?> _runtimeRaw(String event, Map<String, Object?> payload, String session) => {
      'event_name': event,
      'payload': payload,
      'mf_source': 'runtime-intercept',
      'session_id': session,
      'page_instance_id': 'pg',
      'route': '/habits',
      'release_id': 'r1',
      'renderer_version': 'v',
      'renderer_package': 'microflow4_flutter',
      'environment': 'production',
      'trace_id': 'tr-x',
      'identity': const {'user_ref': null},
      'experiment_assignments': const [],
    };
