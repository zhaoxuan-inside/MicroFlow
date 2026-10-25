/// 业务函数与数据适配器（§10/§40）：注册进 [MFRegistry] 的真实实现。
///
/// 打卡/删除等有业务含义的调用以采集注记（§24.7，基线 8）声明运营事件，
/// 事件由运行时零埋点发射并走完整采集管道；业务代码不做任何手工上报。
/// 每个函数在契约中声明 output Schema（§40.3，基线 4）：不符输出是类型化
/// 错误，不静默截断。
library;

import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'habit_data.dart';
import 'habit_logic.dart';

/// 打卡动作图标池：创建习惯时按既有数量轮转取用（渲染端 Icon 名闭合集）。
const _iconPool = ['star', 'home', 'person', 'list', 'settings', 'search', 'info', 'stats'];

/// 注册习惯打卡平台的全部业务资源。所有实现即时读写 [HabitDataAccess]。
void registerHabitFunctions(MFRegistry registry, HabitDataAccess data) {
  registry.register(
    'function',
    'fn.habits.today',
    const ComponentContract(
      props: {
        'output': TObject(requiredKeys: ['items', 'summary', 'emptyText']),
      },
    ),
    MFFunctionImpl((args) async {
      final snapshot = data.load();
      final items = buildTodayItems(snapshot.habits, snapshot.records, DateTime.now());
      final done = items.where((i) => i['done'] == true).length;
      return {
        'items': items,
        'summary': '已完成 $done/${items.length}',
        'emptyText':
            snapshot.habits.isEmpty ? '还没有习惯，先去「习惯管理」添加一个吧' : '',
      };
    }, timeoutMs: 3000),
    description: '读取今日打卡视图（今日状态、连续天数、汇总）',
  );

  registry.register(
    'adapter',
    'adapter.habits.toggle',
    const ComponentContract(
      props: {
        'output': TObject(requiredKeys: ['habitId', 'done']),
      },
      // 采集注记（§24.7）：打卡触点声明 ops.habit.checked-in，参数键
      // habitId/name 进入事件 payload，供管理平台做习惯维度运营统计。
      telemetry: MFTelemetryAnnotation(
        events: {'success': 'ops.habit.checked-in'},
        args: ['habitId', 'name'],
      ),
    ),
    MFAdapterImpl((args) async {
      final habitId = '${args['habitId']}';
      final name = '${args['name']}';
      final snapshot = data.load();
      final today = localDateKey(DateTime.now());
      final existing =
          snapshot.records.where((r) => r.habitId == habitId && r.date == today).toList();
      final checked = existing.isNotEmpty;
      final records = checked
          ? [
              for (final r in snapshot.records)
                if (r.habitId != habitId || r.date != today) r,
            ]
          : [...snapshot.records, CheckinRecord(habitId: habitId, date: today)];
      data.save(habits: snapshot.habits, records: records);
      return {'habitId': habitId, 'name': name, 'done': !checked};
    }, timeoutMs: 3000),
    description: '切换某习惯今日打卡状态（幂等切换，写持久层）',
  );

  registry.register(
    'function',
    'fn.habits.all',
    const ComponentContract(
      props: {
        'output': TObject(requiredKeys: ['items', 'emptyText']),
      },
    ),
    MFFunctionImpl((args) async {
      final snapshot = data.load();
      return {
        'items': buildHabitRows(snapshot.habits, snapshot.records, DateTime.now()),
        'emptyText': snapshot.habits.isEmpty ? '还没有习惯，在上方输入名称创建第一个习惯' : '',
      };
    }, timeoutMs: 3000),
    description: '读取全部习惯（管理页列表）',
  );

  registry.register(
    'adapter',
    'adapter.habits.create',
    const ComponentContract(
      props: {
        'output': TObject(requiredKeys: ['ok', 'error']),
      },
      telemetry: MFTelemetryAnnotation(
        events: {'success': 'ops.habit.created'},
        args: ['name'],
      ),
    ),
    MFAdapterImpl((args) async {
      final name = '${args['name'] ?? ''}'.trim();
      if (name.isEmpty) {
        return {'ok': false, 'error': '习惯名称不能为空'};
      }
      final snapshot = data.load();
      if (snapshot.habits.any((h) => h.name == name)) {
        return {'ok': false, 'error': '已存在同名习惯「$name」'};
      }
      final habit = Habit(
        id: 'h-${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}',
        name: name,
        icon: _iconPool[snapshot.habits.length % _iconPool.length],
        createdAtUtc: DateTime.now().toUtc().toIso8601String(),
      );
      data.save(habits: [...snapshot.habits, habit], records: snapshot.records);
      return {'ok': true, 'error': '', 'name': name};
    }, timeoutMs: 3000),
    description: '创建习惯（名称非空且唯一）',
  );

  registry.register(
    'adapter',
    'adapter.habits.delete',
    const ComponentContract(
      props: {
        'output': TObject(requiredKeys: ['ok']),
      },
      telemetry: MFTelemetryAnnotation(
        events: {'success': 'ops.habit.deleted'},
        args: ['habitId', 'name'],
      ),
    ),
    MFAdapterImpl((args) async {
      final habitId = '${args['habitId']}';
      final name = '${args['name'] ?? ''}';
      final snapshot = data.load();
      data.save(
        habits: snapshot.habits.where((h) => h.id != habitId).toList(),
        records: snapshot.records.where((r) => r.habitId != habitId).toList(),
      );
      return {'ok': true, 'habitId': habitId, 'name': name};
    }, timeoutMs: 3000),
    description: '删除习惯及其全部打卡记录',
  );

  registry.register(
    'function',
    'fn.habits.stats',
    const ComponentContract(
      props: {
        'output': TObject(requiredKeys: [
          'items',
          'totalText',
          'activeDaysText',
          'bestStreakText',
          'emptyText',
        ]),
      },
    ),
    MFFunctionImpl((args) async {
      final snapshot = data.load();
      final now = DateTime.now();
      final allDates = snapshot.records.map((r) => r.date);
      final best = snapshot.habits.isEmpty
          ? 0
          : snapshot.habits
              .map((h) => currentStreak(
                  snapshot.records.where((r) => r.habitId == h.id).map((r) => r.date), now))
              .fold(0, (a, b) => a > b ? a : b);
      final bestEver = best > 0 ? best : bestStreak(allDates);
      return {
        'items': buildStatRows(snapshot.habits, snapshot.records, now),
        'totalText': '${snapshot.records.length}',
        'activeDaysText': '${allDates.toSet().length}',
        'bestStreakText': '$bestEver 天',
        'emptyText': snapshot.habits.isEmpty ? '还没有数据，先去打卡吧' : '',
      };
    }, timeoutMs: 3000),
    description: '读取统计视图（累计、活跃天数、最长连续、近 7/30 天窗口）',
  );
}
