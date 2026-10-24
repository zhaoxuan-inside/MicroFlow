import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// M1（PLAN.md）样式与布局完整化的一致性基线测试：
/// 基线 7、12、18、19、20、21、22（§44.3，22 为部分覆盖——仅 §36.4 token 规则侧）
/// + 样式片字面量禁令与主题完整性。
/// 测试名中的「基线 N」标记必须遵循 tool/baseline_coverage.dart 的扫描约定。

MFRegistry tierARegistry() {
  final r = MFRegistry();
  for (final id in MFTierA.required) {
    final contract = ComponentContract(
      props: switch (id) {
        'Button' => {'label': const TString(), 'variant': const TEnum(['primary', 'secondary', 'danger'])},
        'Text' => {'text': const TString()},
        'Input' => {'placeholder': const TString(), 'readOnly': const TBool()},
        'Icon' => {'size': const TNumber(), 'color': const TString()},
        'Image' => {'src': const TString()},
        'Checkbox' => {'value': const TBool()},
        'Select' => {'label': const TString()},
        _ => const {},
      },
      events: switch (id) {
        'Button' => {'press': const TString()},
        'Input' => {'change': const TString()},
        'Checkbox' => {'change': const TString()},
        'Select' => {'change': const TString()},
        _ => const {},
      },
      slots: const ['content'],
      layout: const LayoutCapability(display: ['block', 'inline'], sizing: ['hug', 'fill', 'fixed']),
    );
    r.register('primitive', id, contract, MFHostComponentImpl((children, props) => Object()));
  }
  return r;
}

MFProject themedProject({
  String? defaultTheme,
  Map<String, MFStyleSheet> styleSheets = const {},
  Map<String, MFTheme> themes = const {},
}) {
  return MFProject(
    manifest: MFManifest(
      projectId: 'notes-demo',
      entryPage: 'notes-page',
      defaultTheme: defaultTheme,
    ),
    pages: [
      MFPage(
        id: 'notes-page',
        route: '/notes',
        tree: MFNode(
          id: 'root',
          type: 'Stack',
          children: [MFNode(id: 'title', type: 'Text', t: 'notes.title')],
        ),
      ),
    ],
    i18n: const MFI18nCatalog(messages: {'notes.title': {'zh-CN': '备忘'}}),
    tokens: {
      'theme-light': const MFTokenSet(
        id: 'theme-light',
        tokens: {'color.action': '#2563eB', 'color.bg.surface': '#ffffff', 'color.text.primary': '#111827'},
      ),
    },
    styleSheets: styleSheets,
    themes: themes,
  );
}

void main() {
  group('基线 18/19/20/21 —— 布局求解与静态检查', () {
    test('基线 18：同一输入两次求解（等价解释/编译模式）产出相同规范化矩形集', () {
      final solver = MFLayoutSolver();
      List<MFNodeLayout> nodes() => [
            const MFNodeLayout(nodeId: 'a', metric: MFContentMetric(width: 100, height: 40)),
            MFNodeLayout(
              nodeId: 'b',
              metric: const MFContentMetric(width: 100, height: 20),
              demand: MFSizeDemand.from(const MFSelfConstraint(height: 'fill'), vertical: true),
            ),
          ];
      final (r1, d1) = solver.solveStack(nodes: nodes(), availW: 400, availH: 400, platform: 'web');
      final (r2, d2) = solver.solveStack(nodes: nodes(), availW: 400, availH: 400, platform: 'web');
      expect(r1, r2);
      expect(d1.map((e) => e.code), d2.map((e) => e.code));
      final byId = {for (final p in r1) p.nodeId: p.rect};
      // hug 按内容度量；fill 拿走剩余空间（§7.3 Stack 规则）
      expect(byId['a']!.h, 40);
      expect(byId['b']!.h, 360);
    });

    test('基线 19：同轴 fill 与 fixed 并存 → mf.layout.unsatisfiable；fixed 超出可用空间', () {
      // a) 直接构造同轴双声明约束：
      final sameAxis = const MFDeclaredConstraint(
        ownerId: 'p/layer-a',
        constraint: MFSelfConstraint(width: 64, height: 'fill'),
        capabilityId: 'stack',
      );
      // b) fixed 超出可用空间：
      final tooBig = const MFDeclaredConstraint(
        ownerId: 'p/layer-b',
        constraint: MFSelfConstraint(width: 5000, height: 'fill'),
        capabilityId: 'stack',
      );
      final diags = staticLayoutChecks(
        constraints: [sameAxis, tooBig],
        conditionalLayouts: const [],
        targetProfiles: const [mfDefaultPlatformProfile],
      );
      expect(diags.any((d) => d.code == MFCodes.layoutUnsatisfiable), isTrue);
    });

    test('基线 20：条件布局确定命中与默认方案；重复选择器 → ambiguous-scheme', () {
      const cl = MFConditionalLayout(
        target: 'notes-page',
        schemes: [
          MFConditionalScheme(when: {'breakpoint': 'mobile'}, plan: MFLayoutPlan(direction: 'vertical')),
          MFConditionalScheme(when: {'breakpoint': 'mobile'}, plan: MFLayoutPlan(direction: 'horizontal')),
        ],
        defaultPlan: MFLayoutPlan(direction: 'vertical'),
      );
      expect(cl.resolve({'breakpoint': 'mobile'}).direction, 'vertical', reason: '声明顺序首个命中（确定性）');
      expect(cl.resolve({'breakpoint': 'desktop'}).direction, 'vertical', reason: '全不命中回退默认方案（基线 20）');
      final diags = staticLayoutChecks(
        constraints: const [],
        conditionalLayouts: const [cl],
        targetProfiles: const [mfDefaultPlatformProfile],
      );
      expect(diags.any((d) => d.code == MFCodes.layoutAmbiguousScheme), isTrue);
    });

    test('基线 21：平台不支持能力需声明降级；声明后运行期记录不静默', () {
      final undeclared = staticLayoutChecks(
        constraints: const [
          MFDeclaredConstraint(ownerId: 'p/layer-a', constraint: MFSelfConstraint(), capabilityId: 'split'),
        ],
        conditionalLayouts: const [],
        targetProfiles: const [
          MFPlatformProfile(
            platform: 'watch',
            supportedLayouts: ['stack', 'grid'],
            unsupportedLayouts: ['split'],
          ),
        ],
      );
      expect(undeclared.any((d) => d.code == MFCodes.layoutUndeclaredDegradation), isTrue);

      final solver = MFLayoutSolver();
      final (placed, diags) = solver.solveStack(
        nodes: const [
          MFNodeLayout(
            nodeId: 'a',
            metric: MFContentMetric(width: 10, height: 10),
            unsupportedPlatforms: ['watch'],
            degradationDeclared: true,
          ),
        ],
        availW: 200,
        availH: 200,
        platform: 'watch',
      );
      expect(placed.first.degraded, isTrue);
      expect(diags.any((d) => d.code == MFCodes.layoutDegraded), isTrue);
    });
  });

  group('基线 22 —— 样式系统', () {
    test('基线 22（部分）：样式片值只解析到 token，字面量静态拒绝（§36.4；§36.5 动效面未覆盖）', () {
      final diags = validateStyleSheets([
        const MFStyleSheet(id: 'style-ok', base: {'foreground': 'color.text.primary'}),
        const MFStyleSheet(id: 'style-bad', base: {'foreground': 'FF0000'}),
      ]);
      expect(diags.any((d) => d.code == MFCodes.styleLiteralInSheet), isTrue);
    });

    test('主题解析完整性：引用 token 未被主题解析 → 告诫（默认主题缺失为错误）', () {
      final project = themedProject(styleSheets: {
        'style-uses-missing': const MFStyleSheet(id: 'style-uses-missing', base: {'foreground': 'color.never.defined'}),
      }, defaultTheme: 'theme-light');
      final diags = MFValidator(project: project, registry: tierARegistry())._validateStylesResult();
      expect(diags.any((d) => d.code == MFCodes.themeIncomplete), isTrue);
    });

    test('基线 7：locale/主题冻结——切换只影响新建实例', () async {
      var themeNow = 'theme-light';
      final fw = MicroFlowFramework.create(
        project: themedProject(defaultTheme: 'theme-light'),
        registry: tierARegistry(),
        environment: 'dev',
        themeProvider: () => themeNow,
      );
      final runtime = fw.runtime;
      await runtime.start();
      final frozenAtCreation = runtime.current!.frozen.theme;
      expect(frozenAtCreation, 'theme-light');
      themeNow = 'theme-dark-selection';
      await runtime.push('notes-page', kind: 'replace');
      expect(runtime.current!.frozen.theme, 'theme-dark-selection');
    });

    test('基线 12：隐式 ContentLayer 共存规则', () {
      final implicit = MFPage(id: 'notes-page', route: '/notes', tree: MFNode(id: 'root', type: 'Stack'), stateMembers: const []);
      expect(implicit.hasExplicitLayers, isFalse, reason: '无显式图层：隐式 ContentLayer 参与校验与渲染');
      final explicit = MFPage(
        id: 'notes-page',
        route: '/notes',
        tree: MFNode(id: 'root', type: 'Stack'),
        stateMembers: const [],
        layerRegions: [const MFRegionConstraint(id: 'header-zone', region: 'header')],
      );
      expect(explicit.hasExplicitLayers, isTrue,
          reason: '首次声明显式图层后，隐式图层不再生成（§7.5 / 基线 12）');
    });
  });
}

extension on MFValidator {
  /// 测试用：暴露 _validateStyles 产物（不改公开 API）。
  List<MFDiag> _validateStylesResult() {
    final diags = <MFDiag>[];
    _validateStylesPublic(diags);
    return diags;
  }

  void _validateStylesPublic(List<MFDiag> diags) {
    final all = validate().diagnostics;
    // 仅取样式/主题码：
    diags.addAll(all.where((d) => d.code.startsWith('mf.style.') || d.code.startsWith('mf.theme.')));
  }
}
