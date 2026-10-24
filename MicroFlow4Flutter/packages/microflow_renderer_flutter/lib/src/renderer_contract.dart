/// Renderer contract declaration (§12.1): every renderer delivers this
/// minimal machine-checkable 契约 as the input to §28/§33 consistency tests
/// and §38.2 分级验收. `allowed_differences` is exhaustive; un-enumerated
/// runtime differences are consistency defects.
library;

import 'package:microflow_model/microflow_model.dart';

/// Renderer contract Schema (§12.1).
class MFRendererContract {
  const MFRendererContract({
    required this.rendererId,
    required this.platform,
    required this.layoutSolverSyntax,
    required this.allowedDifferences,
    this.asyncStates = const ['idle', 'loading', 'success', 'empty', 'error', 'cancelled'],
    this.eventDispatch = 'declaration-order-deterministic',
    this.navigationShapes = const ['push', 'replace', 'modal', 'tab', 'back', 'deeplink'],
    this.errorBoundary = 'declared-scope-only',
    this.accessibility = const ['role', 'label', 'focus-order', 'lang', 'contrast'],
    this.instanceIdentifiers = const ['page_instance_id', 'component_instance_id', 'render_revision'],
    this.capabilityDegradation = 'declared-alternative-or-error',
    this.coreLayouts = const ['stack', 'grid', 'overlay', 'scroll', 'anchor', 'constraint', 'split'],
  });

  final String rendererId;
  final String platform;
  final String layoutSolverSyntax;
  final List<String> asyncStates;
  final String eventDispatch;
  final List<String> navigationShapes;
  final String errorBoundary;
  final List<String> accessibility;
  final List<String> instanceIdentifiers;
  final String capabilityDegradation;
  final List<String> coreLayouts;

  /// Exhaustive runtime differences: each with degradation declaration.
  final List<MFAllowedDifference> allowedDifferences;

  Map<String, Object?> toJson() => {
        'renderer_id': rendererId,
        'platform': platform,
        'consistency': {
          'async_states': asyncStates,
          'event_dispatch': eventDispatch,
          'navigation': navigationShapes,
          'error_boundary': errorBoundary,
          'accessibility': accessibility,
        },
        'layout_solver': {'core': coreLayouts, 'syntax_version': layoutSolverSyntax},
        'instance_identifiers': instanceIdentifiers,
        'allowed_differences': [for (final d in allowedDifferences) d.toJson()],
        'capability_degradation': {'on_unsupported': capabilityDegradation},
      };

  /// Validation: allowed_differences entries必须声明降级（§12.1 规则 1）。
  List<MFDiag> validate() => [
        for (final d in allowedDifferences)
          if (d.degradation.isEmpty)
            MFDiag(MFCodes.regContractMismatch,
                '允许差异 ${d.area}.${d.difference} 未声明降级（§12.1）'),
      ];
}

class MFAllowedDifference {
  const MFAllowedDifference({required this.area, required this.difference, this.userVisible = true, this.degradation = ''});
  final String area;
  final String difference;
  final bool userVisible;
  final String degradation; // e.g. 'reduced-motion-group' / 'platform-default'

  Map<String, Object?> toJson() => {
        'area': area,
        'difference': difference,
        'user_visible': userVisible,
        'degradation': degradation,
      };
}

/// The Flutter renderer's declared contract (Layer 1 口径, §38.2).
final MFRendererContract mfFlutterRendererContract = MFRendererContract(
  rendererId: 'flutter',
  platform: 'flutter',
  layoutSolverSyntax: '1.0',
  allowedDifferences: [
    const MFAllowedDifference(
      area: 'motion',
      difference: 'timing-and-easing-mapping',
      degradation: 'reduced-motion-group',
    ),
    const MFAllowedDifference(
      area: 'layout',
      difference: 'platform-widget-mapping',
      degradation: 'declared-alternative-or-error',
    ),
  ],
);
