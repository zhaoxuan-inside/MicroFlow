/// Structured expression evaluation (§37.2 subset) over the scoped state
/// model (§11): prop, param, state, session, product, local, capability,
/// provided, prev.
library;

import 'package:microflow_model/microflow_model.dart';

import 'state_store.dart';

class EvalContext {
  const EvalContext({
    required this.state,
    this.props = const {},
    this.params = const {},
    this.prev = const {},
    this.providedRoots = const [],
  });

  final MFStateStore state;
  final Map<String, Object?> props;
  final Map<String, Object?> params;

  /// Action chain result transfer (§39.1): `prev` resolves to the last
  /// action result, or a named `as`.
  final Map<String, Object?> prev;

  /// Stack of offering container instance subtrees that declared `provides`;
  /// innermost last. Resolution is subtree-bounded (§37.2).
  final List<ProvidedScope> providedRoots;

  EvalContext withPrev(String? asKey, Object? result) => EvalContext(
        state: state,
        props: props,
        params: params,
        prev: asKey == null
            ? {'last': result}
            : {...prev, 'as:$asKey': result, 'last': result},
        providedRoots: providedRoots,
      );
}

class ProvidedScope {
  const ProvidedScope({required this.id, required this.values});
  final String id;
  final Map<String, Object?> values;
}

class MFExprEvaluator {
  const MFExprEvaluator();

  Object? eval(MFExpr expr, EvalContext ctx) => switch (expr) {
        MFLiteral(:final value) => value,
        MFRef(:final path) => _resolve(path, ctx),
        MFCall() => const MFCallNotSupported().unknownValue,
        MFCompare(:final op, :final operands) => switch (op) {
            'gt' => _num(operands, 0, ctx) > _num(operands, 1, ctx),
            'gte' => _num(operands, 0, ctx) >= _num(operands, 1, ctx),
            'lt' => _num(operands, 0, ctx) < _num(operands, 1, ctx),
            'lte' => _num(operands, 0, ctx) <= _num(operands, 1, ctx),
            'eq' => eval(operands[0], ctx) == eval(operands[1], ctx),
            'neq' => eval(operands[0], ctx) != eval(operands[1], ctx),
            _ => false,
          },
        MFLogic(:final op, :final operands) => switch (op) {
            'and' => operands.every((o) => eval(o, ctx) == true),
            'or' => operands.any((o) => eval(o, ctx) == true),
            'not' => !(eval(operands.first, ctx) == true),
            _ => false,
          },
      };

  double _num(List<MFExpr> operands, int i, EvalContext ctx) =>
      switch (eval(operands[i], ctx)) {
        final num n => n.toDouble(),
        _ => double.nan,
      };

  Object? _resolve(String path, EvalContext ctx) {
    final parts = path.split('.');
    final root = parts.first;
    final rest = parts.skip(1);
    // State layers resolve the whole path inside peek() (§11 layering).
    if (root == 'state') {
      return ctx.state.peek('page', rest.isNotEmpty ? rest.join('.') : '');
    }
    if (root == 'session') {
      return ctx.state.peek('session', rest.isNotEmpty ? rest.join('.') : '');
    }
    if (root == 'product') {
      return ctx.state.peek('product', rest.isNotEmpty ? rest.join('.') : '');
    }
    if (root == 'prev') {
      return _resolvePrev(rest.join('.'), ctx);
    }
    if (root == 'provided') {
      return _resolveProvided(path, ctx);
    }
    final source = switch (root) {
      'prop' => ctx.props,
      'param' => ctx.params,
      _ => throw StateError('unknown scope: $root'),
    };
    return _walkInner(source, rest);
  }

  Object? _resolvePrev(String joined, EvalContext ctx) {
    if (ctx.prev.isEmpty) return null;
    if (joined.isEmpty || joined == 'last') return ctx.prev['last'];
    if (joined.startsWith('as:')) return ctx.prev[joined];
    // `prev.<asName>` → named action result (§39.1).
    return ctx.prev[joined] ?? ctx.prev['as:$joined'] ?? ctx.prev['last'];
  }

  Object? _resolveProvided(String path, EvalContext ctx) {
    final parts = path.split('.');
    if (parts.length < 3) return null; // provided.<id>.<path>
    final scopeId = parts[1];
    for (final root in ctx.providedRoots.reversed) {
      if (root.id == scopeId) {
        return _walkInner(root.values[parts[2]], parts.skip(3));
      }
    }
    return null; // unresolved provided ref: validator's scope (§2.8)
  }

  Object? _walkInner(Object? source, Iterable<String> rest) {
    Object? cur = source;
    for (final p in rest) {
      if (cur is Map) {
        cur = cur[p];
      } else if (cur is List) {
        final i = int.tryParse(p);
        cur = i == null ? null : (i < cur.length ? cur[i] : null);
      } else {
        return null;
      }
    }
    return cur;
  }
}

/// Placeholder marker for unsupported call evaluation in pure model context;
/// `call` actions are executed by the runtime's action executor (§10/§39).
class MFCallNotSupported {
  const MFCallNotSupported();
  final Object? unknownValue = null;
}
