/// Binding map resources (§39): versioned first-class resources mapping
/// declared object events to typed action chains, plus the structured
/// expression subset (§37.2) used by guards and arguments.
library;

/// Structured expression atoms (§37.2 subset).
///
/// Grammar (structured JSON form):
/// - literal: any JSON scalar/list/map without "ref"/"call"/"op" keys;
/// - reference: `{"ref": "scope.path"}` with scopes
///   prop|param|state|session|product|local|capability|provided|prev;
/// - comparison: `{"gt"|"gte"|"lt"|"lte"|"eq"|"neq": [a, b]}`;
/// - logic: `{"and"|"or": [predicates], "not": predicate}`;
/// - call: `{"call": "<registered function id>", "arguments": {...}}`.
sealed class MFExpr {
  const MFExpr();

  static MFExpr parse(Object? json) => switch (json) {
        {'ref': final String path} => MFRef(path),
        {'call': final String fn} => MFCall(
            fn,
            json['arguments'] is Map
                ? (json['arguments'] as Map)
                    .map((k, v) => MapEntry('$k', MFExpr.parse(v)))
                : const <String, MFExpr>{},
          ),
        {'gt': final List args} => _cmp('gt', args),
        {'gte': final List args} => _cmp('gte', args),
        {'lt': final List args} => _cmp('lt', args),
        {'lte': final List args} => _cmp('lte', args),
        {'eq': final List args} => _cmp('eq', args),
        {'neq': final List args} => _cmp('neq', args),
        {'and': final List args} => MFLogic('and', args.map(MFExpr.parse).toList()),
        {'or': final List args} => MFLogic('or', args.map(MFExpr.parse).toList()),
        {'not': final inner} => MFLogic('not', [MFExpr.parse(inner)]),
        null => const MFLiteral(null),
        _ => MFLiteral(json),
      };

  static MFExpr _cmp(String op, List args) =>
      MFCompare(op, args.map(MFExpr.parse).toList(growable: false));

  /// Referenced scope paths in this expression (for static existence checks).
  Iterable<String> refPaths();
}

class MFLiteral extends MFExpr {
  const MFLiteral(this.value);
  final Object? value;

  @override
  Iterable<String> refPaths() sync* {}
}

class MFRef extends MFExpr {
  const MFRef(this.path);
  final String path;

  @override
  Iterable<String> refPaths() sync* {
    yield path;
  }
}

class MFCall extends MFExpr {
  const MFCall(this.functionId, this.arguments);
  final String functionId;
  final Map<String, MFExpr> arguments;

  @override
  Iterable<String> refPaths() sync* {
    for (final a in arguments.values) {
      yield* a.refPaths();
    }
  }
}

class MFCompare extends MFExpr {
  const MFCompare(this.op, this.operands);
  final String op;
  final List<MFExpr> operands;

  @override
  Iterable<String> refPaths() sync* {
    for (final o in operands) {
      yield* o.refPaths();
    }
  }
}

class MFLogic extends MFExpr {
  const MFLogic(this.op, this.operands);
  final String op;
  final List<MFExpr> operands;

  @override
  Iterable<String> refPaths() sync* {
    for (final o in operands) {
      yield* o.refPaths();
    }
  }
}

/// Binding actions correspond one-to-one to the six action categories (§10).
sealed class MFAction {
  const MFAction();

  static MFAction parse(Map<String, Object?> json) {
    final kind = json['kind'] as String?;
    switch (kind) {
      case 'state':
        return MFStateAction(
          target: (json['state'] ?? json['target']) as String,
          value: MFExpr.parse(json['value']),
          scope: json['scope'] as String? ?? 'page',
        );
      case 'navigation':
        return MFNavigationAction(
          target: json['target'] as String,
          arguments: (json['arguments'] as Map?)
                  ?.map((k, v) => MapEntry('$k', MFExpr.parse(v))) ??
              const {},
        );
      case 'event':
        return MFEventAction(json['event'] as String);
      case 'function':
      case 'adapter':
      case 'host':
        return MFAdapterAction(
          kind: kind!,
          call: json['call'] as String,
          arguments: (json['arguments'] as Map?)
                  ?.map((k, v) => MapEntry('$k', MFExpr.parse(v))) ??
              const {},
          as: json['as'] as String?,
          timeoutMs: (json['timeout_ms'] as num?)?.toInt() ?? 5000,
          idempotency: json['idempotency'] as String? ?? 'read',
        );
      case 'ui':
        return MFUiAction(op: json['op'] as String? ?? 'noop', nodeId: json['node'] as String?);
      default:
        throw FormatException('unknown action kind: $kind');
    }
  }
}

class MFStateAction extends MFAction {
  const MFStateAction({required this.target, required this.value, this.scope = 'page'});
  final String target; // state member name
  final MFExpr value;
  final String scope; // page | session | product | component
}

class MFNavigationAction extends MFAction {
  const MFNavigationAction({required this.target, this.arguments = const {}});
  final String target;
  final Map<String, MFExpr> arguments;
}

class MFEventAction extends MFAction {
  const MFEventAction(this.event);
  final String event;
}

class MFAdapterAction extends MFAction {
  const MFAdapterAction({
    required this.kind,
    required this.call,
    this.arguments = const {},
    this.as,
    this.timeoutMs = 5000,
    this.idempotency = 'read',
  });
  final String kind; // function | adapter | host
  final String call;
  final Map<String, MFExpr> arguments;
  final String? as;
  final int timeoutMs;
  final String idempotency; // read | idempotent-write | non-idempotent
}

class MFUiAction extends MFAction {
  const MFUiAction({required this.op, this.nodeId});
  final String op;
  final String? nodeId;
}

/// Concurrency policy for a binding entry (§39.1, baseline 26): unbound
/// entries reject duplicate triggers.
enum MFPolicy { cancelPrevious, supersede, queue, rejectNew, undeclared }

class MFBinding {
  const MFBinding({
    required this.id,
    required this.on,
    this.guard,
    this.actions = const [],
    this.policy = MFPolicy.undeclared,
    this.errorBoundary,
    this.onError,
    this.findings = const [],
  });

  final String id;

  /// `"<nodeId>.<event>"` or `"<componentId>.<event>"` for cross-object maps.
  final String on;

  /// Optional guard; a structured boolean predicate (§39.1): false -> the
  /// entry does not run, and this is not an error.
  final MFExpr? guard;

  final List<MFAction> actions;

  /// Declared retry/concurrency policy; undeclared rejects duplicates.
  final MFPolicy policy;

  /// Declared error boundary target ("*" catch-all or specific error code).
  final String? errorBoundary;

  /// Optional state action executed on error (declared propagation, §37.4);
  /// undeclared error propagation is a static error.
  final MFAction? onError;

  /// findings 注记引用（§43.3）：见 [MFPage.findings]（§43.3「页面、组件和
  /// 交互可携带 findings 引用」，基线 17）。
  final List<String> findings;

  /// 派生候选绑定（findings 注记登记用，§43.3）。
  MFBinding copyWith({List<String>? findings}) => MFBinding(
        id: id,
        on: on,
        guard: guard,
        actions: actions,
        policy: policy,
        errorBoundary: errorBoundary,
        onError: onError,
        findings: findings ?? this.findings,
      );
}

String? mfErrorRefToString(Object? v) => v == null ? null : '$v';

/// A versioned binding-map resource (`interaction-map`, §39).
class MFBindingMap {
  const MFBindingMap({
    required this.id,
    required this.bindings,
    this.schemaVersion = '1.0',
    this.syntaxVersion = '1.0',
  });

  final String id;
  final List<MFBinding> bindings;
  final String schemaVersion;
  final String syntaxVersion;

  static MFBindingMap fromJson(Map<String, Object?> json) => MFBindingMap(
        id: json['id'] as String,
        schemaVersion: json['schema_version'] as String? ?? '1.0',
        syntaxVersion: json['syntax_version'] as String? ?? '1.0',
        bindings: ((json['bindings'] as List?) ?? const [])
            .map((b) => _parseBinding(b as Map<String, Object?>))
            .toList(growable: false),
      );

  static MFBinding _parseBinding(Map<String, Object?> json) => MFBinding(
        id: json['id'] as String,
        on: json['on'] as String,
        guard: json['guard'] == null ? null : MFExpr.parse(json['guard']),
        actions: ((json['actions'] as List?) ?? const [])
            .map((a) => MFAction.parse((a as Map).cast<String, Object?>()))
            .toList(growable: false),
        policy: switch (json['concurrency']) {
          'cancel-previous' => MFPolicy.cancelPrevious,
          'supersede' => MFPolicy.supersede,
          'queue' => MFPolicy.queue,
          'reject-new' => MFPolicy.rejectNew,
          null || _ => MFPolicy.undeclared,
        },
        errorBoundary:
            json['errors'] is Map ? mfErrorRefToString((json['errors'] as Map)['*'] ?? json['errors']) : null,
        onError: null,
      );
}
