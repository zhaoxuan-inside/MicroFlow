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
  const MFInterpreter({
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

  /// Contracts for primitives declared in the registry (not Dart widgets).
  final Map<String, ComponentContract> primitiveContracts;

  Widget renderPage(MFPageInstance instance) {
    return _NodeRenderer(
      interpreter: this,
      instance: instance,
      providedScopes: [],
    ).build();
  }
}

class _NodeRenderer {
  _NodeRenderer({
    required this.interpreter,
    required this.instance,
    required this.providedScopes,
  });

  final MFInterpreter interpreter;
  final MFPageInstance instance;
  final List<ProvidedScope> providedScopes;

  Widget build() => widgetFor(instance.definition.tree);

  Widget widgetFor(MFNode node) {
    final childNodes = <MFNode>[...node.children, ...node.slots.values.expand((s) => s)];

    final evaluated = <String, Object?>{};
    for (final e in node.props.entries) {
      final expr = MFExpr.parse(e.value);
      evaluated[e.key] = interpreter.runtime.safeEval(expr, _ctx());
    }

    final context = MFRenderContext(
      props: {
        ...evaluated,
        // i18n message channel: `t` resolves via the fallback chain; missing
        // translations are diagnosable (§42.5), never silent.
        if (node.t != null) 'text': interpreter.localize(node.t!, instance.frozen.locale),
      },
      onEvent: (nodeId, event) {
        // Dispatch through the runtime binding map (§39); evaluation order
        // is declaration order and deterministic.
        interpreter.runtime.dispatchEvent(nodeId, event).ignore();
      },
      tokenColor: (name) => resolveTokenColor(interpreter.resolveColor(name)),
    );

    final view = MFNodeView(node: node, children: [for (final child in childNodes) widgetFor(child)]);

    final builder = interpreter.table.builders[node.type];
    if (builder != null) {
      return KeyedSubtree(key: ValueKey('${instance.id}/${node.id}'), child: builder(context, view));
    }
    // Model-composition component (§6): expand its definition tree in a
    // component-instance scope with per-instance provided values.
    final def = interpreter.runtime.project.components[node.type];
    if (def != null) {
      return KeyedSubtree(
        key: ValueKey('${instance.id}/${node.id}'),
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
      );
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
