/// Error boundaries and structured diagnostics (§13.2, §22.3).
///
/// Boundaries are declared resources; runtime errors are captured at action
/// execution and adapter boundaries and carry the diagnostic chain ids so a
/// user action can be tracked to state, host calls and final render.
library;

import 'package:microflow_model/microflow_model.dart';

/// Structured runtime diagnostic info, anchored to a page/action chain.
class MFBoundaryInfo {
  const MFBoundaryInfo({required this.boundaryId, required this.error, this.digest});
  final String boundaryId;
  final Object error;
  final String? digest;

  Map<String, Object?> toJson() => {'boundary_id': boundaryId, 'error': '$error'};
}

/// Boundary handler: declared scope only (§12.1 error_boundary).
class MFBoundaryHandler {
  final List<({String actionRequestId, MFBoundaryInfo info})> captured = [];

  void capture(String actionRequestId, MFBoundaryInfo info) {
    captured.add((actionRequestId: actionRequestId, info: info));
  }

  /// Boundary report digest is bounded; replay-sensitive payload is not
  /// persisted here (§29 snapshot discipline).
  List<Map<String, Object?>> report() => [
        for (final c in captured)
          {'action_request_id': c.actionRequestId, ...c.info.toJson()},
      ];
}

/// Runtime diagnostic sink (§13.2 结构化运行诊断).
class MFDiagSink {
  final List<MFDiag> _diags = [];

  void add(MFDiag diag) => _diags.add(diag);

  List<MFDiag> get all => List.unmodifiable(_diags);

  List<MFDiag> whereCode(String code) => _diags.where((d) => d.code == code).toList();

  void clear() => _diags.clear();
}
