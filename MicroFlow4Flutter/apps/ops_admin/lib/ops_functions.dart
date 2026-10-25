/// 运营管理平台的注册资源（§10/§40）：读取同源遥测 JSONL 日志，按
/// MFLocalQueryEngine 查询/导出协议（§30.2）与业务聚合逻辑产出页面数据。
/// 全部实现读真实采集数据，写入只涉及采集控制开关与保留期清理。
library;

import 'package:mf_platform_store/mf_platform_store.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'ops_logic.dart';

/// 解析共享日志为事件信封；必填字段缺失的行计入损坏（质量面可见）。
List<MFEventEnvelope> parseEnvelopes(TelemetryLogStore store) {
  final out = <MFEventEnvelope>[];
  for (final raw in store.readAll()) {
    try {
      out.add(MFEventEnvelope.fromJson(raw));
    } catch (_) {
      store.metrics.corrupt++;
    }
  }
  return out;
}

/// 注册运营管理平台的全部业务资源。
///
/// [queueQuality] 提供本实例采集队列的数据质量（fw.telemetry.dataQuality）；
/// [downloadFile] 是浏览器文件下载能力（生产实现经 Blob + object URL，
/// 见 download.dart），导出函数交付 JSONL 文件时调用。
void registerOpsFunctions(
  MFRegistry registry,
  TelemetryLogStore logStore,
  CollectionControl control, {
  required Map<String, Object?> Function() queueQuality,
  required void Function(String fileName, String text) downloadFile,
}) {
  List<MFEventEnvelope> events() => parseEnvelopes(logStore);

  registry.register(
    'function',
    'fn.ops.overview',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['rows', 'updatedText'])},
    ),
    MFFunctionImpl((args) async {
      final now = DateTime.now();
      final all = events();
      return {
        'rows': overviewRows(all, now: now),
        'updatedText': '数据截至 ${_stamp(now)}',
      };
    }, timeoutMs: 3000),
    description: '运营 KPI：事件/会话/页面/功能/打卡计数',
  );

  registry.register(
    'function',
    'fn.ops.quality',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['rows'])},
    ),
    MFFunctionImpl((args) async {
      final all = events();
      return {
        'rows': qualityRows(all, logMetrics: logStore.metrics.toMap(), queueQuality: queueQuality()),
      };
    }, timeoutMs: 3000),
    description: '数据质量：接收端与采集队列的丢失/抑制/损坏口径',
  );

  registry.register(
    'function',
    'fn.ops.habits',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['rows'])},
    ),
    MFFunctionImpl((args) async {
      return {'rows': habitCheckinRows(events())};
    }, timeoutMs: 3000),
    description: '习惯维度打卡运营统计（来自注记事件）',
  );

  registry.register(
    'function',
    'fn.ops.pages',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['rows'])},
    ),
    MFFunctionImpl((args) async {
      return {'rows': pageRows(events())};
    }, timeoutMs: 3000),
    description: '页面分析：浏览/退出/平均停留',
  );

  registry.register(
    'function',
    'fn.ops.features',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['rows'])},
    ),
    MFFunctionImpl((args) async {
      return {'rows': featureRows(events())};
    }, timeoutMs: 3000),
    description: '功能使用分析：feature_ref × 路由分组',
  );

  registry.register(
    'function',
    'fn.ops.events-query',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['rows', 'totalText', 'pageToken'])},
    ),
    MFFunctionImpl((args) async {
      final now = DateTime.now();
      final eventName = '${args['eventName'] ?? ''}';
      final routeContains = '${args['routeContains'] ?? ''}';
      final window = '${args['window'] ?? 'all'}';
      final token = args['pageToken'] as String?;
      final existing = args['existing'];
      final filtered = [
        for (final e in events())
          if (eventName.isEmpty || e.eventName == eventName)
            if (routeContains.isEmpty || e.route.contains(routeContains)) e,
      ];
      final engine = MFLocalQueryEngine(
        events: () => filtered,
        dataQuality: () => {
          'delivered': filtered.length,
          'dropped': logStore.metrics.evicted,
        },
      );
      final page = engine.queryEvents(
        from: windowStart(window, now).toUtc(),
        to: now.toUtc().add(const Duration(minutes: 1)),
        eventName: eventName.isEmpty ? null : eventName,
        pageSize: 15,
        pageToken: token,
      );
      final rows = [
        ...?existing is List
            ? [for (final row in existing) if (row is Map) row.cast<String, Object?>()]
            : null,
        ...logRowsOf([
          for (final raw in page['events'] as List)
            MFEventEnvelope.fromJson((raw as Map).cast<String, Object?>()),
        ]),
      ];
      return {
        'rows': rows,
        'totalText': '共 ${page['total']} 条',
        'pageToken': page['page_token'],
      };
    }, timeoutMs: 3000),
    description: '日志检索：queryevents 协议（过滤/分页/窗口）',
  );

  registry.register(
    'adapter',
    'adapter.ops.export',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['resultText'])},
    ),
    MFAdapterImpl((args) async {
      final window = '${args['range'] ?? 'all'}';
      final export = buildExport(events(), window: window, now: DateTime.now());
      if (export.count == 0) {
        return {'resultText': '所选时间范围内没有可导出的事件'};
      }
      final stamp = DateTime.now().toUtc().toIso8601String().replaceAll(':', '-');
      final fileName = 'mf-telemetry-$stamp.jsonl';
      downloadFile(fileName, export.lines.join('\n'));
      return {'resultText': '已导出 ${export.count} 条事件（缺口区间 ${export.gaps} 个）→ $fileName'};
    }, timeoutMs: 10000),
    description: '导出事件日志为 JSONL 文件（exportevents 协议）',
  );

  registry.register(
    'adapter',
    'adapter.ops.prune',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['resultText'])},
    ),
    MFAdapterImpl((args) async {
      final removed = logStore.pruneOlderThan(const Duration(days: 7));
      return {'resultText': '已清理 $removed 条早于 7 天的事件'};
    }, timeoutMs: 5000),
    description: '保留期管理：清理早于 7 天的日志事件',
  );

  registry.register(
    'function',
    'fn.ops.status',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['enabled', 'statusText', 'rows'])},
    ),
    MFFunctionImpl((args) async {
      final all = events();
      return {
        'enabled': control.enabled,
        'statusText': control.enabled ? '采集进行中' : '采集已暂停',
        'rows': qualityRows(all, logMetrics: logStore.metrics.toMap(), queueQuality: queueQuality()),
      };
    }, timeoutMs: 3000),
    description: '采集控制状态与质量指标',
  );

  registry.register(
    'adapter',
    'adapter.ops.set-collection',
    const ComponentContract(
      props: {'output': TObject(requiredKeys: ['statusText'])},
    ),
    MFAdapterImpl((args) async {
      control.enabled = args['enabled'] == true;
      return {'statusText': control.enabled ? '采集进行中' : '采集已暂停'};
    }, timeoutMs: 3000),
    description: '写入采集控制开关（同源共享，采集端每次投递前读取）',
  );
}

String _stamp(DateTime at) {
  final local = at.toLocal();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(local.hour)}:${two(local.minute)}:${two(local.second)}';
}
