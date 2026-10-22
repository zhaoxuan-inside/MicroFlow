import 'dart:collection';

enum TelemetryKind { diagnostic, operational, performance, businessFact }

class TelemetryEvent {
  const TelemetryEvent({
    required this.eventId,
    required this.name,
    required this.kind,
    required this.occurredAt,
    required this.releaseId,
    this.pageId,
    this.payload = const {},
  });

  factory TelemetryEvent.navigation({
    required String releaseId,
    required String pageId,
    required String route,
    required int revision,
    required bool replace,
  }) => TelemetryEvent(
    eventId: 'navigation-$releaseId-$revision',
    name: 'navigation',
    kind: TelemetryKind.operational,
    occurredAt: DateTime.now().toUtc(),
    releaseId: releaseId,
    pageId: pageId,
    payload: {'route': route, 'revision': revision, 'replace': replace},
  );

  final String eventId;
  final String name;
  final TelemetryKind kind;
  final DateTime occurredAt;
  final String releaseId;
  final String? pageId;
  final Map<String, Object?> payload;
}

abstract interface class TelemetrySink {
  void write(TelemetryEvent event);
}

class TelemetryCollector {
  TelemetryCollector({
    this.maxEvents = 256,
    List<TelemetrySink> sinks = const [],
  }) : _sinks = List.unmodifiable(sinks);

  final int maxEvents;
  final List<TelemetrySink> _sinks;
  final Queue<TelemetryEvent> _events = ListQueue<TelemetryEvent>();

  Iterable<TelemetryEvent> get events => UnmodifiableListView(_events.toList());

  void record(TelemetryEvent event) {
    if (maxEvents <= 0) return;
    if (_events.length >= maxEvents) _events.removeFirst();
    _events.addLast(event);
    for (final sink in _sinks) {
      try {
        sink.write(event);
      } catch (_) {
        // Telemetry failures must not block the user flow.
      }
    }
  }
}
