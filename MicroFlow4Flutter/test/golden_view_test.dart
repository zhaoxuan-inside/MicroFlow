import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

import 'fixtures/product_sample.dart';

/// 本地视觉验证用（golden 产物不入库）：样例渲染快照。
void main() {
  testWidgets('render sample surface page', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    final project = productSampleProject();
    final runtime = MFRuntime(
      project: project,
      registry: _reg(),
      ids: MFInstanceIdentifiers(projectId: 'p', releaseId: 'r1', environment: 'dev'),
      emissionSink: MFNullEmissionSink(),
    );
    await runtime.start();
    runtime.state.write('page', 'rows', [
      {'name': 'ops.page.viewed', 'count': 5},
      {'name': 'ops.feature.used', 'count': 5},
      {'name': 'ops.page.viewed', 'count': 3},
    ]);
    runtime.generation.value++;
    await tester.pumpWidget(MicroFlowApp(project: project, registry: _reg(), runtime: runtime));
    await tester.pumpAndSettle();
    void hunt(Element element) {
      final typeName = element.widget.runtimeType.toString();
      if (typeName.contains('Error') || typeName.contains('ErrorBox')) {
        // ignore: avoid_print
        print('HUNT-ERROR-WIDGET: $typeName :: ${element.widget}');
      }
      element.visitChildren(hunt);
    }
    hunt(tester.element(find.byType(MaterialApp)));
    await expectLater(find.byType(MaterialApp), matchesGoldenFile('_local_view.png'));
  });
}

MFRegistry _reg() {
  final r = MFRegistry();
  for (final id in MFTierA.required) {
    r.register('primitive', id,
        ComponentContract(props: {'text': const TString(), 'items': const TList()},
            slots: const ['content'], layout: const LayoutCapability()),
        MFHostComponentImpl((children, props) => Object()));
  }
  r.register('primitive', 'Grid',
      const ComponentContract(props: {'columns': TString(), 'gap': TString()},
          slots: ['content'], layout: LayoutCapability()),
      MFHostComponentImpl((children, props) => Object()));
  return r;
}
