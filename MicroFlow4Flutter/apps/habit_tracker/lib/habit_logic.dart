/// 习惯打卡的领域逻辑（纯计算，无平台依赖）：连续天数、窗口完成数、
/// 页面行数据与汇总文案的构建。所有输出行的形状与页面绑定图消费的
/// `item.<field>` 引用一一对应。
library;

/// 习惯定义。
class Habit {
  Habit({required this.id, required this.name, required this.icon, required this.createdAtUtc});

  final String id;
  final String name;
  final String icon;
  final String createdAtUtc;

  Map<String, Object?> toJson() =>
      {'id': id, 'name': name, 'icon': icon, 'createdAtUtc': createdAtUtc};

  static Habit fromJson(Map<String, Object?> json) => Habit(
        id: '${json['id']}',
        name: '${json['name']}',
        icon: '${json['icon']}',
        createdAtUtc: '${json['createdAtUtc']}',
      );
}

/// 打卡记录：习惯 × 本地日期（一天一条）。
class CheckinRecord {
  CheckinRecord({required this.habitId, required this.date});

  final String habitId;
  final String date;

  Map<String, Object?> toJson() => {'habitId': habitId, 'date': date};

  static CheckinRecord fromJson(Map<String, Object?> json) =>
      CheckinRecord(habitId: '${json['habitId']}', date: '${json['date']}');
}

/// 本地日期键（浏览器本地时区的自然日）。
String localDateKey(DateTime at) =>
    '${at.year.toString().padLeft(4, '0')}-'
    '${at.month.toString().padLeft(2, '0')}-'
    '${at.day.toString().padLeft(2, '0')}';

/// 从今天（含）向前数连续打卡天数；今天未打卡则从昨天起算。
int currentStreak(Iterable<String> checkedDates, DateTime today) {
  final days = checkedDates.toSet();
  var cursor = DateTime(today.year, today.month, today.day);
  if (!days.contains(localDateKey(cursor))) {
    cursor = cursor.subtract(const Duration(days: 1));
  }
  var streak = 0;
  while (days.contains(localDateKey(cursor))) {
    streak++;
    cursor = cursor.subtract(const Duration(days: 1));
  }
  return streak;
}

/// 历史最长连续天数。
int bestStreak(Iterable<String> checkedDates) {
  final sorted = checkedDates.toSet().toList()..sort();
  var best = 0;
  var run = 0;
  String? previous;
  for (final day in sorted) {
    final dayTime = DateTime.parse(day);
    run = (previous != null && dayTime.difference(DateTime.parse(previous)).inDays == 1)
        ? run + 1
        : 1;
    previous = day;
    if (run > best) best = run;
  }
  return best;
}

int checkedCountInWindow(Iterable<String> checkedDates, DateTime today, int days) {
  final from = localDateKey(today.subtract(Duration(days: days - 1)));
  return checkedDates.where((d) => d.compareTo(from) >= 0 && d.compareTo(localDateKey(today)) <= 0).length;
}

String _shortDate(String isoUtc, DateTime now) {
  final local = DateTime.tryParse(isoUtc)?.toLocal() ?? now;
  return '${local.month.toString().padLeft(2, '0')}-${local.day.toString().padLeft(2, '0')}';
}

/// 今日页行数据：每行一个习惯，含今日状态、连续天数与动作按钮文案。
List<Map<String, Object?>> buildTodayItems(
  List<Habit> habits,
  List<CheckinRecord> records,
  DateTime now,
) {
  final today = localDateKey(now);
  final checkedToday = records.where((r) => r.date == today).map((r) => r.habitId).toSet();
  return [
    for (final habit in habits)
      () {
        final dates = records.where((r) => r.habitId == habit.id).map((r) => r.date);
        final done = checkedToday.contains(habit.id);
        return {
          'id': habit.id,
          'name': habit.name,
          'icon': habit.icon,
          'done': done,
          'streakText': '连续 ${currentStreak(dates, now)} 天',
          'actionLabel': done ? '取消打卡' : '打卡',
          'variant': done ? 'secondary' : 'primary',
        };
      }(),
  ];
}

/// 习惯管理页行数据：创建日期与累计打卡次数。
List<Map<String, Object?>> buildHabitRows(
  List<Habit> habits,
  List<CheckinRecord> records,
  DateTime now,
) {
  return [
    for (final habit in habits)
      {
        'id': habit.id,
        'name': habit.name,
        'icon': habit.icon,
        'createdAtText': '建于 ${_shortDate(habit.createdAtUtc, now)}',
        'checkinsText': '累计 ${records.where((r) => r.habitId == habit.id).length} 次',
      },
  ];
}

/// 统计页行数据：每个习惯的累计、当前连续与近 7/30 天完成数。
List<Map<String, Object?>> buildStatRows(
  List<Habit> habits,
  List<CheckinRecord> records,
  DateTime now,
) {
  return [
    for (final habit in habits)
      () {
        final dates = records.where((r) => r.habitId == habit.id).map((r) => r.date);
        return {
          'id': habit.id,
          'name': habit.name,
          'totalText': '${dates.length}',
          'streakText': '${currentStreak(dates, now)} 天',
          'last7Text': '${checkedCountInWindow(dates, now, 7)}/7',
          'last30Text': '${checkedCountInWindow(dates, now, 30)}/30',
        };
      }(),
  ];
}
