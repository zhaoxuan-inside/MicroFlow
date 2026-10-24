/// Flutter interpretation of Tier A primitives (§38.1).
///
/// Every primitive maps a model contract to a Flutter widget. The mapping is
/// deterministic: the same node + same resolved state produces the same
/// widget tree shape (§7.3 / baseline 18, for the structural subset).
library;

import 'package:flutter/material.dart';
import 'package:microflow_model/microflow_model.dart';
// ignore: unused_import

/// The Tier A primitive set (§38.1) and Tier B (replaceable in clients).
abstract final class MFTierA {
  static const required = {'Text', 'Icon', 'Image', 'Button', 'Input', 'Select', 'Checkbox', 'Stack', 'Scroll', 'Overlay', 'List', 'Modal'};
  static const tierB = {'Grid', 'Split', 'Anchor', 'Tabs', 'Drawer', 'Table'};
}

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
  const MFRenderContext({required this.props, required this.onEvent, required this.tokenColor});

  final Map<String, Object?> props;

  /// `on(nodeId, event)` — the runtime dispatches via binding maps.
  final void Function(String nodeId, String event) onEvent;

  /// Resolve a named color token into a Flutter color.
  final Color Function(String tokenName) tokenColor;
}

class MFNodeView {
  const MFNodeView({required this.node, required this.children});
  final MFNode node;
  final List<Widget> children;
}

typedef MFPrimitiveBuilder = Widget Function(MFRenderContext context, MFNodeView view);

/// The Tier A (+ Tier B Grid) mapping table used by the interpreter.
class MFPrimitiveTable {
  Map<String, MFPrimitiveBuilder> get builders => _builders;

  final Map<String, MFPrimitiveBuilder> _builders = {
    'Text': (ctx, view) => Text(
          (view.node.props['text'] as String?) ?? '',
          textAlign: switch (view.node.props['align']) {
            'center' => TextAlign.center,
            'end' => TextAlign.end,
            _ => TextAlign.start,
          },
        ),
    'Icon': (ctx, view) => Icon(
          Icons.circle,
          size: (view.node.props['size'] as num?)?.toDouble(),
          color: view.node.props['color'] is String ? ctx.tokenColor(view.node.props['color'] as String) : null,
        ),
    'Image': (ctx, view) => Image.network(
          (view.node.props['src'] as String?) ?? '',
          fit: BoxFit.cover,
          errorBuilder: (context, error, stack) => const SizedBox(width: 48, height: 48, child: Icon(Icons.broken_image)),
        ),
    'Button': (ctx, view) {
      final label = (view.node.props['label'] as String?) ?? '';
      void press() => ctx.onEvent(view.node.id, 'press');
      return switch (view.node.props['variant']) {
        'secondary' => OutlinedButton(onPressed: press, child: Text(label)),
        'danger' => TextButton(
            style: TextButton.styleFrom(foregroundColor: Colors.redAccent),
            onPressed: press,
            child: Text(label),
          ),
        _ => FilledButton(onPressed: press, child: Text(label)),
      };
    },
    'Input': (ctx, view) => TextField(
          enabled: view.node.props['readOnly'] != true,
          decoration: InputDecoration(labelText: (view.node.props['placeholder'] as String?)),
        ),
    'Select': (ctx, view) => DropdownButtonFormField<String>(
          items: const [],
          decoration: InputDecoration(labelText: (view.node.props['label'] as String?)),
          onChanged: (_) => ctx.onEvent(view.node.id, 'change'),
        ),
    'Checkbox': (ctx, view) => Checkbox(
          value: (view.node.props['value'] ?? false) == true,
          tristate: false,
          onChanged: (_) => ctx.onEvent(view.node.id, 'change'),
        ),
    'Stack': (ctx, view) {
      final direction = axisOf(view.node.props['direction'] as String?);
      if (direction == Axis.horizontal) {
        return Row(
          mainAxisSize: MainAxisSize.min,
          mainAxisAlignment: mainAlignOf(view.node.props['align'] as String?),
          crossAxisAlignment: crossAlignOf(view.node.props['crossAlign'] as String?),
          children: view.children,
        );
      }
      return Column(
        mainAxisSize: view.node.props['expand'] == true ? MainAxisSize.max : MainAxisSize.min,
        mainAxisAlignment: mainAlignOf(view.node.props['align'] as String?),
        crossAxisAlignment: crossAlignOf(view.node.props['crossAlign'] as String?),
        children: view.children,
      );
    },
    'Grid': (ctx, view) {
      final columns = (view.node.props['columns'] as num?)?.toInt() ?? 2;
      return Wrap(
        runSpacing: 8,
        spacing: 8,
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
            color: ctx.tokenColor('color.bg.surface'),
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
