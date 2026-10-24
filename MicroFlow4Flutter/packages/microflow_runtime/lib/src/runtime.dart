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
import 'business_fact.dart';
import 'recovery.dart';
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

  /// Business Fact channel (§24.1 第 4 类、§30.1): the runtime-declared
  /// explicit submission entry — the only sanctioned bypass of the
  /// zero-instrumentation rule (§24.7).
  late final MFBusinessFactChannel facts = MFBusinessFactChannel(runtime: this);

  /// Recovery executor (§16.1): collects and restores snapshots per the
  /// declared Recovery Contract.
  late final MFRecoveryExecutor recovery = MFRecoveryExecutor(runtime: this);
  List<MFPageInstance> stack = [];
  MFPageInstance? get current => stack.isEmpty ? null : stack.last;

  /// Render-generation signal (renderer rebuild trigger after state writes,
  /// §13.2 The runtime itself stays framework-owned).
  final ValueNotifier<int> generation = ValueNotifier<int>(0);

  /// 渲染修订号（§12.1/§22.3）：每次 generation 推进时经
  /// [MFInstanceIdentifiers.renderRevision] 取号，进入 Debug 上下文。
  int renderRevision = 0;

  void _bump() {
    renderRevision = ids.renderRevision();
    generation.value++;
  }

  /// Validation gate (§22.4): the runtime refuses to start on static error.
  MFValidationResult? lastValidation;

  /// Runtime diagnostics (§13.2 结构化运行诊断)：由 [diagSink] 承载，
  /// 内部发射统一走 sink；对外提供只读视图。
  final MFDiagSink diagSink = MFDiagSink();
  List<MFDiag> get diagnostics => diagSink.all;

  /// Unknown-result ledger (§22.1, baseline 27): unknown side effects are
  /// recorded once, queryable, never auto-retried.
  final List<Map<String, Object?>> unknownResults = [];

  /// External run references returned by the outer execution side (§24.8):
  /// opaque ids recorded into diagnostics, events and debug snapshots; the
  /// framework never interprets their internal structure.
  final List<String> externalRunRefs = [];

  /// Debug interception stream (§29): navigation/action/state events produced
  /// at interception boundaries only — business code has no instrumentation.
  final StreamController<Map<String, Object?>> _debugEvents =
      StreamController<Map<String, Object?>>.broadcast();
  Stream<Map<String, Object?>> get debugEvents => _debugEvents.stream;

  /// Declared checkpoints (§29): bindings a debug session may pause at.
  final Set<String> checkpoints = {};
  final Map<String, Completer<void>> _checkpointGates = {};

  void declareCheckpoints(Iterable<String> bindingIds) => checkpoints.addAll(bindingIds);

  /// Arm a checkpoint: the next execution of [bindingId] suspends until
  /// [resumeCheckpoint]. Authorization is checked by the observability debug
  /// controller (§29 grants); the runtime only executes the gate.
  void pauseAt(String bindingId) => _checkpointGates.putIfAbsent(bindingId, Completer<void>.new);

  Future<void> resumeCheckpoint(String bindingId) async {
    final gate = _checkpointGates.remove(bindingId);
    if (gate != null && !gate.isCompleted) {
      gate.complete();
    }
  }

  /// Bindings with a run currently in flight (recovery snapshot
  /// pending_actions, §16.1).
  List<String> get inFlightBindings => [
        for (final e in _inFlight.entries)
          if (e.value) e.key,
      ];

  /// Record an unknown side effect once (§22.1): ledgered, queryable,
  /// `auto_retry` pinned false (baseline 27).
  void recordUnknown({required String call, required String requestId, required String reason}) {
    unknownResults.add({
      'call': call,
      'action_request_id': requestId,
      'reason': reason,
      'state': 'unknown',
      'auto_retry': false,
      'at': DateTime.now().toUtc().toIso8601String(),
    });
  }

  void _debug(String kind, Map<String, Object?> payload) {
    if (!_debugEvents.hasListener) return;
    _debugEvents.add({
      'kind': kind,
      'at': DateTime.now().toUtc().toIso8601String(),
      ...payload,
    });
  }

  /// Expression evaluation exposed for the interpreter (structured subset,
  /// §37.2). Call expressions evaluate to unknown here; functions run via
  /// action chains only.
  Object? safeEval(MFExpr expr, EvalContext ctx) {
    try {
      return _evaluator.eval(expr, ctx);
    } catch (err) {
      diagSink.add(MFDiag(MFCodes.interactionUnknownMember, '表达式求值失败：$err', stage: Stage.runtime));
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
        diagSink.add(d);
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
      diagSink.add(MFDiag(MFCodes.navUnknownTarget, '导航目标 $targetName 不存在', stage: Stage.runtime));
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
    _debug('navigation', {
      'page_definition_id': target.id,
      'page_instance_id': instance.id,
      'route': target.route,
      'entry': stack.length == 1 ? 'external' : 'push',
    });
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
      diagSink.add(MFDiag(MFCodes.bindingEventUnknown, '执行未发现的绑定 $bindingId', stage: Stage.runtime));
      return MFActionResult(requestId: requestId, results: {});
    }
    _emitStandard('ops.feature.used', {
      'feature_ref': binding.id,
      'context_route': page.definition.route,
    }, page: page, interactionId: binding.id, actionRequestId: requestId);
    _debug('action', {'binding_id': binding.id, 'action_request_id': requestId, 'route': page.definition.route});

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
    Completer<void>? queueSlot;
    try {
      if (binding.policy == MFPolicy.queue) {
        // queue 并发策略（§39.1）：同一绑定的重复触发按声明顺序排队
        // 串行执行，不并发也不拒绝。
        final prev = _queueTails[binding.id] ?? Future<void>.value();
        final slot = Completer<void>();
        _queueTails[binding.id] = slot.future;
        queueSlot = slot;
        await prev;
      }
      // Checkpoint gate (§29): an armed checkpoint suspends the run before
      // the action chain so the debug session can read a snapshot; resuming
      // is explicit and idempotent.
      final gate = _checkpointGates[binding.id];
      if (gate != null) {
        _debug('checkpoint', {'binding_id': binding.id, 'action_request_id': requestId});
        await gate.future;
      }
      return await _runChain(binding, requestId, token, ctx, page);
    } finally {
      _inFlight[binding.id] = false;
      queueSlot?.complete();
      if (queueSlot != null && identical(_queueTails[binding.id], queueSlot.future)) {
        _queueTails.remove(binding.id);
      }
    }
  }

  final Map<String, bool> _inFlight = {};
  final Map<String, int> _tokens = {};
  final Map<String, int> _superseded = {};

  /// queue 并发策略的执行尾指针（§39.1）：指向当前排队的最后一个 run，
  /// 后续触发等待其完成。
  final Map<String, Future<void>> _queueTails = {};

  static const _evaluator = MFExprEvaluator();

  EvalContext _context(MFPageInstance page, Map<String, Object?> props) => EvalContext(
        state: state,
        props: props,
        params: page.params,
        prev: const {},
        providedRoots: [ProvidedScope(id: page.definition.id, values: page.provided)],
      );

  Future<MFActionResult> _runChain(
      MFBinding binding, String requestId, int token, EvalContext ctx, MFPageInstance page) async {
    final results = <String, Object?>{};
    Object? last;
    for (final action in binding.actions) {
      if ((_superseded[binding.id] ?? -1) >= token) {
        // This run was superseded/cancelled (baseline 26).
        return MFActionResult(requestId: requestId, results: results);
      }
      last = await _runAction(action, ctx, page: page, requestId: requestId);
      final as = action is MFAdapterAction ? action.as : null;
      ctx = ctx.withPrev(as, last);
    }
    results['last'] = last;
    return MFActionResult(requestId: requestId, results: results);
  }

  Future<Object?> _runAction(MFAction action, EvalContext ctx,
      {required MFPageInstance page, required String requestId}) async {
    switch (action) {
      case MFStateAction s:
        final value = _evaluator.eval(s.value, ctx);
        if (s.scope == 'component') {
          throw StateError('component 状态只能写组件内部，不进入页面绑定（§6）');
        }
        // 作用域映射（§11）：page/session/product 各层如实落位；persistent
        // 的持久化与版本迁移随发布面交付（§11 纪律），此处不静默改写。
        final scope = switch (s.scope) {
          'session' => 'session',
          'product' => 'product',
          _ => 'page',
        };
        state.writeDeep(scope, s.target, value);
        _debug('state', {'target': s.target, 'scope': scope, 'action_request_id': requestId});
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
          diagSink.add(MFDiag(MFCodes.capUnavailable, '动作调用 ${a.call} 无可用实现', stage: Stage.runtime));
          recordUnknown(call: a.call, requestId: requestId, reason: 'unregistered-call');
          return const MFUnknownResult();
        }
        final args = {
          for (final e in a.arguments.entries) e.key: _evaluator.eval(e.value, ctx),
        };
        // Trace propagation (§24.8, baseline 11): declared propagation gets a
        // runtime-injected outbound context (trace_id, release_id, page
        // instance id, action_request_id); business code and adapter
        // implementations never construct trace identity themselves.
        final trace = entry?.contract.trace;
        if (trace != null && trace.direction != 'inbound') {
          for (final carrier in trace.carrier) {
            args[carrier] = {
              'trace_id': ids.traceId,
              'release_id': ids.releaseId,
              'page_instance_id': page.id,
              'action_request_id': requestId,
            };
          }
        }
        // Telemetry annotation (§24.7, baseline 8): annotated events go
        // through the same full collection pipeline; privacy class and
        // sampling come from the declaration, not from business code.
        final annotation = entry?.contract.telemetry;
        if (annotation != null) {
          _emitAnnotated(annotation, 'entry', page, interactionId: a.call, actionRequestId: requestId);
        }
        final int timeout = (impl as dynamic).timeoutMs as int? ?? a.timeoutMs;
        try {
          final result = await (impl as dynamic).fn(args).timeout(Duration(milliseconds: timeout));
          if (annotation != null) {
            _emitAnnotated(annotation, 'success', page, interactionId: a.call, actionRequestId: requestId);
          }
          // Opaque external run reference (§24.8): recorded, never
          // interpreted; declared propagation without a returned reference is
          // a recorded reason, not a call failure.
          final runRef = result is Map ? result['external_run_ref'] : null;
          if (runRef is String && runRef.isNotEmpty) {
            externalRunRefs.add(runRef);
          } else if (trace != null) {
            diagSink.add(MFDiag(MFCodes.teleTraceRefMissing, '动作 ${a.call} 声明了追踪传播但未返回运行引用',
                stage: Stage.runtime, severity: Severity.info));
          }
          return _validateOutput(a, entry, result, requestId: requestId);
        } on TimeoutException {
          // Timeout is not "not executed" (§10): unknown result surfaces,
          // enters the ledger (§22.1, baseline 27) and is never auto-retried.
          diagSink.add(MFDiag(MFCodes.dataTimeout, '动作 ${a.call} 超时，进入 unknown', stage: Stage.runtime));
          recordUnknown(call: a.call, requestId: requestId, reason: 'timeout');
          if (annotation != null) {
            _emitAnnotated(annotation, 'failure', page, interactionId: a.call, actionRequestId: requestId);
          }
          return const MFUnknownResult();
        } catch (err) {
          if (annotation != null) {
            _emitAnnotated(annotation, 'failure', page, interactionId: a.call, actionRequestId: requestId);
          }
          return {'error': '$err'};
        }
      case MFUiAction u:
        return {'ui': u.op};
    }
  }

  /// Adapter output Schema validation (§40.3, baseline 4): mismatches are
  /// typed errors, never silently truncated; the failed side effect enters
  /// the unknown ledger (§22.1).
  Object? _validateOutput(MFAdapterAction action, MFResourceEntry? entry, Object? result,
      {required String requestId}) {
    final contract = entry?.contract;
    final outputSpec = contract?.props['output'];
    if (outputSpec == null) return result;
    final value = result is Map && result.containsKey('output') ? result['output'] : result;
    if (!outputSpec.check(value)) {
      diagSink.add(MFDiag(MFCodes.dataOutputInvalid, '动作 ${action.call} 输出不符 output 声明', stage: Stage.runtime));
      recordUnknown(call: action.call, requestId: requestId, reason: 'output-schema-mismatch');
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
    String privacyClass = 'operational',
  }) {
    final raw = <String, Object?>{
      'event_name': event,
      'payload': payload,
      // 运行时拦截边界来源标记（§24.7）：观测面据此区分零埋点发射与业务侧
      // 对标准事件族的手工上报（后者被拒绝并产生 mf.tele.manual-standard-event）。
      'mf_source': 'runtime-intercept',
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
      'privacy_class': privacyClass,
      'identity': {'user_ref': null, 'device_ref': null, 'exp_subject_ref': null},
      'experiment_assignments': page.frozen.experiments,
    };
    try {
      emissionSink.emit(raw);
    } catch (_) {
      // Collection failures never interrupt core user flows (§24.2).
    }
  }

  /// Annotated touchpoint emission (§24.7, baseline 8): declared events go
  /// through the same pipeline as standard events — Schema validation,
  /// identity injection, queue and privacy checks all apply (no bypass for
  /// declarative origins).
  void _emitAnnotated(
    MFTelemetryAnnotation annotation,
    String touchpoint,
    MFPageInstance page, {
    String? interactionId,
    String? actionRequestId,
  }) {
    final eventName = annotation.events[touchpoint];
    if (eventName == null) return;
    final ratio = annotation.samplingRatio;
    if (ratio != null && !_sampled(ratio, actionRequestId ?? interactionId ?? eventName)) return;
    _emitStandard(
      eventName,
      {'touchpoint': touchpoint, 'feature_ref': interactionId},
      page: page,
      interactionId: interactionId,
      actionRequestId: actionRequestId,
      privacyClass: annotation.privacyClass,
    );
  }

  /// Deterministic ratio sampling keyed by request id (§24.7 sampling_policy
  /// `kind: ratio`): the same request always gets the same decision.
  bool _sampled(double ratio, String key) {
    if (ratio >= 1) return true;
    if (ratio <= 0) return false;
    return key.hashCode.abs() % 10000 < (ratio * 10000).round();
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
        // 边界归属（§13.2/§37.4）：绑定级声明优先，其次页面级默认边界，
        // 最后运行时兜底边界。
        final boundaryId = b.errorBoundary ?? current?.definition.errorBoundary ?? 'runtime-default';
        final info = MFBoundaryInfo(boundaryId: boundaryId, error: err);
        boundaryHandler.capture(MFInstanceIdentifiers.newRequestId(), info);
      }
    }
    if (boundaryThrown) {
      // Errors entered the declared boundary; the incident does not spread
      // beyond the dispatch layer (§37.4 declared propagation).
      diagSink.add(
        const MFDiag(MFCodes.interactionErrorPropagation, '绑定执行进入边界处理', stage: Stage.runtime, severity: Severity.info),
      );
    }
  }

  /// Debug contract surface output (§29): runtime context read; snapshots
  /// are bounded and masked by the observability module. External run
  /// references (§24.8) and unknown side effects are reachable here.
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
        'external_run_refs': List.of(externalRunRefs),
        'unknown_results': List.of(unknownResults),
        'render_revision': renderRevision,
      };
}
