// 纯模型与运行时测试（VM）：静态校验门禁、领域逻辑、以及解释运行时驱动
// 的完整用户流程（页面进入、声明式列表、打卡切换、导航、统计、删除）。
// 持久化介质以 HabitDataAccess 的内存实现承载；真实 localStorage 路径在
// browser_test（-p chrome）覆盖。
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'package:habit_tracker/functions.dart';
import 'package:habit_tracker/habit_data.dart';
import 'package:habit_tracker/habit_logic.dart';
import 'package:habit_tracker/project.dart';
import 'package:habit_tracker/registry.dart';

/// 测试夹具：接口的内存实现（测试基础设施，不在产品代码内）。
class InMemoryHabitData implements HabitDataAccess {
  List<Habit> habits = [];
  List<CheckinRecord> records = [];

  @override
  ({List<Habit> habits, List<CheckinRecord> records}) load() =>
      (habits: List.of(habits), records: List.of(records));

  @override
  void save({required List<Habit> habits, required List<CheckinRecord> records}) {
    this.habits = List.of(habits);
    this.records = List.of(records);
  }
}

void main() {
  group('静态校验门禁', () {
    test('完整项目通过校验：页面树、绑定锚点、导航可达、状态成员、样式 token', () {
      final data = InMemoryHabitData();
      final registry = buildBaseRegistry();
      registerHabitFunctions(registry, data);
      final result = MFValidator(project: buildHabitProject(), registry: registry).validate();
      expect(
        [for (final d in result.diagnostics) '$d'],
        isEmpty,
        reason: '不应有任何诊断（含 warning）：${result.diagnostics}',
      );
    });
  });

  group('领域逻辑', () {
    test('localDateKey 与 currentStreak：今天未打卡从昨天起算', () {
      final today = DateTime(2026, 10, 25);
      expect(localDateKey(today), '2026-10-25');
      expect(currentStreak(['2026-10-25', '2026-10-24', '2026-10-23'], today), 3);
      expect(currentStreak(['2026-10-24', '2026-10-23'], today), 2);
      expect(currentStreak(['2026-10-21'], today), 0);
      expect(currentStreak(const [], today), 0);
    });

    test('bestStreak 与窗口完成数', () {
      final today = DateTime(2026, 10, 25);
      final dates = ['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-10', '2026-10-24', '2026-10-25'];
      expect(bestStreak(dates), 3);
      expect(checkedCountInWindow(dates, today, 7), 2);
      expect(checkedCountInWindow(dates, today, 30), 6);
      expect(checkedCountInWindow(const [], today, 7), 0);
    });

    test('buildTodayItems：今日状态、连续天数与动作文案', () {
      final now = DateTime(2026, 10, 25, 20);
      final habits = [
        Habit(id: 'h1', name: '晨跑', icon: 'star', createdAtUtc: '2026-10-01T00:00:00.000Z'),
        Habit(id: 'h2', name: '阅读', icon: 'list', createdAtUtc: '2026-10-02T00:00:00.000Z'),
      ];
      final records = [
        CheckinRecord(habitId: 'h1', date: '2026-10-25'),
        CheckinRecord(habitId: 'h1', date: '2026-10-24'),
        CheckinRecord(habitId: 'h2', date: '2026-10-20'),
      ];
      final items = buildTodayItems(habits, records, now);
      expect(items[0]['done'], true);
      expect(items[0]['actionLabel'], '取消打卡');
      expect(items[0]['variant'], 'secondary');
      expect(items[0]['streakText'], '连续 2 天');
      expect(items[1]['done'], false);
      expect(items[1]['actionLabel'], '打卡');
      expect(items[1]['streakText'], '连续 0 天');
    });
  });

  group('解释运行时全流程', () {
    testWidgets('建习惯 → 打卡 → 统计 → 删除；onEnter 加载与零埋点事件产出', (tester) async {
      final data = InMemoryHabitData();
      final registry = buildBaseRegistry();
      registerHabitFunctions(registry, data);
      final project = buildHabitProject();
      final emission = MFNullEmissionSink();
      final runtime = MFRuntime(
        project: project,
        registry: registry,
        ids: MFInstanceIdentifiers(projectId: 'habit-tracker', releaseId: 'r-test', environment: 'dev'),
        emissionSink: emission,
      );
      // 先启动运行时再渲染（与框架测试一致）：入口页 onEnter 在渲染前执行。
      await runtime.start();

      await tester.pumpWidget(MicroFlowApp(project: project, registry: registry, runtime: runtime));
      await tester.pumpAndSettle();

      // onEnter 加载：空状态文案可见（锚点 <pageId>.onEnter 语义探针）。
      expect(find.text('今日打卡'), findsOneWidget);
      expect(find.text('还没有习惯，先去「习惯管理」添加一个吧'), findsOneWidget);
      expect(find.text('已完成 0/0'), findsOneWidget);

      // 导航：习惯管理 → 创建习惯。
      await tester.tap(find.text('习惯管理'));
      await tester.pumpAndSettle();
      expect(find.text('习惯管理'), findsWidgets);
      await tester.enterText(find.byType(TextFormField), '晨跑');
      await tester.tap(find.text('添加'));
      await tester.pumpAndSettle();
      // 输入框自持编辑态仍显示「晨跑」，列表行新增同名行。
      expect(find.text('晨跑'), findsNWidgets(2));
      expect(find.text('累计 0 次'), findsOneWidget);
      expect(data.habits.single.name, '晨跑', reason: '适配器真实写持久层');

      // 空名称校验反馈（fn 返回 error，绑定写状态显示）。
      await tester.enterText(find.byType(TextFormField), '  ');
      await tester.tap(find.text('添加'));
      await tester.pumpAndSettle();
      expect(find.text('习惯名称不能为空'), findsOneWidget);

      // 返回今日 → 列表渲染 → 打卡切换。
      await tester.tap(find.text('返回今日'));
      await tester.pumpAndSettle();
      expect(find.text('已完成 0/1'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, '打卡'));
      await tester.pumpAndSettle();
      expect(find.text('已完成 1/1'), findsOneWidget);
      expect(find.text('取消打卡'), findsOneWidget);
      expect(find.text('连续 1 天'), findsOneWidget);
      expect(data.records.single.date, localDateKey(DateTime.now()));

      // 再次点击 = 取消打卡。
      await tester.tap(find.widgetWithText(OutlinedButton, '取消打卡'));
      await tester.pumpAndSettle();
      expect(find.text('已完成 0/1'), findsOneWidget);
      expect(find.text('打卡'), findsOneWidget);

      // 恢复打卡后查看统计。
      await tester.tap(find.widgetWithText(FilledButton, '打卡'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('数据统计'));
      await tester.pumpAndSettle();
      expect(find.text('累计打卡'), findsOneWidget);
      expect(find.text('1'), findsWidgets, reason: '累计打卡与活跃天数均为 1');
      expect(find.text('1/7'), findsOneWidget);
      expect(find.text('1/30'), findsOneWidget);

      // 删除习惯：列表清空，记录级联删除。
      await tester.tap(find.text('习惯管理'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('删除'));
      await tester.pumpAndSettle();
      expect(find.text('还没有习惯，在上方输入名称创建第一个习惯'), findsOneWidget);
      expect(data.habits, isEmpty);
      expect(data.records, isEmpty);

      // 运行时零埋点：页面浏览/功能使用/注记事件全部经拦截边界产出。
      expect(emission.emitted, greaterThan(10), reason: '标准事件族 + 注记事件（§24.7）');
    });
  });
}
