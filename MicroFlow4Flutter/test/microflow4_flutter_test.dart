import 'package:flutter_test/flutter_test.dart';
import 'package:microflow4_flutter/microflow4_flutter.dart';

void main() {
  test('runtime navigates and records a traceable event', () {
    final project = ProjectModel(
      projectId: 'test-project',
      schemaVersion: 'microflow-project-v1',
      releaseId: 'release-1',
      entryPageId: 'home',
      pages: [
        PageDefinition(
          id: 'home',
          route: '/',
          title: 'Home',
          builder: (_) => 'home',
        ),
        PageDefinition(
          id: 'settings',
          route: '/settings',
          title: 'Settings',
          builder: (_) => 'settings',
        ),
      ],
    );
    final runtime = MicroFlowRuntime(project: project);

    runtime.start();
    expect(runtime.currentPageId, 'home');
    runtime.navigate('settings');

    expect(runtime.currentPageId, 'settings');
    expect(runtime.telemetry.events.last.pageId, 'settings');
    expect(runtime.debug.records.last.payload['page_id'], 'settings');
  });

  test('experiment assignments are frozen', () {
    final context = ExperimentContext();
    context.freeze(
      const ExperimentAssignment(
        experimentId: 'checkout-copy',
        assignmentId: 'assignment-1',
        variant: 'new',
        configVersion: 'v2',
      ),
    );

    expect(
      () => context.freeze(
        const ExperimentAssignment(
          experimentId: 'checkout-copy',
          assignmentId: 'assignment-2',
          variant: 'control',
          configVersion: 'v2',
        ),
      ),
      throwsStateError,
    );
  });
}
