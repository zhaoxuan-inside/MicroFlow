/// 交易平台应用测试：authoring 命令面构造审计、静态门禁、业务语义与
/// 监控数据面（遥测零埋点 → 内存 sink → 查询断言）。
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'package:trading_app/project.dart';
import 'package:trading_app/registry.dart';
import 'package:trading_app/trading_data.dart';

void main() {
  test('页面经 authoring 命令面构造：每条命令过门禁并产生可回滚修订', () {
    final built = buildTradingViaAuthoring();
    expect(built.audit.length, 5, reason: '3 × create_page + 2 × connect_navigation');
    expect(built.audit.every((r) => r.actor == 'zcode-builder'), isTrue);
    expect(built.session.project.pages.map((p) => p.id).toSet(),
        {'home-page', 'cart-page', 'orders-page'});
    // 回滚语义可用：撤销最后一次导航修订，项目回到其前状态。
    final before = built.session.project;
    final reverted = built.session.undo();
    expect(reverted, isNotNull);
    expect(identical(reverted, before), isFalse);
    final reapplied = built.session.connectNavigation(from: 'orders-page', to: 'home-page');
    expect(reapplied.ok, isTrue, reason: '${[for (final d in reapplied.diagnostics) d.message]}');
  });

  test('构造完成的项目通过与发布相同的静态校验门禁（§2.7）', () {
    final result = MFValidator(project: buildTradingProject(), registry: buildTradingRegistry())
        .validate();
    expect(result.ok, isTrue, reason: '${[for (final d in result.diagnostics) d.message]}');
  });

  test('业务语义与后端 place_order 流程对齐（整数分、会员 95/100）', () {
    final data = LocalTradingData();
    final hits = data.search('手机');
    expect((hits['products'] as List).length, 2);
    data.addCart('MI-14', '手机 Pro 14', 499900);
    data.addCart('BUDGETS-2', '耳机 2', 49900);
    final order = data.placeOrder('buyer-web-001', true);
    expect(order['status'], 'CREATED');
    expect(order['orderId'], 'SO-W-1');
    // (499900 + 49900) * 95 ~/ 100 = 522310
    expect(order['orderText'], contains('5223.10'));
    expect(data.cart()['emptyText'], '购物车是空的，回首页逛逛吧');
    final orders = data.orders();
    expect(orders['gmvText'], contains('5223.10'));
    expect((orders['items'] as List).length, 1);
  });

  testWidgets('监控数据面：页面浏览零埋点事件进入遥测管道并可查询', (tester) async {
    final sink = MFInMemorySink();
    final registry = buildTradingRegistry();
    final project = buildTradingProject(registry: registry);
    final framework = MicroFlowFramework.create(
      project: project,
      registry: registry,
      environment: 'preview',
      releaseId: 'trading-app-r1',
      telemetrySink: sink,
    );
    // 运行时先启动（在构建期之外打开入口页），再挂载应用。
    await framework.runtime.start();
    await tester.pumpWidget(MicroFlowApp(
      project: project,
      registry: registry,
      runtime: framework.runtime,
    ));
    await tester.pumpAndSettle();

    // 首页列表经 onEnter 绑定加载（List 声明式绑定）。
    expect(find.text('手机 Pro 14'), findsOneWidget);
    expect(find.text('手机 14e'), findsOneWidget);
    // 显式冲刷采集队列（生产由周期 flush 承担），再断言数据面可查询。
    await framework.telemetry.flush();
    await tester.pump();
    // 标准运营事件族由运行时拦截边界零埋点产生（§24.7，基线 29）。
    final names = sink.delivered.map((e) => e.eventName).toSet();
    expect(names.contains('ops.page.viewed'), isTrue,
        reason: 'delivered: ${sink.delivered.map((e) => e.eventName).toList()}');
  });
}
