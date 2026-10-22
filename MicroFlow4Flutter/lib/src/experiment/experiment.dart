class ExperimentAssignment {
  const ExperimentAssignment({
    required this.experimentId,
    required this.assignmentId,
    required this.variant,
    required this.configVersion,
  });

  final String experimentId;
  final String assignmentId;
  final String variant;
  final String configVersion;
}

abstract interface class ExperimentProvider {
  Future<ExperimentAssignment?> resolve(
    String experimentId, {
    required String subjectScope,
  });
}

/// Holds an externally resolved assignment; it never performs allocation.
class ExperimentContext {
  ExperimentContext({this.provider});

  final ExperimentProvider? provider;
  final Map<String, ExperimentAssignment> _assignments = {};

  ExperimentAssignment? operator [](String experimentId) =>
      _assignments[experimentId];

  void freeze(ExperimentAssignment assignment) {
    final current = _assignments[assignment.experimentId];
    if (current != null && current.assignmentId != assignment.assignmentId) {
      throw StateError('Experiment assignment is already frozen.');
    }
    _assignments[assignment.experimentId] = assignment;
  }
}
