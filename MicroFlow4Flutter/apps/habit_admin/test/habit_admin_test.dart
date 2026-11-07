import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:habit_admin/src/admin_data.dart';
import 'package:habit_admin/src/admin_model.dart';
import 'package:habit_admin/src/mf_storage.dart';
import 'package:habit_admin/src/telemetry_sink.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// 管理平台应用测试：真实信封落盘 → 管理适配器（§30.2 引擎封装）→
/// 运营指标；损坏行计入丢弃口径；项目模型静态门禁。无假数据。

void main() {
  late Directory dir;
  late MFKeyValueStore storage;
  late AdminData data;

  setUp(() {
    dir = Directory.systemTemp.createTempSync('admin-test');
    storage = MFKeyValueStore.open(dir.path);
    data = AdminData(storage);
  });

  tearDown(() {
    dir.deleteSync(recursive: true);
  });

  Map<String, Object?> runtimeRaw(String name, Map<String, Object?> payload, String session, String trace) => {
        'event_name': name,
        'payload': payload,
        'mf_source': 'runtime-intercept',
        'session_id': session,
        'page_instance_id': 'pg',
        'route': '/habits',
        'release_id': 'r1',
        'renderer_version': 'v',
        'renderer_package': 'microflow4_flutter',
        'environment': 'production',
        'trace_id': trace,
        'identity': const {'user_ref': null},
        'experiment_assignments': const [],
      };

  test('打卡平台日志落盘 → 管理适配器产出真实运营指标', () async {
    // 打卡平台侧：经运行时发射边界产生真实事件并落盘。
    final sink = MFStorageSink(storage);
    final queue = MFTelemetryQueue(sink: sink, batchMax: 64);
    queue.emit(runtimeRaw('ops.page.viewed', const {}, 'ses-1', 'tr-1'));
    queue.emit(runtimeRaw('ops.habit.checked-in', const {'id': 'h1', 'name': '晨跑'}, 'ses-1', 'tr-1'));
    queue.emit(runtimeRaw('ops.habit.checked-in', const {'id': 'h1', 'name': '晨跑'}, 'ses-1', 'tr-2'));
    queue.emit(runtimeRaw('ops.habit.checked-in', const {'id': 'h2', 'name': '阅读'}, 'ses-2', 'tr-3'));
    queue.emit(runtimeRaw('ops.habit.created', const {'name': '晨跑'}, 'ses-2', 'tr-3'));
    await queue.flush();

    final registry = MFRegistry();
    registerAdminPrimitives(registry);
    registerAdminAdapters(registry, data);
    MFFunctionImpl impl(String id) => registry.entry(id)!.impl as MFFunctionImpl;

    final overview = await impl('function.admin-overview').fn(const {}) as Map<String, Object?>;
    expect(overview['totalLabel'], '事件总数 5');
    expect(overview['checksLabel'], '打卡事件 3');
    expect(overview['createsLabel'], '创建习惯 1');
    expect(overview['sessionsLabel'], '活跃会话 2');
    expect((overview['lossLabel'] as String).startsWith('丢失率 0.0%'), isTrue);
    expect(overview['hint'], '');

    // 按习惯维度分组：h1 两次打卡（两个追踪）。
    final byEvent = (overview['byEvent'] as List).cast<Map>();
    final checkRow = byEvent.firstWhere((g) => (g['event'] as String) == 'ops.habit.checked-in');
    expect(checkRow['count'], '3 条');

    final events = await impl('function.admin-events').fn(const {}) as Map<String, Object?>;
    expect((events['events'] as List).length, 5);
    expect((events['hint'] as String).contains('共 5 条'), isTrue);

    final trace = await impl('function.admin-trace').fn(const {'trace': 'tr-1'}) as Map<String, Object?>;
    expect((trace['events'] as List).length, 2, reason: 'tr-1 下两条事件（页面浏览 + 打卡）');
    expect(trace['message'], contains('共 2 条'));

    final miss = await impl('function.admin-trace').fn(const {'trace': 'tr-none'}) as Map<String, Object?>;
    expect((miss['events'] as List).isEmpty, isTrue);
    expect(miss['message'], contains('未找到'));

    final quality = await impl('function.admin-quality').fn(const {}) as Map<String, Object?>;
    expect((quality['qualityRows'] as List).first, {'k': '已交付事件', 'v': '5'});
  });

  test('损坏行与队列丢弃计入丢失率口径（数据质量如实反映）', () async {
    // 三条好数据 + 一条损坏行。
    final sink = MFStorageSink(storage);
    final queue = MFTelemetryQueue(sink: sink, batchMax: 64);
    queue.emit(runtimeRaw('ops.page.viewed', const {}, 's', 't'));
    await queue.flush();
    final raw = jsonDecode(storage.read('telemetry.log')!) as List;
    raw.add({'event_name': 'ops.page.viewed'}); // 缺必需身份字段 → fromJson 抛错
    storage.write('telemetry.log', jsonEncode(raw));
    storage.write('telemetry.quality', jsonEncode({'queue_dropped': 2, 'sink_dropped': 1}));

    final events = data.loadTrackerEvents();
    expect(events, hasLength(1));
    expect(data.corruptCount, 1, reason: '损坏行计入丢弃口径');
    expect(data.trackerDropped(), 3);
    final dq = data.engine(events).getDataQuality();
    expect(dq['delivered'], 1);
    expect(dq['dropped'], 4);
    expect((dq['loss_rate'] as num) > 0, isTrue, reason: '丢失率如实大于 0');
  });

  test('空数据如实空态：管理项目静态门禁通过，适配器返回零值口径', () async {
    final registry = MFRegistry();
    registerAdminPrimitives(registry);
    registerAdminAdapters(registry, data);
    final result = MFValidator(project: buildAdminProject(), registry: registry).validate();
    expect(result.ok, isTrue, reason: '静态错误：${result.diagnostics.where((d) => d.severity == Severity.error)}');

    final overview = await (registry.entry('function.admin-overview')!.impl as MFFunctionImpl).fn(const {})
        as Map<String, Object?>;
    expect(overview['totalLabel'], '事件总数 0');
    expect((overview['hint'] as String), isNotEmpty, reason: '空态提示（无假数据填充）');
    expect((overview['preview'] as List).isEmpty, isTrue);
    final quality = await (registry.entry('function.admin-quality')!.impl as MFFunctionImpl).fn(const {})
        as Map<String, Object?>;
    expect((quality['qualityRows'] as List).first, {'k': '已交付事件', 'v': '0'});
  });
}
