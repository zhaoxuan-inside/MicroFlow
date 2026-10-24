/// External experiment control-side integration (§24.4, §31): the framework
/// only validates, applies, freezes and reports assignments; allocation,
/// sample selection and metric computation live entirely outside.
library;

import 'package:microflow_model/microflow_model.dart';

/// External Provider contract (§31) surface rendered in Dart terms.
abstract class MFExperimentProvider {
  /// Returns a frozen assignment summary or null (no experiment context).
  Map<String, Object?>? resolveAssignment(String experimentId, String releaseContext);

  Map<String, Object?>? getExperimentConfig(String experimentId, String assignmentId);
}

/// A frozen assignment record validated at acceptance time.
class MFExperimentAssignment {
  MFExperimentAssignment({
    required this.experimentId,
    String? assignmentId,
    required this.variant,
    required this.assignmentSource,
    DateTime? frozenAt,
  }) : assignmentId = assignmentId ?? 'opaque-stable',
       frozenAt = (frozenAt ?? DateTime.now().toUtc()).toIso8601String();

  final String experimentId;
  final String assignmentId; // opaque, stable (§24.2)
  final String variant;
  final String frozenAt;
  final String assignmentSource;

  Map<String, Object?> toJson() => {
    'experiment_id': experimentId,
    'assignment_id': assignmentId,
    'variant': variant,
    'assignment_source': assignmentSource,
    'frozen_at': frozenAt,
  };
}

/// Runtime state: assignments are frozen once applied; history cannot be
/// silently rewritten (§24.5: historical exposure attribution cannot change).
class MFExperimentState {
  final Map<String, MFExperimentAssignment> _frozen = {};
  final List<MFDiag> diagnostics = [];

  void freeze(MFExperimentAssignment assignment) => _frozen.putIfAbsent(assignment.experimentId, () => assignment);

  bool isFrozen(String experimentId) => _frozen.containsKey(experimentId);

  String? variantOf(String experimentId) => _frozen[experimentId]?.variant;

  List<Map<String, Object?>> frozenAssignments() =>
      List.unmodifiable(_frozen.values.map((a) => a.toJson()));

  /// Accept a candidate assignment from the external side: platform/variant
  /// compatibility checks are the only hook implemented here; missing
  /// variants always degrade to the declared default (§24.4 baseline).
  void acceptCandidate(Map<String, Object?> candidate, {List<String> knownVariants = const []}) {
    final id = candidate['experiment_id'] as String?;
    final variant = candidate['variant'] as String? ?? 'control';
    if (id == null) {
      diagnostics.add(const MFDiag(MFCodes.expAssignmentIncompatible, '缺失 experiment_id，拒绝写入运行上下文'));
      return;
    }
    if (knownVariants.isNotEmpty && !knownVariants.contains(variant)) {
      diagnostics.add(MFDiag(MFCodes.expAssignmentIncompatible, 'variant $variant 未命中 variants，回退默认'));
      return;
    }
    freeze(
      MFExperimentAssignment(
        experimentId: id,
        assignmentId: candidate['assignment_id'] as String? ?? 'opaque-unstable',
        variant: variant,
        assignmentSource: candidate['assignment_source'] as String? ?? 'external-platform',
      ),
    );
  }

  /// Exposure events may only report after real visibility (§24.4); this
  /// helper only exists to gate manual attempt, which runtime denies.
  bool shouldConfirmExposure(String experimentId, {required bool visible}) =>
      visible && _frozen.containsKey(experimentId);
}
