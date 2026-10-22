import 'package:flutter/foundation.dart';

import '../debug/debug.dart';
import '../model/project_model.dart';
import '../telemetry/telemetry.dart';

/// Owns navigation, page lifecycle and observable runtime state.
class MicroFlowRuntime extends ChangeNotifier {
  MicroFlowRuntime({
    required this.project,
    TelemetryCollector? telemetry,
    DebugController? debug,
  }) : telemetry = telemetry ?? TelemetryCollector(),
       debug = debug ?? DebugController();

  final ProjectModel project;
  final TelemetryCollector telemetry;
  final DebugController debug;

  String? _currentPageId;
  Object? _currentArguments;
  int _revision = 0;
  bool _started = false;

  String? get currentPageId => _currentPageId;
  Object? get currentArguments => _currentArguments;
  int get revision => _revision;
  bool get isStarted => _started;

  PageDefinition get currentPage {
    final id = _currentPageId ?? project.entryPageId;
    if (id == null) throw StateError('Project has no entry page.');
    final page = project.page(id);
    if (page == null) throw StateError('Unknown page: $id');
    return page;
  }

  void start({String? pageId, Object? arguments}) {
    if (_started) return;
    _started = true;
    navigate(
      pageId ?? project.entryPageId!,
      arguments: arguments,
      replace: true,
    );
  }

  void navigate(String pageId, {Object? arguments, bool replace = false}) {
    final page = project.page(pageId);
    if (page == null) throw StateError('Unknown page: $pageId');
    _currentPageId = page.id;
    _currentArguments = arguments;
    _revision++;
    telemetry.record(
      TelemetryEvent.navigation(
        releaseId: project.releaseId,
        pageId: page.id,
        route: page.route,
        revision: _revision,
        replace: replace,
      ),
    );
    debug.record('navigation', <String, Object?>{
      'page_id': page.id,
      'route': page.route,
      'revision': _revision,
      'replace': replace,
    });
    notifyListeners();
  }

  void stop() {
    if (!_started) return;
    _started = false;
    _currentPageId = null;
    _currentArguments = null;
    notifyListeners();
  }

  RuntimeSnapshot snapshot() => RuntimeSnapshot(
    releaseId: project.releaseId,
    pageId: _currentPageId,
    revision: _revision,
    arguments: _currentArguments,
  );
}

class RuntimeSnapshot {
  const RuntimeSnapshot({
    required this.releaseId,
    required this.pageId,
    required this.revision,
    required this.arguments,
  });

  final String releaseId;
  final String? pageId;
  final int revision;
  final Object? arguments;
}
