/// 习惯打卡领域存储（宿主侧真实实现，§23 宿主承载）：
/// 习惯与打卡记录持久化为 JSON；打卡幂等键 = 习惯@本地日期；
/// 连续天数按本地日历逐日回溯计算。
library;

import 'dart:convert';

import 'mf_storage.dart';

class HabitStore {
  HabitStore(this.storage);

  final MFKeyValueStore storage;

  static const _habitsKey = 'habits';
  static const _checkinsKey = 'checkins';

  final List<Map<String, Object?>> _habits = [];
  final List<Map<String, Object?>> _checkins = [];

  void load() {
    _habits
      ..clear()
      ..addAll(_readList(_habitsKey));
    _checkins
      ..clear()
      ..addAll(_readList(_checkinsKey));
  }

  List<Map<String, Object?>> _readList(String key) {
    final raw = storage.read(key);
    if (raw == null || raw.isEmpty) return const [];
    return [
      for (final e in jsonDecode(raw) as List) (e as Map).cast<String, Object?>(),
    ];
  }

  void _persist() {
    storage.write(_habitsKey, jsonEncode(_habits));
    storage.write(_checkinsKey, jsonEncode(_checkins));
  }

  /// 本地日期键（打卡幂等与连击按用户本地日历）。
  static String dayKey(DateTime at) =>
      '${at.year}-${at.month.toString().padLeft(2, '0')}-${at.day.toString().padLeft(2, '0')}';

  Map<String, Object?> createHabit(String name, String icon) {
    final now = DateTime.now();
    final habit = <String, Object?>{
      'id': 'h-${now.millisecondsSinceEpoch}',
      'name': name,
      'icon': icon,
      'created': now.toUtc().toIso8601String(),
    };
    _habits.add(habit);
    _persist();
    return habit;
  }

  /// 打卡：同一习惯同一天幂等（重复打卡返回既有记录，不产生第二条）。
  Map<String, Object?> checkIn(String habitId, {DateTime? at}) {
    final now = at ?? DateTime.now();
    final day = dayKey(now);
    final existing = _checkins.where((c) => c['habit'] == habitId && c['day'] == day).toList();
    if (existing.isNotEmpty) {
      return {
        'record_id': existing.first['id'],
        'duplicate': true,
        'streak': streakOf(habitId, at: now),
        'day': day,
      };
    }
    final record = <String, Object?>{
      'id': 'ci-${now.millisecondsSinceEpoch}-$habitId',
      'habit': habitId,
      'day': day,
      'at': now.toUtc().toIso8601String(),
    };
    _checkins.add(record);
    _persist();
    return {
      'record_id': record['id'],
      'duplicate': false,
      'streak': streakOf(habitId, at: now),
      'day': day,
    };
  }

  /// 连续天数：自今天（今天未打卡则自昨天）向过去逐日回溯连续打卡的长度。
  int streakOf(String habitId, {DateTime? at}) {
    final days = {
      for (final c in _checkins)
        if (c['habit'] == habitId) c['day'] as String,
    };
    if (days.isEmpty) return 0;
    var cursor = at ?? DateTime.now();
    if (!days.contains(dayKey(cursor))) {
      cursor = cursor.subtract(const Duration(days: 1));
      if (!days.contains(dayKey(cursor))) return 0;
    }
    var streak = 0;
    while (days.contains(dayKey(cursor))) {
      streak++;
      cursor = cursor.subtract(const Duration(days: 1));
    }
    return streak;
  }

  bool _doneToday(String habitId) =>
      _checkins.any((c) => c['habit'] == habitId && c['day'] == dayKey(DateTime.now()));

  int totalOf(String habitId) => _checkins.where((c) => c['habit'] == habitId).length;

  /// 列表页数据源：行内携带渲染所需的一切字段（声明式列表绑定消费）。
  Map<String, Object?> snapshot() {
    final habits = _habits;
    final done = habits.where((h) => _doneToday(h['id'] as String)).length;
    return {
      'habits': [
        for (final h in habits)
          {
            'id': h['id'],
            'name': h['name'],
            'icon': h['icon'],
            'streakLabel': '连续 ${streakOf(h['id'] as String)} 天',
            'actionLabel': _doneToday(h['id'] as String) ? '已打卡' : '打卡',
          },
      ],
      'label': '今日 $done/${habits.length}',
    };
  }

  /// 统计页数据源。
  Map<String, Object?> statsAll() {
    final stats = [
      for (final h in _habits)
        {
          'id': h['id'],
          'name': h['name'],
          'icon': h['icon'],
          'streakLabel': '连续 ${streakOf(h['id'] as String)} 天',
          'totalLabel': '累计 ${totalOf(h['id'] as String)} 次'
              '${totalOf(h['id'] as String) > 0 ? ' · 今日${_doneToday(h['id'] as String) ? '已完成' : '未完成'}' : ''}',
        },
    ];
    final recent = [
      for (final c in _sortedRecent())
        {
          'habit': _habitName(c['habit'] as String),
          'timeLabel': _fmtLocal(c['at'] as String),
        },
    ];
    return {'stats': stats, 'recent': recent};
  }

  List<Map<String, Object?>> _sortedRecent() {
    final sorted = [..._checkins]..sort((a, b) => (b['at'] as String).compareTo(a['at'] as String));
    return sorted.take(10).toList(growable: false);
  }

  String _habitName(String id) {
    for (final h in _habits) {
      if (h['id'] == id) return h['name'] as String;
    }
    return '已删除习惯';
  }

  static String _fmtLocal(String isoUtc) {
    final t = DateTime.parse(isoUtc).toLocal();
    return '${dayKey(t).substring(5)} ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }
}
