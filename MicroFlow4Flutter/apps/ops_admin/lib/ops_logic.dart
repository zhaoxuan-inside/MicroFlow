/// 运营指标与日志聚合（纯计算，无平台依赖）：输入是框架 §24.2 事件信封
/// 列表，输出是页面绑定图消费的结构化行。全部指标来自真实采集的运营
/// 事件（零埋点标准事件族 + 注记事件），不引入任何样例数据。
library;

import 'package:microflow4_flutter/microflow4_flutter.dart';

String _two(int v) => v.toString().padLeft(2, '0');

String _localTime(String isoUtc) {
  final at = DateTime.tryParse(isoUtc)?.toLocal();
  if (at == null) return '-';
  return '${_two(at.month)}-${_two(at.day)} ${_two(at.hour)}:${_two(at.minute)}:${_two(at.second)}';
}

/// KPI 行：label/value 文本行（页面 List 模板直接消费）。
List<Map<String, Object?>> overviewRows(
  List<MFEventEnvelope> events, {
  required DateTime now,
}) {
  int count(String name) => events.where((e) => e.eventName == name).length;
  final last24h = events
      .where((e) => DateTime.parse(e.occurredAt).isAfter(now.toUtc().subtract(const Duration(hours: 24))))
      .length;
  final sessions = events.map((e) => e.sessionId).toSet().length;
  String valueOf(Object v) => '$v';
  return [
    {'label': '事件总数', 'value': valueOf(events.length)},
    {'label': '会话数', 'value': valueOf(sessions)},
    {'label': '页面浏览', 'value': valueOf(count('ops.page.viewed'))},
    {'label': '页面退出', 'value': valueOf(count('ops.page.left'))},
    {'label': '功能调用', 'value': valueOf(count('ops.feature.used'))},
    {'label': '打卡次数', 'value': valueOf(count('ops.habit.checked-in'))},
    {'label': '近 24 小时事件', 'value': valueOf(last24h)},
  ];
}

/// 数据质量行（§30.1/§30.2 口径）：接收端存储指标 + 采集队列指标。
List<Map<String, Object?>> qualityRows(
  List<MFEventEnvelope> events, {
  required Map<String, Object?> logMetrics,
  required Map<String, Object?> queueQuality,
}) {
  String metric(Map<String, Object?> source, String key) =>
      '${source[key] ?? 0}';
  return [
    {'label': '日志事件行', 'value': '${events.length}'},
    {'label': '容量淘汰（evicted）', 'value': metric(logMetrics, 'evicted')},
    {'label': '采集关闭抑制（suppressed）', 'value': metric(logMetrics, 'suppressed')},
    {'label': '损坏行（corrupt）', 'value': metric(logMetrics, 'corrupt')},
    {'label': '队列待发', 'value': metric(queueQuality, 'queued')},
    {'label': '队列丢弃', 'value': metric(queueQuality, 'dropped')},
    {'label': '队列诊断数', 'value': metric(queueQuality, 'diagnostics')},
  ];
}

/// 页面分析行：每个路由的浏览、退出与平均停留（ops.page.left 的 stay_ms）。
List<Map<String, Object?>> pageRows(List<MFEventEnvelope> events) {
  final views = <String, int>{};
  final exits = <String, int>{};
  final stayMs = <String, int>{};
  for (final e in events) {
    if (e.eventName == 'ops.page.viewed') {
      views[e.route] = (views[e.route] ?? 0) + 1;
    } else if (e.eventName == 'ops.page.left') {
      exits[e.route] = (exits[e.route] ?? 0) + 1;
      stayMs[e.route] = (stayMs[e.route] ?? 0) + ((e.payload['stay_ms'] as num?)?.toInt() ?? 0);
    }
  }
  final routes = {...views.keys, ...exits.keys}.toList()..sort();
  final rows = [
    for (final route in routes)
      {
        'route': route,
        'viewsText': '${views[route] ?? 0}',
        'exitsText': '${exits[route] ?? 0}',
        'avgStayText': (exits[route] ?? 0) == 0
            ? '-'
            : '${(stayMs[route]! / exits[route]! / 1000).toStringAsFixed(1)}s',
      },
  ];
  rows.sort((a, b) => (views[b['route']] ?? 0).compareTo(views[a['route']] ?? 0));
  return rows;
}

/// 功能使用行：ops.feature.used 按（feature_ref × 路由）分组。
List<Map<String, Object?>> featureRows(List<MFEventEnvelope> events) {
  final uses = <String, int>{};
  final last = <String, String>{};
  for (final e in events) {
    if (e.eventName != 'ops.feature.used') continue;
    final feature = '${e.payload['feature_ref']}';
    final route = e.route;
    final key = '$feature\n$route';
    uses[key] = (uses[key] ?? 0) + 1;
    last[key] = _localTime(e.occurredAt);
  }
  final rows = [
    for (final entry in uses.entries)
      {
        'feature': entry.key.split('\n')[0],
        'route': entry.key.split('\n')[1],
        'usesText': '${entry.value}',
        'lastText': last[entry.key] ?? '-',
      },
  ];
  rows.sort((a, b) => int.parse(b['usesText']!).compareTo(int.parse(a['usesText']!)));
  return rows;
}

/// 习惯打卡运营行：ops.habit.checked-in 按习惯分组（次数 + 最近打卡）。
List<Map<String, Object?>> habitCheckinRows(List<MFEventEnvelope> events) {
  final counts = <String, int>{};
  final last = <String, String>{};
  for (final e in events) {
    if (e.eventName != 'ops.habit.checked-in') continue;
    final name = '${e.payload['name']}';
    counts[name] = (counts[name] ?? 0) + 1;
    last[name] = _localTime(e.occurredAt);
  }
  final rows = [
    for (final entry in counts.entries)
      {
        'name': entry.key,
        'checkinsText': '${entry.value}',
        'lastText': last[entry.key] ?? '-',
      },
  ];
  rows.sort((a, b) => int.parse(b['checkinsText']!).compareTo(int.parse(a['checkinsText']!)));
  return rows;
}

/// 查询窗口 → 起始时间（engine 查询协议的时间范围参数）。
DateTime windowStart(String window, DateTime now) => switch (window) {
      '1h' => now.subtract(const Duration(hours: 1)),
      '24h' => now.subtract(const Duration(hours: 24)),
      '7d' => now.subtract(const Duration(days: 7)),
      _ => DateTime.fromMillisecondsSinceEpoch(0, isUtc: true),
    };

/// 日志检索行（一条事件一行）。
List<Map<String, Object?>> logRowsOf(List<MFEventEnvelope> events) => [
      for (final e in events)
        {
          'timeText': _localTime(e.occurredAt),
          'name': e.eventName,
          'route': e.route,
          'infoText':
              e.interactionId ?? '${e.payload['feature_ref'] ?? e.payload['page_definition_id'] ?? ''}',
        },
    ];

/// 导出（§30.2 exportevents 协议）：游标循环取全量 JSONL 与缺口区间数。
({List<String> lines, int count, int gaps}) buildExport(
  List<MFEventEnvelope> events, {
  required String window,
  required DateTime now,
}) {
  final engine = MFLocalQueryEngine(events: () => events);
  final from = windowStart(window, now);
  final lines = <String>[];
  var gaps = 0;
  String? cursor;
  while (true) {
    final page = engine.exportEvents(from: from, to: now.toUtc(), cursor: cursor);
    lines.addAll([for (final item in page['items'] as List) '$item']);
    final pageGaps = page['gap_intervals'] as List? ?? const [];
    gaps += pageGaps.length;
    final next = page['cursor'] as String?;
    if (next == null) break;
    cursor = next;
  }
  return (lines: lines, count: lines.length, gaps: gaps);
}
