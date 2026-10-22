# MicroFlow4Flutter

Flutter Renderer and runtime contracts for the MicroFlow frontend model.

```text
Project Model → Runtime → Flutter Renderer / Host
                       ↓
             Debug / Telemetry / Experiment
```

The first slice provides stable project/page definitions, page lifecycle and navigation, bounded telemetry collection, local debug snapshots, an external experiment-provider contract with frozen assignments, and a minimal `MicroFlowApp` renderer entry point.

This package is a framework foundation. Data ingestion/query, authentication, persistent recovery, remote production debug, and experiment allocation remain host/provider responsibilities described by the frontend design.

Run checks from this directory:

```text
flutter analyze
flutter test
```
