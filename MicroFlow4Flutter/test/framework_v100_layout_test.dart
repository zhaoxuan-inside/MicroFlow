import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// 0.10.0 布局能力扩展的可执行判据（能力面测试，不挂 §44.3 基线号）：
/// - L1 Stack padding：四边内边距（页面容器最小留白）；
/// - L2 Stack maxWidth：垂直容器限宽 + 水平居中（经典页面容器）；
/// - L3 Text size/weight：排版层次 prop。
MFRegistry _registry() {
  final r = MFRegistry();
  for (final id in MFTierA.required) {
    r.register(
      'primitive',
      id,
      ComponentContract(
        props: switch (id) {
          'Text' => {'text': const TString()},
          'List' => {'items': const TList()},
          _ => const {},
        },
        slots: const ['content'],
        layout: const LayoutCapability(),
      ),
      MFHostComponentImpl((children, props) => Object()),
    );
  }
  return r;
}

MFProject _project(MFNode tree) => MFProject(
      manifest: const MFManifest(projectId: 'p', entryPage: 'page'),
      pages: [
        MFPage(id: 'page', route: '/p', tree: tree),
      ],
    );

MFRuntime _runtime(MFProject project) {
  final runtime = MFRuntime(
    project: project,
    registry: _registry(),
    ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
    emissionSink: MFNullEmissionSink(),
  );
  return runtime;
}

void main() {
  testWidgets('L1 Stack padding：内容不再贴边（四边内边距生效）', (tester) async {
    final project = _project(MFNode(
      id: 'root',
      type: 'Stack',
      props: const {'padding': 24},
      children: const [
        MFNode(id: 'label', type: 'Text', props: {'text': '带留白的文本'}),
      ],
    ));
    final runtime = _runtime(project);
    await runtime.start();
    await tester.pumpWidget(MicroFlowApp(project: project, registry: _registry(), runtime: runtime));
    await tester.pump();

    final rect = tester.getRect(find.text('带留白的文本'));
    expect(rect.left, greaterThanOrEqualTo(24), reason: '左内边距生效');
    expect(rect.top, greaterThanOrEqualTo(24), reason: '上内边距生效');
  });

  testWidgets('L2 Stack maxWidth：限宽容器水平居中（左右边距对称）', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    final project = _project(MFNode(
      id: 'root',
      type: 'Stack',
      props: const {'expand': true, 'maxWidth': 400},
      children: const [
        MFNode(id: 'label', type: 'Text', props: {'text': '居中容器内容'}),
      ],
    ));
    final runtime = _runtime(project);
    await runtime.start();
    await tester.pumpWidget(MicroFlowApp(project: project, registry: _registry(), runtime: runtime));
    await tester.pump();

    final rect = tester.getRect(find.text('居中容器内容'));
    final leftGap = rect.left;
    final rightGap = 1200 - rect.right;
    expect(leftGap, greaterThan(100), reason: '1200 宽视口下 400 限宽应产生大边距');
    expect((leftGap - rightGap).abs(), lessThan(2), reason: '水平居中：左右边距对称');
    expect(rect.width, lessThanOrEqualTo(400), reason: '内容宽度不超过 maxWidth');
  });

  testWidgets('L3 Text size/weight：排版层次 prop 生效', (tester) async {
    final project = _project(MFNode(
      id: 'root',
      type: 'Stack',
      children: const [
        MFNode(id: 'title', type: 'Text', props: {'text': '页面标题', 'size': 22, 'weight': 700}),
      ],
    ));
    final runtime = _runtime(project);
    await runtime.start();
    await tester.pumpWidget(MicroFlowApp(project: project, registry: _registry(), runtime: runtime));
    await tester.pump();

    final widget = tester.widget<Text>(find.text('页面标题'));
    expect(widget.style?.fontSize, 22);
    expect(widget.style?.fontWeight, FontWeight.w700);
  });
}
