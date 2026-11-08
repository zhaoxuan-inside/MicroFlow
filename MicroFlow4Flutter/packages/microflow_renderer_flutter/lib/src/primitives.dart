/// Flutter interpretation of Tier A primitives (§38.1).
///
/// Every primitive maps a model contract to a Flutter widget. The mapping is
/// deterministic: the same node + same resolved state produces the same
/// widget tree shape (§7.3 / baseline 18, for the structural subset).
library;

import 'package:flutter/material.dart';
import 'package:microflow_model/microflow_model.dart';

// Tier A/Tier B 元组件集（§38.1）单一来源在模型层，这里保持再导出以兼容
// 既有 `package:microflow_renderer_flutter` 导入面。
export 'package:microflow_model/microflow_model.dart' show MFTierA;

Axis axisOf(String? direction) => direction == 'horizontal' ? Axis.horizontal : Axis.vertical;

MainAxisAlignment mainAlignOf(String? align) => switch (align) {
      'end' => MainAxisAlignment.end,
      'center' => MainAxisAlignment.center,
      'space-between' => MainAxisAlignment.spaceBetween,
      _ => MainAxisAlignment.start,
    };

CrossAxisAlignment crossAlignOf(String? align) => switch (align) {
      'end' => CrossAxisAlignment.end,
      'center' => CrossAxisAlignment.center,
      'stretch' => CrossAxisAlignment.stretch,
      _ => CrossAxisAlignment.start,
    };

/// Widget builders consume a resolved render context: evaluated prop values
/// and an event callback routed through the runtime's binding map (never
/// directly through business code, §24.7).
class MFRenderContext {
  const MFRenderContext({
    required this.props,
    required this.onEvent,
    required this.tokenColor,
    this.motionSurfaces = const {},
    this.resolveMotion,
    this.recordMotionDiag,
  });

  final Map<String, Object?> props;

  /// `on(nodeId, event, [payload])` — the runtime dispatches via binding
  /// maps; `payload` carries the typed event value declared by the component
  /// contract (`value` key, §5)，由输入类元组件在用户交互时回传。
  final void Function(String nodeId, String event, [Map<String, Object?>? payload]) onEvent;

  /// Resolve a named color token into a Flutter color.
  final Color Function(String tokenName) tokenColor;

  /// 该节点组件契约已声明的动效面（§36.5）；渲染侧动效只允许出现在这里。
  final Set<String> motionSurfaces;

  /// motion token 解析（§36.5 值只解析到 motion Token；§36.7 减少动效替代组）。
  final MFMotionResolution? Function(String tokenName)? resolveMotion;

  /// 动效诊断记录通道（替代组命中记录 / 未声明面拒绝记录）。
  final void Function(MFDiag diag)? recordMotionDiag;
}

class MFNodeView {
  const MFNodeView({
    required this.node,
    required this.children,
    this.slots = const {},
    this.childConstraints = const [],
  });

  final MFNode node;

  /// 默认插槽（未声明 slotOf 的子节点，§23.9）。
  final List<Widget> children;

  /// 命名插槽：slotOf/命名槽 -> 子组件；未被 primitive 消费的命名插槽
  /// 不再被静默并入默认插槽。
  final Map<String, List<Widget>> slots;

  /// 与 [children] 对齐的节点自约束（§7.2），由布局型 primitive 消费。
  final List<MFSelfConstraint?> childConstraints;
}

typedef MFPrimitiveBuilder = Widget Function(MFRenderContext context, MFNodeView view);

/// The Tier A (+ Tier B Grid) mapping table used by the interpreter.
class MFPrimitiveTable {
  Map<String, MFPrimitiveBuilder> get builders => _builders;

  final Map<String, MFPrimitiveBuilder> _builders = {
    'Text': (ctx, view) => Text(
          (ctx.props['text'] as String?) ?? '',
          style: ctx.props['foreground'] is String
              ? TextStyle(color: resolveTokenColor(ctx.props['foreground']))
              : null,
          textAlign: switch (ctx.props['align']) {
            'center' => TextAlign.center,
            'end' => TextAlign.end,
            _ => TextAlign.start,
          },
        ),
    'Icon': (ctx, view) => Icon(
          _iconOf(ctx.props['name'] as String?),
          size: (ctx.props['size'] as num?)?.toDouble(),
          color: ctx.props['color'] is String ? ctx.tokenColor(ctx.props['color'] as String) : null,
        ),
    'Image': (ctx, view) => Image.network(
          (ctx.props['src'] as String?) ?? '',
          fit: BoxFit.cover,
          errorBuilder: (context, error, stack) => const SizedBox(width: 48, height: 48, child: Icon(Icons.broken_image)),
        ),
    'Button': (ctx, view) {
      final label = (ctx.props['label'] as String?) ?? '';
      void press() => ctx.onEvent(view.node.id, 'press');
      return switch (ctx.props['variant']) {
        'secondary' => OutlinedButton(onPressed: press, child: Text(label)),
        'danger' => TextButton(
            style: TextButton.styleFrom(foregroundColor: Colors.redAccent),
            onPressed: press,
            child: Text(label),
          ),
        _ => FilledButton(onPressed: press, child: Text(label)),
      };
    },
    'Input': (ctx, view) => TextFormField(
          initialValue: ctx.props['value'] as String?,
          enabled: ctx.props['readOnly'] != true,
          decoration: InputDecoration(labelText: (ctx.props['placeholder'] as String?)),
          // 输入值经 change 事件回传（契约 events.change 声明载荷类型，§5）；
          // FormField 自身维持编辑状态，绑定侧镜像到页面状态。
          onChanged: (text) => ctx.onEvent(view.node.id, 'change', {'value': text}),
        ),
    'Select': (ctx, view) {
      final raw = ctx.props['options'] as List? ?? const [];
      String valueOf(Object o) => o is Map ? '${o['value']}' : '$o';
      String labelOf(Object o) => o is Map ? '${o['label'] ?? o['value']}' : '$o';
      final options = [for (final o in raw) valueOf(o)];
      return DropdownButtonFormField<String>(
        items: [
          for (var i = 0; i < options.length; i++)
            DropdownMenuItem(value: options[i], child: Text(labelOf(raw[i])))
        ],
        initialValue: options.contains(ctx.props['value']) ? ctx.props['value'] as String : null,
        decoration: InputDecoration(labelText: (ctx.props['label'] as String?)),
        onChanged: (v) => ctx.onEvent(view.node.id, 'change', {'value': v}),
      );
    },
    'Checkbox': (ctx, view) => Checkbox(
          value: (ctx.props['value'] ?? false) == true,
          tristate: false,
          onChanged: (_) => ctx.onEvent(view.node.id, 'change'),
        ),
    'Stack': (ctx, view) {
      final direction = axisOf(ctx.props['direction'] as String?);
      // 0.8.0：gap 数值 prop 声明主轴间距（默认 0 保持既有无间距行为）。
      final gap = (ctx.props['gap'] as num?)?.toDouble() ?? 0;
      // 子约束映射（§7.2/§7.3）：fill 主轴 -> Expanded 分配剩余空间，
      // fixed -> SizedBox 固定尺寸，hug/未声明 -> 按内容。
      Widget wrap(int i, Widget child) {
        if (i >= view.childConstraints.length) return child;
        final c = view.childConstraints[i];
        if (c == null) return child;
        final main = direction == Axis.horizontal ? c.width : c.height;
        if (isFill(main)) return Expanded(child: child);
        if (main is num) return direction == Axis.horizontal ? SizedBox(width: main.toDouble(), child: child) : SizedBox(height: main.toDouble(), child: child);
        final cross = direction == Axis.horizontal ? c.height : c.width;
        if (cross is num) {
          return direction == Axis.horizontal ? SizedBox(height: cross.toDouble(), child: child) : SizedBox(width: cross.toDouble(), child: child);
        }
        return child;
      }

      final children = [for (var i = 0; i < view.children.length; i++) wrap(i, view.children[i])];
      if (direction == Axis.horizontal) {
        return Row(
          spacing: gap,
          mainAxisSize: MainAxisSize.min,
          mainAxisAlignment: mainAlignOf(ctx.props['align'] as String?),
          crossAxisAlignment: crossAlignOf(ctx.props['crossAlign'] as String?),
          children: children,
        );
      }
      return Column(
        spacing: gap,
        mainAxisSize: ctx.props['expand'] == true ? MainAxisSize.max : MainAxisSize.min,
        mainAxisAlignment: mainAlignOf(ctx.props['align'] as String?),
        crossAxisAlignment: crossAlignOf(ctx.props['crossAlign'] as String?),
        children: children,
      );
    },
    'Tabs': (ctx, view) {
      final labels = [for (final l in (ctx.props['labels'] as List? ?? const [])) '$l'];
      final count = view.children.length.clamp(1, 8);
      return DefaultTabController(
        length: count,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TabBar(tabs: [
              for (var i = 0; i < count; i++) Tab(text: i < labels.length ? labels[i] : '${i + 1}'),
            ]),
            Expanded(child: TabBarView(children: [for (final w in view.children) w])),
          ],
        ),
      );
    },
    'Drawer': (ctx, view) {
      final panelWidth = (ctx.props['width'] as num?)?.toDouble() ?? 240;
      return Container(
        width: panelWidth,
        color: ctx.tokenColor('color.bg.surface'),
        child: view.children.isEmpty ? const SizedBox() : view.children.first,
      );
    },
    'Table': (ctx, view) {
      final colSpec = ctx.props['columns'];
      final rowSpec = ctx.props['rows'];
      // 0.8.0 数据绑定模式：columns: [{key,label,width?}] + rows: [Map]。
      if (colSpec is List && rowSpec is List) {
        final widths = <int, TableColumnWidth>{
          for (var i = 0; i < colSpec.length; i++)
            if (colSpec[i] is Map && (colSpec[i] as Map)['width'] is num)
              i: FixedColumnWidth(((colSpec[i] as Map)['width'] as num).toDouble()),
        };
        String labelOf(Object c) => c is Map ? '${c['label'] ?? c['key']}' : '$c';
        Object? cellValue(Map row, Object c) => row[c is Map ? '${c['key']}' : '$c'];
        Widget cell(Object? v) => Padding(
              padding: const EdgeInsets.all(6),
              child: Text('$v', maxLines: 2, overflow: TextOverflow.ellipsis),
            );
        return Table(
          columnWidths: widths.isEmpty ? null : widths,
          defaultColumnWidth: const FlexColumnWidth(),
          border: TableBorder.all(color: ctx.tokenColor('color.border')),
          children: [
            TableRow(
              children: [
                for (final c in colSpec)
                  TableCell(
                    child: Padding(
                      padding: const EdgeInsets.all(6),
                      child: Text(labelOf(c), style: const TextStyle(fontWeight: FontWeight.w600)),
                    ),
                  ),
              ],
            ),
            for (final r in rowSpec)
              if (r is Map)
                TableRow(children: [for (final c in colSpec) TableCell(child: cell(cellValue(r, c)))])
              else
                TableRow(children: [for (final _ in colSpec) TableCell(child: cell(r))]),
          ],
        );
      }
      // 旧模式（向后兼容）：columns 为数量，children 按列数分块。
      final columns = (colSpec as num?)?.toInt() ?? 1;
      final rows = [for (int i = 0; i < view.children.length; i += columns) view.children.sublist(i, (i + columns).clamp(0, view.children.length))];
      return Table(
        defaultColumnWidth: const FlexColumnWidth(),
        border: TableBorder.all(color: ctx.tokenColor('color.border')),
        children: [
          for (final row in rows)
            TableRow(children: [for (final cell in row) TableCell(child: Padding(padding: const EdgeInsets.all(4), child: cell))]),
        ],
      );
    },
    'Split': (ctx, view) {
      // 分栏（Tier B，允许替换实现）：direction + weights 声明式分配，
      // 未声明权重的子项均分剩余空间；0.8.0 支持 gap 主轴间距。
      final horizontal = (ctx.props['direction'] as String? ?? 'horizontal') != 'vertical';
      final gap = (ctx.props['gap'] as num?)?.toDouble() ?? 0;
      final weights = (ctx.props['weights'] as List?)?.cast<num>();
      final children = [
        for (var i = 0; i < view.children.length; i++)
          Expanded(flex: (weights?.length ?? 0) > i ? weights![i].toInt() : 1, child: view.children[i]),
      ];
      return horizontal
          ? Row(spacing: gap, children: children)
          : Column(spacing: gap, children: children);
    },
    'Anchor': (ctx, view) {
      // 锚定（§7.3 Overlay 规则：仅相对容器边）：anchor 声明映射到
      // Alignment，容器内对齐，不引用兄弟节点。
      final child = view.children.isEmpty ? const SizedBox.shrink() : view.children.first;
      final anchor = ctx.props['anchor'] as String?;
      final alignment = switch (anchor) {
        'top' => Alignment.topCenter,
        'top-left' || 'left-top' => Alignment.topLeft,
        'top-right' || 'right-top' => Alignment.topRight,
        'bottom' => Alignment.bottomCenter,
        'bottom-left' || 'left-bottom' => Alignment.bottomLeft,
        'bottom-right' || 'right-bottom' => Alignment.bottomRight,
        'left' => Alignment.centerLeft,
        'right' => Alignment.centerRight,
        _ => Alignment.center,
      };
      return Align(alignment: alignment, child: child);
    },
    'Grid': (ctx, view) {
      final columns = (ctx.props['columns'] as num?)?.toInt() ?? 2;
      // 0.8.0：gap 可声明（默认 8 保持既有行为）。
      final gap = (ctx.props['gap'] as num?)?.toDouble() ?? 8;
      return Wrap(
        runSpacing: gap,
        spacing: gap,
        children: [for (final child in view.children) FractionallySizedBox(widthFactor: 1 / columns, child: child)],
      );
    },
    'Scroll': (ctx, view) => SingleChildScrollView(child: view.children.isEmpty ? const SizedBox() : view.children.first),
    'Overlay': (ctx, view) => Stack(fit: StackFit.loose, children: view.children),
    'List': (ctx, view) => Column(mainAxisSize: MainAxisSize.min, children: view.children),
    'Modal': (ctx, view) => Container(
          margin: const EdgeInsets.all(16),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: ctx.props['background'] is String
                ? resolveTokenColor(ctx.props['background'])
                : ctx.tokenColor('color.bg.surface'),
            borderRadius: BorderRadius.circular(12),
          ),
          child: view.children.isEmpty ? const SizedBox() : view.children.first,
        ),
  };
}

/// Tier A completeness (§38.1): every required primitive must exist in the
/// registry with a §5-shape contract; missing implementations are errors.
List<MFDiag> tierAContractDiagnostics(Map<String, ComponentContract> registryContracts) {
  final registered = registryContracts.keys.toSet();
  final missing = MFTierA.required.difference(registered);
  if (missing.isEmpty) return const [];
  return [MFDiag(MFCodes.regUnregisteredImpl, 'Tier A 缺失必备元组件实现：${missing.join(', ')}')];
}

/// 常用图标名映射（Icon 元组件 name 属性）：闭合集合，未知名回落占位形状。
IconData _iconOf(String? name) => switch (name) {
      'check' => Icons.check,
      'add' => Icons.add,
      'close' => Icons.close,
      'delete' => Icons.delete_outlined,
      'stats' => Icons.bar_chart,
      'list' => Icons.list,
      'settings' => Icons.settings_outlined,
      'search' => Icons.search,
      'refresh' => Icons.refresh,
      'arrow-back' => Icons.arrow_back,
      'arrow-forward' => Icons.arrow_forward,
      'home' => Icons.home_outlined,
      'person' => Icons.person_outline,
      'star' => Icons.star_border,
      'warning' => Icons.warning_amber_outlined,
      'info' => Icons.info_outline,
      _ => Icons.circle,
    };

/// Model-project color mapping; token resolution stays framework side.
Color resolveTokenColor(Object? v) {
  if (v is String && v.startsWith('#')) {
    final hex = v.substring(1);
    final asInt = int.tryParse(hex, radix: 16);
    if (asInt != null) return Color(hex.length == 6 ? (0xFF000000 | asInt) : asInt);
  }
  if (v is int) return Color(v);
  return const Color(0xFF888888);
}
