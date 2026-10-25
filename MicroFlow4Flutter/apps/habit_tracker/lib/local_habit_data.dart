/// 打卡数据的 localStorage 持久化（业务层承载）：同源键 `mf.habits.data.v1`，
/// JSON 结构 {version, habits, records}。读写即真，无内存影子副本。
library;

import 'dart:convert';

import 'package:mf_platform_store/mf_platform_store.dart';

import 'habit_data.dart';
import 'habit_logic.dart';

class LocalHabitData implements HabitDataAccess {
  LocalHabitData({required this.kv, this.key = defaultKey});

  static const defaultKey = 'mf.habits.data.v1';
  static const version = 1;

  final MFLocalKV kv;
  final String key;

  @override
  ({List<Habit> habits, List<CheckinRecord> records}) load() {
    final raw = kv.read(key);
    if (raw == null || raw.isEmpty) return (habits: const [], records: const []);
    final decoded = jsonDecode(raw);
    if (decoded is! Map) return (habits: const [], records: const []);
    final habits = [
      for (final h in (decoded['habits'] as List? ?? const []))
        if (h is Map) Habit.fromJson(h.cast<String, Object?>()),
    ];
    final records = [
      for (final r in (decoded['records'] as List? ?? const []))
        if (r is Map) CheckinRecord.fromJson(r.cast<String, Object?>()),
    ];
    return (habits: habits, records: records);
  }

  @override
  void save({required List<Habit> habits, required List<CheckinRecord> records}) {
    kv.write(
      key,
      jsonEncode({
        'version': version,
        'habits': [for (final h in habits) h.toJson()],
        'records': [for (final r in records) r.toJson()],
      }),
    );
  }
}
