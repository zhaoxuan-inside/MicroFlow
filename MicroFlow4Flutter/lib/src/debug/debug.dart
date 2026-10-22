import '../runtime/microflow_runtime.dart';

class DebugController {
  final List<DebugRecord> _records = <DebugRecord>[];
  bool _paused = false;

  bool get isPaused => _paused;
  Iterable<DebugRecord> get records => List.unmodifiable(_records);

  void record(String name, Map<String, Object?> payload) {
    _records.add(DebugRecord(name: name, payload: Map.unmodifiable(payload)));
  }

  void pause() => _paused = true;
  void resume() => _paused = false;

  DebugSnapshot snapshot(MicroFlowRuntime runtime) => DebugSnapshot(
    runtime: runtime.snapshot(),
    records: records,
    paused: _paused,
  );
}

class DebugRecord {
  DebugRecord({required this.name, required this.payload, DateTime? occurredAt})
    : occurredAt = (occurredAt ?? DateTime.now()).toUtc();

  final String name;
  final Map<String, Object?> payload;
  final DateTime occurredAt;
}

class DebugSnapshot {
  const DebugSnapshot({
    required this.runtime,
    required this.records,
    required this.paused,
  });

  final RuntimeSnapshot runtime;
  final Iterable<DebugRecord> records;
  final bool paused;
}
