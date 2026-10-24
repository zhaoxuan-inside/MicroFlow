/// Event emission interface: the runtime module's stable, minimal output
/// face toward the observability module (§24.7: the runtime is the only
/// emitter; the collection pipeline lives outside the runtime module).
///
/// Observability implements [MFEmissionSink] by building validated
/// Telemetry-Contract envelopes (§24.2), queuing and reporting. The runtime
/// depends on nothing beyond this interface, so observability and runtime
/// can evolve (and be released) independently.
library;

/// A raw, structured emission from a runtime interception boundary.
/// Field contract is relaxed (`Object?`) deliberately: schema enforcement is
/// the observability module's job (§24.2 envelope Schema validation).
typedef MFRawEvent = Map<String, Object?>;

/// Where the runtime hands its intercept-boundary events. Implementations
/// must never block or throw into the caller path (§24.2: collection
/// failures must not interrupt core user flows).
abstract class MFEmissionSink {
  void emit(MFRawEvent event);
}

/// Default no-op sink (drops events with a bounded counter) for previews
/// that have not attached an observability pipeline.
class MFNullEmissionSink implements MFEmissionSink {
  int emitted = 0;
  int dropped = 0;

  @override
  void emit(MFRawEvent event) {
    emitted++;
  }

  Map<String, Object?> dataQuality() => {'emitted': emitted, 'dropped': dropped};
}
