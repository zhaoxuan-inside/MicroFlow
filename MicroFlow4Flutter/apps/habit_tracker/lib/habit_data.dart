/// 打卡数据访问面：领域逻辑与持久化介质之间的契约。生产实现落在本应用的
/// localStorage（`local_habit_data.dart`），同源管理平台不直接读取本数据。
library;

import 'habit_logic.dart';

abstract interface class HabitDataAccess {
  ({List<Habit> habits, List<CheckinRecord> records}) load();

  void save({required List<Habit> habits, required List<CheckinRecord> records});
}
