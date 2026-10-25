/// The interpreter (§13.3 解释模式): walk the model node tree of a page
/// instance and produce the Flutter widget tree.
///
/// Binding dispatch routes node events through the runtime's binding maps
/// (§39); components are instantiated per use site, so two usages of one
/// definition are isolated (§2.6, baseline 1).
library;

import 'package:flutter/widgets.dart';
import 'package:microflow_model/microflow_model.dart';
import 'package:microflow_runtime/microflow_runtime.dart';

import 'primitives.dart';

typedef MFLocalizer = String Function(String messageId, String locale);

/// Token resolver returns the raw token value (type-agnostic); the
/// interpreter maps it onto the platform value.
typedef MFTokenResolver = Object? Function(String tokenName);

/// Interpreter configuration: localizer, token resolution and runtime.
class MFInterpreter {
  MFInterpreter({
    required this.runtime,
    required this.table,
    required this.localize,
    required this.resolveColor,
    this.primitiveContracts = const {},
  });

  final MFRuntime runtime;
  final MFPrimitiveTable table;
  final MFLocalizer localize;
  final MFTokenResolver resolveColor;

  late final MFStyleResolver styleResolver = MFStyleResolver(
    tokenSets: runtime.project.tokens,
    styleSheets: runtime.project.styleSheets,
    themes: runtime.project.themes,
    defaultThemeId: runtime.project.manifest.defaultTheme ??
        (runtime.project.tokens.keys.isEmpty ? 'theme-default' : runtime.project.tokens.keys.first),
  );

  /// Contracts for primitives declared in the registry (not Dart widgets).
  final Map<String, ComponentContract> primitiveContracts;

  /// 渲染页面实例。`conditions` 提供样式/布局选择器上下文（§7.4 条件布局、
  /// §36.4 变体条件：platform/breakpoint）；页面未声明显式图层树时按基线 12
  /// 以隐式 ContentLayer 渲染，声明后按 §7.1 分区结构化。
  Widget renderPage(MFPageInstance instance, {Map<String, String?> conditions = const {}}) {
    final page = instance.definition;
    if (!page.hasExplicitLayers) {
      return _NodeRenderer(
        interpreter: this,
        instance: instance,
        providedScopes: [],
        layoutPlans: _resolveLayoutPlans(page, conditions),
      ).build();
    }
    return _renderExplicitLayers(page, instance, conditions);
  }

  /// 条件布局解析（§7.4，基线 20）：target 为页面 id 时作用于根节点，否则
  /// 作用于同 id 节点；声明序首个命中，全不命中回退默认方案。
  Map<String, MFLayoutPlan> _resolveLayoutPlans(MFPage page, Map<String, String?> conditions) {
    final plans = <String, MFLayoutPlan>{};
    for (final cl in page.conditionalLayouts) {
      plans[cl.target == page.id ? page.tree.id : cl.target] = cl.resolve(conditions);
    }
    return plans;
  }

  /// 显式图层结构化渲染（§7.1）：顶层子节点按 `layer` 声明（或节点 id 与
  /// 分区 id 匹配）归入 header/footer/overlay 分区，其余进 ContentLayer；
  /// content 分区声明 scroll 时支持滚动；overlay 以 Stack 覆盖。
  Widget _renderExplicitLayers(MFPage page, MFPageInstance instance, Map<String, String?> conditions) {
    final regions = page.layerRegions!;
    final plans = _resolveLayoutPlans(page, conditions);
    Widget renderNode(MFNode n) => _NodeRenderer(
          interpreter: this,
          instance: instance,
          providedScopes: [],
          layoutPlans: plans,
        ).widgetFor(n);
    Widget? header;
    Widget? footer;
    final overlay = <Widget>[];
    final content = <Widget>[];
    for (final child in page.tree.children) {
      final regionId = child.layer ?? (regions.any((r) => r.id == child.id) ? child.id : null);
      final widget = renderNode(child);
      MFRegionConstraint? rc;
      for (final r in regions) {
        if (r.id == regionId) {
          rc = r;
          break;
        }
      }
      if (rc == null) {
        content.add(widget);
      } else {
        switch (rc.region) {
          case 'header':
            header = widget;
          case 'footer':
            footer = widget;
          case 'overlay':
            overlay.add(widget);
          default:
            content.add(widget);
        }
      }
    }
    final contentScroll = regions.any((r) => r.region == 'content' && r.scroll);
    final contentArea = contentScroll
        ? SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min, children: content))
        : Column(mainAxisSize: MainAxisSize.min, children: content);
    Widget body = Column(children: [
      ?header,
      Expanded(child: contentArea),
      ?footer,
    ]);
    if (overlay.isNotEmpty) {
      // body 作为非定位子项撑起 Stack 尺寸，overlay 覆盖其上（§7.1 overlay
      // 分区不再收缩宿主）。
      body = Stack(children: [body, ...overlay]);
    }
    return KeyedSubtree(key: ValueKey('${instance.id}/${page.tree.id}'), child: body);
  }
}

class _NodeRenderer {
  _NodeRenderer({
    required this.interpreter,
    required this.instance,
    required this.providedScopes,
    this.layoutPlans = const {},
    this.item,
    this.itemIndex,
  });

  final MFInterpreter interpreter;
  final MFPageInstance instance;
  final List<ProvidedScope> providedScopes;

  /// 已解析的条件布局计划（§7.4）：node id -> 命中的声明方案。
  final Map<String, MFLayoutPlan> layoutPlans;

  /// 声明式列表绑定的当前项（§39 事件上下文）：模板子树内 `item.<field>`
  /// 表达式与事件分发携带的项上下文。
  final Map<String, Object?>? item;

  /// 当前项序号（键稳定性：无 id 项按序号区分）。
  final int? itemIndex;

  /// 本渲染域的键后缀：列表项模板实例的键/锚点以 `#<itemKey>` 区分。
  String get keySuffix => item == null
      ? ''
      : '#${item!['id'] ?? itemIndex ?? ''}';

  Widget build() => widgetFor(instance.definition.tree);

  Widget widgetFor(MFNode node) {
    // 插槽区分（§23.9）：slotOf 声明归属命名插槽，未声明的进默认插槽；
    // 命名插槽不再静默并入默认插槽，由 primitive 按契约消费。
    final defaultChildren = <MFNode>[];
    final namedSlots = <String, List<MFNode>>{};
    for (final child in node.children) {
      final slot = child.slotOf;
      if (slot == null || slot.isEmpty) {
        defaultChildren.add(child);
      } else {
        namedSlots.putIfAbsent(slot, () => []).add(child);
      }
    }
    for (final e in node.slots.entries) {
      namedSlots.putIfAbsent(e.key, () => [...e.value]);
    }

    final evaluated = <String, Object?>{};
    for (final e in node.props.entries) {
      final expr = MFExpr.parse(e.value);
      evaluated[e.key] = interpreter.runtime.safeEval(expr, _ctx());
    }

    // 声明式列表绑定：List 节点携带求值后的 `items`（List<Map>）时，
    // children 是项模板——每项以 item 作用域渲染模板子树，键与事件锚点
    // 按 `#<itemKey>` 区分；项内事件经 dispatchEvent 携带项上下文执行。
    if (node.type == 'List') {
      final items = evaluated['items'];
      if (items is List) {
        return KeyedSubtree(
          key: ValueKey('${instance.id}/${node.id}$keySuffix'),
          child: _renderItemTemplates(node, items.cast<Object?>()),
        );
      }
    }

    // 条件布局计划（§7.4）：命中方案覆盖 Stack 的方向/对齐声明。
    final plan = layoutPlans[node.id];
    if (plan != null) {
      if (plan.direction != null) evaluated['direction'] = plan.direction;
      if (plan.align != null) evaluated['align'] = plan.align;
      if (plan.crossAlign != null) evaluated['crossAlign'] = plan.crossAlign;
    }

    // Coverage chain (§36.6): `token < 组件默认样式片 < 页面覆盖 < 产品主题`.
    // Node style sheets resolve per aspect against the instance's frozen
    // theme (baseline 7: switching affects only new instances); resolved raw
    // values merge into props so primitives can apply them without their own
    // chain logic.
    final styleId = node.style;
    if (styleId != null) {
      for (final aspect in const {'foreground', 'background'}) {
        final r = interpreter.styleResolver.resolveNode(
          aspect,
          styleSheetId: styleId,
          pageOverrides: instance.definition.pageOverrides,
          themeId: instance.frozen.theme,
        );
        if (r.resolved) {
          evaluated[aspect] = r.value;
        }
      }
    }

    final context = MFRenderContext(
      props: {
        ...evaluated,
        // i18n message channel: `t` resolves via the fallback chain; missing
        // translations are diagnosable (§42.5), never silent.
        if (node.t != null) 'text': interpreter.localize(node.t!, instance.frozen.locale),
      },
      onEvent: (nodeId, event, [payload]) {
        // Dispatch through the runtime binding map (§39); evaluation order
        // is declaration order and deterministic. Payload (typed event value)
        // and the item context of the enclosing list template ride along.
        interpreter.runtime
            .dispatchEvent(nodeId, event, payload: payload, item: item)
            .ignore();
      },
      tokenColor: (name) => resolveTokenColor(interpreter.resolveColor(name)),
    );

    final view = MFNodeView(
      node: node,
      children: [for (final child in defaultChildren) widgetFor(child)],
      slots: {
        for (final e in namedSlots.entries)
          e.key: [for (final c in e.value) widgetFor(c)],
      },
      childConstraints: [for (final child in defaultChildren) child.constraints],
    );

    final builder = interpreter.table.builders[node.type];
    if (builder != null) {
      return KeyedSubtree(key: ValueKey('${instance.id}/${node.id}$keySuffix'), child: builder(context, view));
    }
    // Model-composition component (§6): expand its definition tree in a
    // component-instance scope with per-instance provided values.
    final def = interpreter.runtime.project.components[node.type];
    if (def != null) {
      return KeyedSubtree(
        key: ValueKey('${interpreter.runtime.ids.componentInstanceId(instance.id, node.id)}$keySuffix'),
        child: _ComponentScope(
          interpreter: interpreter,
          instance: instance,
          def: def,
          suppliedProps: evaluated,
          providedId: node.id,
          ancestorProviders: providedScopes,
        ).build(),
      );
    }
    // Unregistered refs are rejected statically (baseline 13/15); the
    // render path never reaches here for a validated project.
    return const SizedBox.shrink();
  }

  EvalContext _ctx() => EvalContext(
        state: interpreter.runtime.state,
        props: const {},
        params: instance.params,
        prev: const {},
        providedRoots: [...providedScopes, ProvidedScope(id: instance.definition.id, values: instance.provided)],
        item: item,
      );

  /// 项模板渲染：每个 Map 项渲染一份 children 模板；非 Map 项上报运行诊断
  /// 后跳过（列表绑定的项是结构化数据，§39）。
  Widget _renderItemTemplates(MFNode node, List<Object?> items) {
    final rows = <Widget>[];
    for (var i = 0; i < items.length; i++) {
      final raw = items[i];
      if (raw is Map) {
        final itemMap = raw.cast<String, Object?>();
        final scoped = _NodeRenderer(
          interpreter: interpreter,
          instance: instance,
          providedScopes: providedScopes,
          layoutPlans: layoutPlans,
          item: itemMap,
          itemIndex: i,
        );
        rows.add(Column(
          key: ValueKey('${instance.id}/${node.id}#${itemMap['id'] ?? i}'),
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [for (final template in node.children) scoped.widgetFor(template)],
        ));
      } else {
        interpreter.runtime.diagSink.add(MFDiag(
          MFCodes.interactionUnknownMember,
          '列表绑定第 $i 项不是结构化对象，已跳过（node=${node.id}）',
          stage: Stage.runtime,
          severity: Severity.warning,
        ));
      }
    }
    return Column(mainAxisSize: MainAxisSize.min, children: rows);
  }
}

/// Component instance boundary: per-instance provided scope is constructed
/// only from props of ids declared in the info contract (`provides`, §2.8).
class _ComponentScope {
  _ComponentScope({
    required this.interpreter,
    required this.instance,
    required this.def,
    required this.suppliedProps,
    required this.providedId,
    required this.ancestorProviders,
  });

  final MFInterpreter interpreter;
  final MFPageInstance instance;
  final MFComponentDefinition def;
  final Map<String, Object?> suppliedProps;
  final String providedId;
  final List<ProvidedScope> ancestorProviders;

  Widget build() => _NodeRenderer(
        interpreter: interpreter,
        instance: instance,
        providedScopes: [...ancestorProviders, ProvidedScope(id: providedId, values: _values())],
      ).build();

  Map<String, Object?> _values() => {
        for (final id in def.contract.info.provides.keys) id: suppliedProps[id],
      };
}
