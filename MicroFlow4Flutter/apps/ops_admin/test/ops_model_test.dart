// 纯聚合逻辑测试（VM）：运营指标聚合。输入是按测试场景构造的真实
// §24.2 信封（测试夹具）；静态校验门禁与跨应用落盘链路在 browser_test
// （-p chrome）以真实 localStorage 覆盖——dart:js_interop 在 VM 不可用，
// 本文件不得触及任何存储面。
import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'package:ops_admin/ops_logic.dart';

MFEventEnvelope _event({
  required String name,
  required String route,
  Map<String, Object?> payload = const {},
  String? interaction,
  String session = 'ses-1',
  String at = '2026-10-25T08:00:00.000Z',
}) =>
    MFEventEnvelope(
      eventName: name,
      payload: payload,
      sessionId: session,
      pageInstanceId: 'pg-$session',
      route: route,
      releaseId: 'r1',
      rendererVersion: 'v',
      environment: 'dev',
      traceId: 'tr-1',
      interactionId: interaction,
      occurredAt: at,
    );

void main() {
  group('运营聚合逻辑', () {
    final now = DateTime.parse('2026-10-25T08:00:00.000Z').toUtc();
    final events = [
      _event(name: 'ops.page.viewed', route: '/today', at: '2026-10-25T07:00:00.000Z'),
      _event(name: 'ops.page.viewed', route: '/today', at: '2026-10-25T07:05:00.000Z'),
      _event(name: 'ops.page.viewed', route: '/stats', at: '2026-10-25T07:10:00.000Z', session: 'ses-2'),
      _event(
        name: 'ops.page.left',
        route: '/today',
        payload: {'stay_ms': 30000, 'exit': 'push'},
        at: '2026-10-25T07:05:30.000Z',
      ),
      _event(
        name: 'ops.feature.used',
        route: '/today',
        payload: {'feature_ref': 'today-check'},
        interaction: 'today-check',
        at: '2026-10-25T07:05:20.000Z',
      ),
      _event(
        name: 'ops.habit.checked-in',
        route: '/today',
        payload: {'habitId': 'h1', 'name': '晨跑', 'touchpoint': 'success'},
        interaction: 'adapter.habits.toggle',
        at: '2026-10-25T07:05:20.000Z',
      ),
      _event(
        name: 'ops.habit.checked-in',
        route: '/today',
        payload: {'habitId': 'h1', 'name': '晨跑', 'touchpoint': 'success'},
        interaction: 'adapter.habits.toggle',
        at: '2026-10-25T07:30:00.000Z',
      ),
    ];

    test('overviewRows：计数与会话去重', () {
      final rows = overviewRows(events, now: now);
      final byLabel = {for (final r in rows) r['label']: r['value']};
      expect(byLabel['事件总数'], '7');
      expect(byLabel['会话数'], '2');
      expect(byLabel['页面浏览'], '3');
      expect(byLabel['页面退出'], '1');
      expect(byLabel['功能调用'], '1');
      expect(byLabel['打卡次数'], '2');
      expect(byLabel['近 24 小时事件'], '7');
    });

    test('pageRows：浏览/退出/平均停留，按浏览量排序', () {
      final rows = pageRows(events);
      expect(rows.first['route'], '/today');
      expect(rows.first['viewsText'], '2');
      expect(rows.first['exitsText'], '1');
      expect(rows.first['avgStayText'], '30.0s');
      expect(rows[1]['route'], '/stats');
      expect(rows[1]['avgStayText'], '-');
    });

    test('featureRows 与 habitCheckinRows：分组计数与最近时间', () {
      final features = featureRows(events);
      expect(features.single['feature'], 'today-check');
      expect(features.single['usesText'], '1');
      expect(features.single['route'], '/today');
      final habits = habitCheckinRows(events);
      expect(habits.single['name'], '晨跑');
      expect(habits.single['checkinsText'], '2');
      // 最近时间以本地时区展示，断言与时区无关的本地时分秒。
      final expectedClock = DateTime.parse('2026-10-25T07:30:00.000Z')
          .toLocal()
          .toString()
          .substring(11, 19);
      expect(habits.single['lastText'], contains(expectedClock));
    });

    test('buildExport：游标循环产出 JSONL 与缺口区间数', () {
      final export = buildExport(events, window: 'all', now: now);
      expect(export.count, 7);
      expect(export.gaps, 0);
      final firstLine = export.lines.first;
      expect(firstLine, contains('"event_name"'));
      expect(firstLine, contains('"event_id"'));
      // 24 小时窗口内包含全部夹具事件。
      expect(buildExport(events, window: '24h', now: now).count, 7);
    });

    test('windowStart：窗口映射', () {
      expect(windowStart('1h', now), now.subtract(const Duration(hours: 1)));
      expect(windowStart('24h', now), now.subtract(const Duration(hours: 24)));
      expect(windowStart('7d', now), now.subtract(const Duration(days: 7)));
      expect(windowStart('all', now).millisecondsSinceEpoch, 0);
    });

    test('qualityRows：接收端与队列指标合并', () {
      final rows = qualityRows(
        events,
        logMetrics: {'corrupt': 1, 'evicted': 2, 'suppressed': 3},
        queueQuality: {'queued': 4, 'dropped': 5, 'diagnostics': 6},
      );
      final byLabel = {for (final r in rows) r['label']: r['value']};
      expect(byLabel['日志事件行'], '7');
      expect(byLabel['容量淘汰（evicted）'], '2');
      expect(byLabel['采集关闭抑制（suppressed）'], '3');
      expect(byLabel['损坏行（corrupt）'], '1');
      expect(byLabel['队列待发'], '4');
      expect(byLabel['队列丢弃'], '5');
      expect(byLabel['队列诊断数'], '6');
    });
  });
}
