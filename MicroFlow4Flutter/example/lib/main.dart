import 'package:flutter/material.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

/// Tier A registry for preview/example purposes (§38.1 预览实现):
/// one contract-declared primitive per Tier A type; rendering happens in
/// the interpreter's primitive table, registration exists for static
/// validation and dependency discovery (§23.6).
MFRegistry buildTierAExampleRegistry() {
  final r = MFRegistry();
  for (final id in MFTierA.required) {
    final contract = ComponentContract(
      props: switch (id) {
        'Text' => {'text': const TString()},
        'Button' => {'label': const TString(), 'variant': const TEnum(['primary', 'secondary', 'danger'])},
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
      states: switch (id) {
        'Button' => const ['enabled', 'disabled', 'busy'],
        _ => const [],
      },
      slots: const ['content'],
      layout: const LayoutCapability(display: ['block', 'inline'], sizing: ['hug', 'fill', 'fixed']),
    );
    r.register('primitive', id, contract, MFHostComponentImpl((children, props) => Object()));
  }
  return r;
}

/// §44.2 规范性最小示例 “备忘（Notes）” 的 Flutter 解释运行版。
///
/// 覆盖：备注（Notes）列表页 + 编辑页，注册宿主函数，模型组合组件，
/// 数据动作（本地函数适配器）、绑定映射、i18n、采集注记语义由运行时零埋点产生；
/// M1：双层主题（theme-light 默认 / theme-dark extends 重定向）经 AppBar
/// 菜单切换——切换只影响新建实例（§36.3，基线 7），标题经样式片
/// `style-title` 走覆盖链（token < 组件默认样式片 < 页面覆盖 < 产品主题，§36.6）。
void main() {
  final registry = buildTierAExampleRegistry();
  final i18n = const MFI18nCatalog(
    defaultLocale: 'zh-CN',
    supportedLocales: ['zh-CN', 'en'],
    fallback: {'en': 'zh-CN'},
    messages: {
      'notes.title': {'zh-CN': '备忘', 'en': 'Notes'},
      'editor.title': {'zh-CN': '编辑', 'en': 'Editor'},
    },
  );

  registry.register(
    'function',
    'function.notes-query',
    const ComponentContract(events: {}),
    MFFunctionImpl(
      (args) async {
        // 演示数据源：真实场景应通过 §40 Data Contract 声明外部适配器获得。
        return [
          {'id': 'n1', 'title': '第一批笔记'},
          {'id': 'n2', 'title': '第二批笔记'},
        ];
      },
      timeoutMs: 3000,
    ),
    description: '本地函数：查询笔记列表（测试/演示实现）',
  );

  final app = MFProject(
    manifest: const MFManifest(
      projectId: 'notes-demo',
      syntaxVersion: '1.0',
      targets: ['web'],
      entryPage: 'notes-page',
      defaultTheme: 'theme-light',
      defaultLocale: 'zh-CN',
      supportedLocales: ['zh-CN', 'en'],
    ),
    pages: [
      // 列表页（§8）：本地函数加载数据、i18n 标题、guarded 导航按钮
      MFPage(
        id: 'notes-page',
        route: '/notes',
        tree: MFNode(
          id: 'notes-root',
          type: 'Stack',
          children: [
            MFNode(id: 'notes-title', type: 'Text', t: 'notes.title', style: 'style-title'),
            const MFNode(id: 'add-note', type: 'Button', props: {'label': '新建'}),
            const MFNode(id: 'note-item', type: 'Stack'),
          ],
        ),
        stateMembers: const ['notes'],
        onEnter: 'note-init',
      ),
      // 编辑页（§8）
      MFPage(
        id: 'editor-page',
        route: '/editor',
        tree: MFNode(
          id: 'editor-root',
          type: 'Stack',
          children: [
            MFNode(id: 'editor-title', type: 'Text', t: 'editor.title', style: 'style-title'),
            const MFNode(id: 'save-note', type: 'Button'),
          ],
        ),
        stateMembers: const ['draft', 'hasChanges'],
        onEnter: 'editor-init',
      ),
    ],
    bindingMaps: const {
      'navigation-map': MFBindingMap(
        id: 'navigation-map',
        syntaxVersion: '1.0',
        bindings: [
          MFBinding(
            id: 'note-init',
            on: 'notes-page.onEnter',
            actions: [
              MFAdapterAction(kind: 'function', call: 'function.notes-query', as: 'value'),
              MFStateAction(target: 'notes', value: MFRef('prev.value')),
            ],
            policy: MFPolicy.rejectNew,
          ),
          // 新建按钮：guard 阻止无草稿重复进入（§39.1 示意）
          MFBinding(
            id: 'open-editor',
            on: 'add-note.press',
            actions: [MFNavigationAction(target: 'editor-page')],
            policy: MFPolicy.cancelPrevious,
          ),
          MFBinding(
            id: 'editor-init',
            on: 'editor-page.onEnter',
            actions: [
              MFStateAction(target: 'draft', value: MFLiteral('')),
              MFStateAction(target: 'hasChanges', value: MFLiteral(false)),
            ],
            policy: MFPolicy.rejectNew,
          ),
          // 保存按钮：把草稿写回状态并返回列表页
          MFBinding(
            id: 'save-note-binding',
            on: 'save-note.press',
            guard: MFRef('state.hasChanges'),
            actions: [
              MFStateAction(target: 'hasChanges', value: MFLiteral(false)),
              MFNavigationAction(target: 'notes-page'),
            ],
            policy: MFPolicy.rejectNew,
          ),
          // 脚注：绑定到 root 的 press 事件档（编辑框实时标脏）
          MFBinding(
            id: 'mark-dirty',
            on: 'editor-root.press',
            actions: [MFStateAction(target: 'hasChanges', value: MFLiteral(true))],
            policy: MFPolicy.rejectNew,
          ),
        ],
      ),
    },
    i18n: i18n,
    // 主题 Token（§36.2）：产品主题投影的语义值基础集。
    tokens: const {
      'theme-light': MFTokenSet(
        id: 'theme-light',
        tokens: {
          'color.action': '#2563eb',
          'color.bg.surface': '#ffffff',
          'color.bg.inverse': '#111827',
          'color.text.primary': '#111827',
          'color.text.inverse': '#f9fafb',
          'color.foreground': '#111827',
          'color.background': '#ffffff',
        },
      ),
    },
    // 双层主题（§36.3）：theme-dark 经 extends 继承 light，仅重定向已有
    // token（{"ref": ...}），重定向环是静态错误。
    themes: const {
      'theme-dark': MFTheme(
        id: 'theme-dark',
        extendsId: 'theme-light',
        overrides: {
          'color.foreground': {'ref': 'color.text.inverse'},
          'color.background': {'ref': 'color.bg.inverse'},
        },
      ),
    },
    // 样式片（§36.4）：值只允许 token 引用，字面量是静态错误。
    styleSheets: const {
      'style-title': MFStyleSheet(
        id: 'style-title',
        base: {'foreground': 'color.foreground', 'background': 'color.background'},
      ),
    },
  );

  final result = MFValidator(
    project: app,
    registry: registry,
  ).validate();
  for (final d in result.diagnostics) {
    debugPrint('mf-static: $d');
  }
  if (!result.ok) {
    throw StateError('notes-demo 未通过静态检查');
  }

  // 双层主题切换（§36.3，基线 7）：themeProvider 只在实例创建时读取，
  // 切换后 replace 重建当前页——新实例带新 frozen 主题，旧实例不可改写。
  final themeSelection = ValueNotifier<String>('theme-light');
  final fw = MicroFlowFramework.create(
    project: app,
    registry: registry,
    environment: 'preview',
    releaseId: 'notes-demo-r1',
    themeProvider: () => themeSelection.value,
  );
  runApp(MicroFlowApp(
    project: app,
    registry: registry,
    runtime: fw.runtime,
    themeSelection: themeSelection,
    themeNames: const ['theme-light', 'theme-dark'],
    onThemeSelected: (themeId) {
      themeSelection.value = themeId;
      final current = fw.runtime.current;
      if (current != null) {
        fw.runtime.push(current.definition.id, kind: 'replace');
      }
    },
  ));
}
