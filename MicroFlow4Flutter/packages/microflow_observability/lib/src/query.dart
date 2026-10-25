/// Query/Export 最小协议（frontend-framework-design §30.2）本地参考实现：
/// `queryevents / get_event_schema / get_trace / exportevents /
/// get_data_quality`。实现形态由承载方交付，本地实现面向测试与预览。
///
/// 纪律：查询过滤器强制时间范围与分页上限（禁止默认返回无限明细）；响应
/// 携带 Schema 版本、数据截止时间、采样比例、丢失率、分页令牌与一致性
/// 级别；导出为游标式增量并携带缺口区间声明（缺失区间、原因），迟到数据
/// 进入后续增量。
library;

import 'dart:convert';


import 'telemetry.dart';

class MFLocalQueryEngine {
  MFLocalQueryEngine({
    required this.events,
    this.dataQuality,
    this.gapWindows,
  });

  final List<MFEventEnvelope> Function() events;
  final Map<String, Object?> Function()? dataQuality;
  final List<Map<String, String>> Function()? gapWindows;

  static const schemaVersion = '1.0';
  static const maxPageSize = 200;

  List<MFEventEnvelope> _filtered({
    required DateTime from,
    required DateTime to,
    String? eventName,
    String? route,
    String? releaseId,
    String? pageInstanceId,
  }) {
    final out = events()
        .where((e) => !DateTime.parse(e.occurredAt).isBefore(from))
        .where((e) => !DateTime.parse(e.occurredAt).isAfter(to))
        .where((e) => eventName == null || e.eventName == eventName)
        .where((e) => route == null || e.route == route)
        .where((e) => releaseId == null || e.releaseId == releaseId)
        .where((e) => pageInstanceId == null || e.pageInstanceId == pageInstanceId)
        .toList()
      ..sort((a, b) => a.occurredAt.compareTo(b.occurredAt));
    return out;
  }

  double get _lossRate {
    final q = dataQuality?.call();
    if (q == null) return 0.0;
    final delivered = (q['delivered'] as num?)?.toInt() ?? 0;
    final dropped = (q['dropped'] as num?)?.toInt() ?? 0;
    final total = delivered + dropped;
    return total == 0 ? 0.0 : dropped / total;
  }

  /// `queryevents`（§30.2）：过滤 + 分页 + 可选分组计数。`groupBy` 取值：
  /// event_name / route / release_id / page_instance_id / privacy_class。
  Map<String, Object?> queryEvents({
    required DateTime from,
    required DateTime to,
    String? eventName,
    String? route,
    String? releaseId,
    String? pageInstanceId,
    List<String> groupBy = const [],
    int pageSize = 50,
    String? pageToken,
  }) {
    if (pageSize > maxPageSize) {
      pageSize = maxPageSize;
    }
    final offset = pageToken == null ? 0 : int.tryParse(pageToken) ?? 0;
    final all = _filtered(
      from: from,
      to: to,
      eventName: eventName,
      route: route,
      releaseId: releaseId,
      pageInstanceId: pageInstanceId,
    );
    final page = all.skip(offset).take(pageSize).toList();
    final nextToken = offset + pageSize < all.length ? '${offset + pageSize}' : null;
    return {
      'schema_version': schemaVersion,
      'events': [for (final e in page) e.toJson()],
      'total': all.length,
      'page_token': nextToken,
      'data_cutoff': all.isEmpty ? to.toUtc().toIso8601String() : all.last.occurredAt,
      'sampling_ratio': 1.0,
      'loss_rate': _lossRate,
      'consistency_level': 'local-reference',
      if (groupBy.isNotEmpty)
        'groups': _groupBy(all, groupBy),
    };
  }

  List<Map<String, Object?>> _groupBy(List<MFEventEnvelope> events, List<String> dimensions) {
    final counters = <String, int>{};
    for (final e in events) {
      String dim(String d) => switch (d) {
            'event_name' => e.eventName,
            'route' => e.route,
            'release_id' => e.releaseId,
            'page_instance_id' => e.pageInstanceId,
            'privacy_class' => e.privacyClass,
            'session_id' => e.sessionId,
            _ when d.startsWith('payload.') => '${e.payload[d.substring(8)]}',
            _ => '_',
          };
      final key = [for (final d in dimensions) dim(d)].join('|');
      counters[key] = (counters[key] ?? 0) + 1;
    }
    return [
      for (final e in counters.entries) {'key': e.key, 'count': e.value},
    ];
  }

  /// `get_event_schema`（§30.2）：事件信封 Schema 描述；标准事件族与
  /// diag. 命名事件的家族归属在此声明。
  Map<String, Object?> getEventSchema(String eventName, {String schemaVersion = '1.0'}) {
    final standard = MFStandardEvents.all.contains(eventName);
    final family = standard
        ? 'operational-standard'
        : eventName.startsWith('diag.')
            ? 'diagnostic'
            : 'custom';
    return {
      'event_name': eventName,
      'schema_version': schemaVersion,
      'family': family,
      'fields': const {
        'event_id': 'string',
        'event_name': 'string',
        'schema_version': 'string',
        'occurred_at': 'iso-8601',
        'client_sent_at': 'iso-8601',
        'release_id': 'string',
        'renderer_version': 'string',
        'environment': 'enum{dev,preview,production}',
        'session_id': 'string',
        'page_instance_id': 'string',
        'route': 'string',
        'interaction_id': 'string?',
        'action_request_id': 'string?',
        'trace_id': 'string',
        'experiment_assignments': 'list<map>',
        'identity': 'map<string,string?>',
        'payload': 'object',
        'privacy_class': 'enum{operational,sensitive,restricted}',
      },
    };
  }

  /// `get_trace`（§30.2）：按追踪 id 汇集事件（发生时间序）。
  Map<String, Object?> getTrace(String traceId) {
    final trace = events().where((e) => e.traceId == traceId).toList()
      ..sort((a, b) => a.occurredAt.compareTo(b.occurredAt));
    return {
      'trace_id': traceId,
      'schema_version': schemaVersion,
      'events': [for (final e in trace) e.toJson()],
    };
  }

  /// `exportevents`（§30.2）：游标式增量导出；响应携带缺口区间声明
  /// （缺失区间、原因），禁止静默改写已交付数据。
  Map<String, Object?> exportEvents({
    required DateTime from,
    required DateTime to,
    String format = 'jsonl',
    String retentionScope = 'raw-events',
    String? cursor,
  }) {
    final offset = cursor == null ? 0 : int.tryParse(cursor) ?? 0;
    final all = _filtered(from: from, to: to);
    final page = all.skip(offset).take(maxPageSize).toList();
    final next = offset + maxPageSize < all.length ? '${offset + maxPageSize}' : null;
    return {
      'schema_version': schemaVersion,
      'format': format,
      'retention_scope': retentionScope,
      'cursor': next,
      'items': [
        for (final e in page) format == 'jsonl' ? jsonEncode(e.toJson()) : e.toJson(),
      ],
      'gap_intervals': [
        ...?gapWindows?.call(),
      ],
    };
  }

  /// `get_data_quality`（§30.2）：丢失率、丢弃计数等口径（与 Ingest 层
  /// 同源，保证丢失/回放数据的口径一致性）。
  Map<String, Object?> getDataQuality({String scope = 'all'}) => {
        'scope': scope,
        'schema_version': schemaVersion,
        ...?dataQuality?.call(),
      };
}
