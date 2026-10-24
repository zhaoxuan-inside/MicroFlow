/// The interpretive runtime (§13.2): owns page instances, navigation,
/// state lifecycle, event dispatch, action execution, interception points
/// and structured diagnostics.
///
/// Invariants (§2.9, §13.2): the runtime never modifies project
/// definitions; running instances hold the frozen release model; the
/// runtime is the only emitter of standard operational events (§24.7) and
/// pushes them through the [MFEmissionSink] boundary — the collection
/// pipeline (envelope, queue, privacy) belongs to the observability module.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:microflow_model/microflow_model.dart';

import 'error_boundary.dart';
import 'registry.dart';
import 'event_emission.dart';
import 'expression.dart';
import 'instance_ids.dart';
import 'state_store.dart';
import 'validator.dart';

/// Result of executing one binding action chain.
class MFActionResult {
  MFActionResult({
    required this.requestId,
    required this.results,
    this.boundary,
    this.unknownSideEffects = const [],
  });

  final String requestId;
  final Map<String, Object?> results; // as/name -> value; 'last' is final
  final MFBoundaryInfo? boundary;
  final List<String> unknownSideEffects;
}

/// A live page instance: identity, frozen context, parameters and page state
/// (§2.6). Instance state is created and destroyed with the instance.
class MFPageInstance {
  MFPageInstance({
    required this.id,
    required this.definition,
    required this.params,
    required this.frozen,
    required this.provided,
  });

  final String id;
  final MFPage definition;
  final Map<String, Object?> params;

  /// Frozen context: config versions, theme, locale and experiment
  /// assignment summaries (§4.5, §24.5; baseline 7).
  final MFFrozenContext frozen;

  /// Information values exposed by the page's info contract `provides`
  /// (§2.8). Values are loaded through the onEnter binding; data value
  /// ownership stays at the instance boundary.
  final Map<String, Object?> provided;
}

/// Frozen per-instance context (baseline 7: switching locale/theme/experiment
/// assignments only affects new instances).
class MFFrozenContext {
  const MFFrozenContext({
    required this.configVersion,
    required this.theme,
    required this.locale,
    this.experiments = const [],
  });

  final String configVersion;
  final String theme;
  final String locale;
  final List<Map<String, Object?>> experiments;
}

/// An unknown side-effect result (§22.1): never auto-retried (baseline 27).
class MFUnknownResult {
  const MFUnknownResult();
  Map<String, Object?> toJson() => {'state': 'unknown', 'auto_retry': false};
}

/// The runtime.
class MFRuntime {
  MFRuntime({
    required this.project,
    required this.registry,
    required this.ids,
    required this.emissionSink,
    List<Map<String, Object?>> Function()? experimentAssignments,
    String Function()? themeProvider,
    MFBoundaryHandler? boundaryHandler,
    this.configVersion = 'config-1',
    this.theme = 'theme-light',
  })  : assignmentsProvider =
            experimentAssignments ?? (experimentAssignments == null ? () => const [] : throw StateError('unreachable')),
        themeProvider = themeProvider ?? (themeProvider == null ? () => theme : throw StateError('unreachable')),
        boundaryHandler = boundaryHandler ?? MFBoundaryHandler();

  final MFProject project;
  final MFRegistry registry;
  final MFInstanceIdentifiers ids;
  final MFEmissionSink emissionSink;

  /// Frozen experiment summaries (§24.5). Supplied by the observability
  /// module's experiment state; the runtime never allocates or decides.
  final List<Map<String, Object?>> Function() assignmentsProvider;

  MFBoundaryHandler boundaryHandler;
  final String configVersion;
  final String theme;

  /// Theme selection for newly created instances (§36.3/§42.5, baseline 7):
  /// switching only affects new instances, never silently rewrites running
  /// ones — their frozen context keeps the selection recorded at creation.
  final String Function()? themeProvider;

  late final MFStateStore state = MFStateStore();
  List<MFPageInstance> stack = [];
  MFPageInstance? get current => stack.isEmpty ? null : stack.last;

  /// Render-generation signal (renderer rebuild trigger after state writes,
  /// §13.2 The runtime itself stays framework-owned).
  final ValueNotifier<int> generation = ValueNotifier<int>(0);
  void _bump() => generation.value++;

  /// Validation gate (§22.4): the runtime refuses to start on static error.
  MFValidationResult? lastValidation;

  final List<MFDiag> diagnostics = [];

  /// Expression evaluation exposed for the interpreter (structured subset,
  /// §37.2). Call expressions evaluate to unknown here; functions run via
  /// action chains only.
  Object? safeEval(MFExpr expr, EvalContext ctx) {
    try {
      return _evaluator.eval(expr, ctx);
    } catch (err) {
      diagnostics.add(MFDiag(MFCodes.interactionUnknownMember, '表达式求值失败：$err', stage: Stage.runtime));
      return null;
    }
  }

  bool get canStart {
    lastValidation ??= MFValidator(project: project, registry: registry).validate();
    return lastValidation!.ok;
  }

  /// Start the product instance and land on the entry page.
  Future<void> start() async {
    if (stack.isNotEmpty) {
      return;
    }
    if (!canStart) {
      final errors = lastValidation!.diagnostics.where((d) => d.severity == Severity.error);
      for (final d in errors) {
        diagnostics.add(d);
      }
      throw StateError('项目未通过静态校验，拒绝进入运行');
    }
    final entry = project.manifest.entryPage ?? project.pages.first.id;
    await push(entry, kind: 'replace');
  }

  /// Navigate (§9 edges: push, replace, modal, back). Emits `ops.page.left`
  /// and `ops.page.viewed` (baseline 29) through the interception boundary.
  Future<void> push(String targetName, {String kind = 'push', Map<String, Object?> args = const {}}) async {
    final target = project.page(targetName);
    if (target == null) {
      diagnostics.add(MFDiag(MFCodes.navUnknownTarget, '导航目标 $targetName 不存在', stage: Stage.runtime));
      return;
    }
    if (kind == 'back' && stack.length <= 1) {
      return;
    }
    final left = current;
    if (left != null) {
      _emitStandard('ops.page.left', {
        'page_definition_id': left.definition.id,
        'stay_ms': DateTime.now().difference(_enteredAt(left.id)).inMilliseconds,
        'exit': kind == 'back' ? 'push' : kind,
      }, page: left);
    }
    if (kind == 'replace' || kind == 'back') {
      if (stack.isNotEmpty) {
        stack.removeLast();
        if (kind == 'back') {
          final prev = stack.last; // the previous page remains live
          _emitStandard('ops.page.viewed', {
            'page_definition_id': prev.definition.id,
            'entry': 'back',
            'referrer_route': target.route,
            'locale': prev.frozen.locale,
          }, page: prev);
          _bump();
          return;
        }
      }
    }
    await _open(targetName, args);
  }

  final Map<String, DateTime> _enterTimes = {};

  DateTime _enteredAt(String id) => _enterTimes[id] ?? DateTime.now();

  Future<void> _open(String targetName, Map<String, Object?> args) async {
    final target = project.page(targetName)!;
    final instance = MFPageInstance(
      id: ids.pageInstanceId(),
      definition: target,
      params: args,
      frozen: _freeze(),
      provided: {},
    );
    _enterTimes[instance.id] = DateTime.now();
    stack.add(instance);
    _bump();
    _emitStandard('ops.page.viewed', {
      'page_definition_id': target.id,
      'entry': stack.length == 1 ? 'external' : 'push',
      'referrer_route': null,
      'locale': instance.frozen.locale,
    }, page: instance);
    if (target.onEnter != null) {
      await execute(target.onEnter!);
    }
  }

  /// Freezing: config/theme/locale/experiment summary at instance creation.
  MFFrozenContext _freeze() => MFFrozenContext(
        configVersion: configVersion,
        theme: themeProvider != null ? themeProvider!() : theme,
        locale: project.manifest.defaultLocale,
        experiments: assignmentsProvider(),
      );

  /// Execute a named binding (§39.1). `ops.feature.used` and error
  /// handling happen here and never in business code (§24.7).
  Future<MFActionResult> execute(String bindingId, {Map<String, Object?> props = const {}}) async {
    final binding = project.findBinding(bindingId);
    final page = current!;
    final requestId = MFInstanceIdentifiers.newRequestId();
    if (binding == null) {
      diagnostics.add(MFDiag(MFCodes.bindingEventUnknown, '执行未发现的绑定 $bindingId', stage: Stage.runtime));
      return MFActionResult(requestId: requestId, results: {});
    }
    _emitStandard('ops.feature.used', {
      'feature_ref': binding.id,
      'context_route': page.definition.route,
    }, page: page, interactionId: binding.id, actionRequestId: requestId);

    var ctx = _context(page, props);
    if (binding.guard != null) {
      final ok = _evaluator.eval(binding.guard!, ctx) == true;
      if (!ok) {
        return MFActionResult(requestId: requestId, results: const {'guard': false});
      }
    }

    // Concurrency discipline (baseline 26) per-entry; undeclared always
    // rejects duplicates. cancel/supersede signal the previous run via a
    // token; the new run proceeds while the old run aborts at its gates.
    final inFlight = _inFlight[binding.id] == true;
    final token = (_tokens[binding.id] ?? 0) + 1;
    _tokens[binding.id] = token;
    switch (binding.policy) {
      case MFPolicy.rejectNew:
      case MFPolicy.undeclared:
        if (inFlight) {
          return MFActionResult(requestId: requestId, results: const {'rejected-concurrency': true});
        }
        break;
      case MFPolicy.cancelPrevious:
      case MFPolicy.supersede:
        _superseded[binding.id] = token - 1;
        break;
      case MFPolicy.queue:
        break;
    }
    _superseded.remove(binding.id);
    _inFlight[binding.id] = true;
    try {
      return await _runChain(binding, requestId, token, ctx);
    } finally {
      _inFlight[binding.id] = false;
    }
  }

  final Map<String, bool> _inFlight = {};
  final Map<String, int> _tokens = {};
  final Map<String, int> _superseded = {};

  static const _evaluator = MFExprEvaluator();

  EvalContext _context(MFPageInstance page, Map<String, Object?> props) => EvalContext(
        state: state,
        props: props,
        params: page.params,
        prev: const {},
        providedRoots: [ProvidedScope(id: page.definition.id, values: page.provided)],
      );

  Future<MFActionResult> _runChain(MFBinding binding, String requestId, int token, EvalContext ctx) async {
    final results = <String, Object?>{};
    Object? last;
    for (final action in binding.actions) {
      if ((_superseded[binding.id] ?? -1) >= token) {
        // This run was superseded/cancelled (baseline 26).
        return MFActionResult(requestId: requestId, results: results);
      }
      last = await _runAction(action, ctx);
      final as = action is MFAdapterAction ? action.as : null;
      ctx = ctx.withPrev(as, last);
    }
    results['last'] = last;
    return MFActionResult(requestId: requestId, results: results);
  }

  Future<Object?> _runAction(MFAction action, EvalContext ctx) async {
    switch (action) {
      case MFStateAction s:
        final value = _evaluator.eval(s.value, ctx);
        if (s.scope == 'component') {
          throw StateError('component 状态只能写组件内部，不进入页面绑定（§6）');
        }
        state.writeDeep(s.scope == 'session' ? 'session' : 'page', s.target, value);
        Future.microtask(_bump);
        return value;
      case MFEventAction e:
        // Event rise is composition semantics (§39.1); the runtime does not
        // re-dispatch anything undeclared by a component contract.
        return e.event;
      case MFNavigationAction n:
        await push(
          n.target,
          args: {
            for (final e in n.arguments.entries) e.key: _evaluator.eval(e.value, ctx),
          },
        );
        return {'navigated': n.target};
      case MFAdapterAction a:
        final entry = registry.entry(a.call);
        final dynamic impl = switch (entry?.impl) {
          MFFunctionImpl f => f,
          MFAdapterImpl x => x,
          MFCapabilityImpl c => c,
          _ => null,
        };
        if (impl == null) {
          diagnostics.add(MFDiag(MFCodes.capUnavailable, '动作调用 ${a.call} 无可用实现', stage: Stage.runtime));
          return const MFUnknownResult();
        }
        final args = {
          for (final e in a.arguments.entries) e.key: _evaluator.eval(e.value, ctx),
        };
        final int timeout = (impl as dynamic).timeoutMs as int? ?? a.timeoutMs;
        try {
          final result = await (impl as dynamic).fn(args).timeout(Duration(milliseconds: timeout));
          return _validateOutput(a, entry, result);
        } on TimeoutException {
          // Timeout is not "not executed" (§10): unknown result surfaces.
          diagnostics.add(MFDiag(MFCodes.dataTimeout, '动作 ${a.call} 超时，进入 unknown', stage: Stage.runtime));
          return const MFUnknownResult();
        } catch (err) {
          return {'error': '$err'};
        }
      case MFUiAction u:
        return {'ui': u.op};
    }
  }

  /// Adapter output Schema validation (§40.3, baseline 4): mismatches are
  /// typed errors, never silently truncated.
  Object? _validateOutput(MFAdapterAction action, MFResourceEntry? entry, Object? result) {
    final contract = entry?.contract;
    final outputSpec = contract?.props['output'];
    if (outputSpec == null) return result;
    final value = result is Map && result.containsKey('output') ? result['output'] : result;
    if (!outputSpec.check(value)) {
      diagnostics.add(MFDiag(MFCodes.dataOutputInvalid, '动作 ${action.call} 输出不符 output 声明', stage: Stage.runtime));
      return const MFUnknownResult();
    }
    return result;
  }

  /// Interception-bound standard events (§24.7): the runtime is the only
  /// emitter; manual reporting from business code is denied by the design.
  void _emitStandard(
    String event,
    Map<String, Object?> payload, {
    required MFPageInstance page,
    String? interactionId,
    String? actionRequestId,
  }) {
    final raw = <String, Object?>{
      'event_name': event,
      'payload': payload,
      'session_id': ids.sessionId,
      'page_instance_id': page.id,
      'route': page.definition.route,
      'release_id': ids.releaseId,
      'renderer_version': ids.rendererVersion,
      'renderer_package': ids.rendererPackage,
      'environment': ids.environment,
      'trace_id': ids.traceId,
      'interaction_id': ?interactionId,
      'action_request_id': ?actionRequestId,
      'identity': {'user_ref': null, 'device_ref': null, 'exp_subject_ref': null},
      'experiment_assignments': page.frozen.experiments,
    };
    try {
      emissionSink.emit(raw);
    } catch (_) {
      // Collection failures never interrupt core user flows (§24.2).
    }
  }

  /// Node-event dispatch (render -> runtime): resolves binding entries
  /// anchored on `<nodeId>.<event>` (§39). Business code cannot be in the
  /// path; evaluation order is declaration order (deterministic).
  Future<void> dispatchEvent(String nodeId, String event) async {
    final order = project.bindingsFor('$nodeId.$event');
    if (order.isEmpty) {
      return;
    }
    var boundaryThrown = false;
    for (final b in order) {
      try {
        await execute(b.id);
      } catch (err) {
        boundaryThrown = true;
        final info = MFBoundaryInfo(boundaryId: b.errorBoundary ?? 'runtime-default', error: err);
        boundaryHandler.capture(MFInstanceIdentifiers.newRequestId(), info);
      }
    }
    if (boundaryThrown) {
      // Errors entered the declared boundary; the incident does not spread
      // beyond the dispatch layer (§37.4 declared propagation).
      diagnostics.add(
        const MFDiag(MFCodes.interactionErrorPropagation, '绑定执行进入边界处理', stage: Stage.runtime, severity: Severity.info),
      );
    }
  }

  /// Debug contract surface output (§29): runtime context read; snapshots
  /// are bounded and masked by the observability module.
  Map<String, Object?> debugContext() => {
        'release_id': ids.releaseId,
        'renderer_version': ids.rendererVersion,
        'trace_id': ids.traceId,
        'stack': [
          for (final p in stack)
            {'page_instance_id': p.id, 'page_definition_id': p.definition.id, 'route': p.definition.route, 'params': p.params},
        ],
        'session_state': state.snapshotSession(),
        'experiment_assignments': current?.frozen.experiments ?? const [],
      };
}
