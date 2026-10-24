/// Layout constraint model (§7): constraint-solving semantics are fixed in
/// the framework, not reinterpreted per renderer (§7.1). Only the sizing
/// word list `hug/fill/fixed/min/max` plus spacing tokens is allowed; any
/// other sizing semantics is a static error (§7.2).
library;

/// Node self constraint (§7.2 mount points: layer region constraint and node
/// own constraint — the two only mount points).
class MFSelfConstraint {
  const MFSelfConstraint({
    this.width,
    this.height,
    this.maxWidth,
    this.minWidth,
    this.maxHeight,
    this.minHeight,
    this.anchor,
  });

  /// `hug` | `fill` | `fixed` | numeric fixed value.
  final Object? width;
  final Object? height;
  final num? maxWidth;
  final num? minWidth;
  final num? maxHeight;
  final num? minHeight;

  /// Anchor offsets, relative to container edges only (§7.3 Overlay rules);
  /// referencing sibling nodes is a static error.
  final Map<String, num>? anchor;

  static const kinds = ['hug', 'fill', 'fixed'];
}

/// A conditional layout scheme (§7.4): condition -> declarative layout plan.
class MFConditionalScheme {
  const MFConditionalScheme({required this.when, required this.plan});
  final Map<String, String> when; // e.g. {'breakpoint': 'mobile'} / {'platform': 'web'}
  final MFLayoutPlan plan;
}

/// A declarative layout plan: only the §7.1 capability list, composed
/// declaratively; imperative layout logic is banned (§7.4).
class MFLayoutPlan {
  const MFLayoutPlan({this.direction, this.align, this.crossAlign, this.attributes = const {}});
  final String? direction; // vertical | horizontal（Stack）
  final String? align;
  final String? crossAlign;
  final Map<String, Object?> attributes;
}

/// Page-level conditional layouts with the mandatory default plan (§7.4):
/// conditions may all miss, so the default plan is mandatory (baseline 20);
/// identical conditional selectors without explicit order are a static
/// error (§7.4 rule).
class MFConditionalLayout {
  const MFConditionalLayout({required this.target, required this.schemes, required this.defaultPlan});

  /// Target node/layer id (page root uses the page id).
  final String target;
  final List<MFConditionalScheme> schemes;
  final MFLayoutPlan defaultPlan;

  /// Resolve deterministically: declaration order, first hit wins; miss-all
  /// falls back to the declared default plan (never null, baseline 20).
  MFLayoutPlan resolve(Map<String, String?> conditions) {
    for (final s in schemes) {
      if (s.when.entries.every((e) => conditions[e.key] == e.value)) {
        return s.plan;
      }
    }
    return defaultPlan;
  }
}

/// Static layout checks on a page's constraint tree (§7.5): unsatisfiable
/// constraints, cycles, conflicting positioning rules; baseline 19/20.
/// The runtime module's solver assembles the full checks; these helpers are
/// shared predicate helpers.
bool isFill(Object? v) => v == 'fill';

bool isFixed(Object? v) => v is num || v == 'fixed';

bool isHug(Object? v) => v == 'hug';
