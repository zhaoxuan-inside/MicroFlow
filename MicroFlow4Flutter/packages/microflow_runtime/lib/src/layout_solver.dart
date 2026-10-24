/// Layout solving semantics (§7.3, formalized): `solve(约束集, 内容度量,
/// 可用空间) → 规范化矩形集`. A pure function: the same input in interpretive
/// and compiled modes and across renderers yields the same normalized
/// rectangles (baseline 18). Baseline tests use fixed-size synthetic
/// primitives to exclude content-metric noise.
library;

import 'package:microflow_model/microflow_model.dart';

/// Normalized logical rectangle (logical units x/y/w/h).
class MFRect {
  const MFRect(this.x, this.y, this.w, this.h);
  final double x, y, w, h;

  @override
  bool operator ==(Object other) =>
      other is MFRect && other.x == x && other.y == y && other.w == w && other.h == h;

  @override
  int get hashCode => Object.hash(x, y, w, h);

  @override
  String toString() => 'MFRect($x, $y, $w x $h)';
}

/// Bounded size demand derived from self constraints (§7.3 rule 1):
/// `fixed` → min=max=declared; `fill` → grow=true, min = declared floor or
/// 0; `hug` → size follows content (no space participation); `min/max`
/// modifiers produce bounds.
class MFSizeDemand {
  const MFSizeDemand({this.minW = 0, this.maxW = double.infinity, this.minH = 0, this.maxH = double.infinity, this.growW = false, this.growH = false});
  final double minW, maxW, minH, maxH;
  final bool growW, growH;

  static MFSizeDemand from(MFSelfConstraint? c, {required bool vertical}) {
    if (c == null) return const MFSizeDemand();
    double? fixedW, fixedH;
    if (c.width is num) fixedW = (c.width as num).toDouble();
    if (c.height is num) fixedH = (c.height as num).toDouble();
    return MFSizeDemand(
      growW: !vertical ? _isGrow(c.width) : false,
      growH: vertical ? _isGrow(c.height) : false,
      minW: _maxOf(fixedW, c.minWidth?.toDouble()),
      maxW: fixedW ?? c.maxWidth?.toDouble() ?? double.infinity,
      minH: _maxOf(fixedH, c.minHeight?.toDouble()),
      maxH: fixedH ?? c.maxHeight?.toDouble() ?? double.infinity,
    );
  }

  static bool _isGrow(Object? v) => v == 'fill';

  static double _maxOf(double? a, double? b) {
    final va = a ?? 0.0;
    final vb = b ?? 0.0;
    return va > vb ? va : vb;
  }
}

/// Content metric declared by the primitive contract (§7.3, deterministic).
class MFContentMetric {
  const MFContentMetric({required this.width, required this.height});
  final double width, height;
}

/// One node in a solving round.
class MFNodeLayout {
  const MFNodeLayout({
    required this.nodeId,
    required this.metric,
    this.demand = const MFSizeDemand(),
    this.unsupportedPlatforms = const [],
    this.degradationDeclared = false,
  });

  final String nodeId;
  final MFContentMetric metric;
  final MFSizeDemand demand;

  /// Platforms on which this node's layout capability is not supported
  /// (from the platform profile, §12).
  final List<String> unsupportedPlatforms;

  /// Whether a functional degradation is declared (§7.5, baseline 21).
  final bool degradationDeclared;
}

/// Placement result; `degraded=true` marks declared platform degradation.
class MFPlacedNode {
  const MFPlacedNode({required this.nodeId, required this.rect, this.degraded = false});
  final String nodeId;
  final MFRect rect;
  final bool degraded;

  @override
  bool operator ==(Object other) =>
      other is MFPlacedNode && other.nodeId == nodeId && other.rect == rect && other.degraded == degraded;

  @override
  int get hashCode => Object.hash(nodeId, rect, degraded);
}

/// The pure deterministic solver.
class MFLayoutSolver {
  /// Solve a vertical Stacked container (default scheme): children in
  /// declaration order along main axis. hug children take content metrics;
  /// the remaining space first satisfies every fill child's min; leftover is
  /// divided evenly between fill children, never below min; deficits emit
  /// `mf.layout.overflow` (§7.3 Stack rule). The same input produces stable
  /// outputs (baseline 18).
  (List<MFPlacedNode>, List<MFDiag>) solveStack({
    required List<MFNodeLayout> nodes,
    required double availW,
    required double availH,
    required String platform,
  }) {
    final diags = <MFDiag>[];
    final fills = nodes.where((n) => n.demand.growH || n.demand.growW).toList(growable: false);
    final hugTotal = nodes.where((n) => !fills.contains(n)).fold(0.0, (acc, n) => acc + n.metric.height);
    final fillMinTotal = fills.fold(0.0, (acc, n) => acc + n.demand.minH);
    final deficit = availH - hugTotal - fillMinTotal;
    if (deficit < 0) {
      diags.add(MFDiag(
        MFCodes.layoutOverflow,
        '主轴内容溢出 ${(-deficit).toStringAsFixed(1)}（可用 $availH）',
        stage: Stage.runtime,
      ));
    }
    final fillPool = deficit > 0 ? deficit : 0.0;
    final fillPer = fills.isEmpty ? 0.0 : fillPool / fills.length;

    final out = <MFPlacedNode>[];
    var y = 0.0;
    for (final n in nodes) {
      final w = _clampExtent(n.demand.minW, n.demand.maxW, n.metric.width, availW);
      var h = n.demand.growH
          ? n.demand.minH + fillPer
          : _clampExtent(n.demand.minH, n.demand.maxH, n.metric.height, availH);
      // Platform gate (§7.1/§7.5, baseline 21): unsupported capability
      // degrades only through the declared strategy, recording never
      // silently omitting.
      bool degraded = false;
      if (n.unsupportedPlatforms.contains(platform)) {
        if (n.degradationDeclared) {
          degraded = true;
          diags.add(MFDiag(MFCodes.layoutDegraded, '节点 ${n.nodeId} 在 $platform 上按声明降级执行', stage: Stage.runtime, severity: Severity.info));
        } else {
          diags.add(MFDiag(MFCodes.layoutUndeclaredDegradation, '节点 ${n.nodeId} 在 $platform 上能力不足且未声明降级'));
        }
      }
      out.add(MFPlacedNode(nodeId: n.nodeId, rect: MFRect(0, y, w, h), degraded: degraded));
      y += h;
    }
    return (out, diags);
  }

  double _clampExtent(double min, double max, double content, double avail) {
    final upper = max.isFinite ? (max > avail ? avail : max) : content;
    if (upper < min) return min;
    if (content < min) return min;
    if (content > upper) return upper;
    return content;
  }
}

/// Static layout checks (§7.5, baseline 19/20/21) over declared constraints
/// and platform profiles:
/// - 同轴 fill 与 fixed 并存、fixed 超出可用空间；
/// - 锚定循环依赖（regions 的 overlies 图）与冲突定位规则；
/// - 条件布局重复选择器的模糊命中（§7.4，基线 20 的静态面）；
/// - 目标平台不支持且未声明降级 → 构建拒绝（基线 21 的静态面）。
List<MFDiag> staticLayoutChecks({
  required List<MFDeclaredConstraint> constraints,
  required List<MFConditionalLayout>? conditionalLayouts,
  required List<MFPlatformProfile> targetProfiles,
  double availW = 1280,
  double availH = 720,
}) {
  final diags = <MFDiag>[];

  for (final c in constraints) {
    final v = c.constraint;
    if (_isFill(v.width) && _isFixed(v.width)) {
      diags.add(MFDiag(MFCodes.layoutUnsatisfiable, '${c.ownerId} 同轴同时声明 fill 与 fixed（宽，§7.3）'));
    }
    if (_isFill(v.height) && _isFixed(v.height)) {
      diags.add(MFDiag(MFCodes.layoutUnsatisfiable, '${c.ownerId} 同轴同时声明 fill 与 fixed（高，§7.3）'));
    }
    final fixedW = v.width is num ? (v.width as num).toDouble() : null;
    if (fixedW != null && fixedW > availW) {
      diags.add(MFDiag(MFCodes.layoutUnsatisfiable, '${c.ownerId} fixed 宽度超出可用空间（§7.3）'));
    }
    final fixedH = v.height is num ? (v.height as num).toDouble() : null;
    if (fixedH != null && fixedH > availH) {
      diags.add(MFDiag(MFCodes.layoutUnsatisfiable, '${c.ownerId} fixed 高度超出可用空间（§7.3）'));
    }
  }

  // 锚定不得形成循环依赖：覆盖图上的环。
  if (!_overlayOrderAcyclic(constraints)) {
    diags.add(MFDiag(MFCodes.layoutUnsatisfiable, '层间覆盖/锚定关系形成循环依赖（§7.3，基线 12）'));
  }

  for (final cl in conditionalLayouts ?? const <MFConditionalLayout>[]) {
    final seen = <String, int>{};
    for (final s in cl.schemes) {
      final key = s.when.toString();
      final count = seen[key] ?? 0;
      seen[key] = count + 1;
      if (count >= 1) {
        diags.add(MFDiag(MFCodes.layoutAmbiguousScheme, '目标 ${cl.target} 存在重复条件映射且顺序未声明（§7.4）'));
      }
    }
  }

  // 平台能力静态面（§7.1，基线 21）：不支持且未声明降级 → 拒绝构建。
  for (final profile in targetProfiles) {
    for (final c in constraints) {
      final unsupported = !profile.supportedLayouts.contains(c.capabilityId);
      if (unsupported) {
        final declaredDegradation = profile.degradation.containsKey(c.capabilityId);
        if (!declaredDegradation) {
          diags.add(MFDiag(MFCodes.layoutUndeclaredDegradation,
              '${c.ownerId} 的能力 ${c.capabilityId} 在 ${profile.platform} 不支持且未声明降级'));
        }
      }
    }
  }
  return diags;
}

bool _isFill(Object? v) => v == 'fill';

bool _isFixed(Object? v) => v is num || v == 'fixed';

bool _overlayOrderAcyclic(Iterable<MFDeclaredConstraint> constraints) {
  final overlies = <String, List<String>>{
    for (final c in constraints)
      if (c.overlies != null) c.ownerId: c.overlies!,
  };
  bool dfs(String node, Set<String> path) {
    if (path.contains(node)) return false;
    if (!overlies.containsKey(node)) return true;
    final next = {...path, node};
    return overlies[node]!.every((t) => dfs(t, next));
  }

  return overlies.keys.every((n) => dfs(n, {}));
}

/// A declared constraint owner（节点/层）——静态检查的最小声明单位。
class MFDeclaredConstraint {
  const MFDeclaredConstraint({
    required this.ownerId,
    required this.constraint,
    this.capabilityId = 'stack',
    this.overlies,
  });
  final String ownerId;
  final MFSelfConstraint constraint;

  /// The layout capability id this owner takes part in (§7.1).
  final String capabilityId;

  /// Declared overlay edges (regions only).
  final List<String>? overlies;
}

/// Platform capability profile (§12): supported layout capabilities and
/// declared per-capability degradation on this platform.
class MFPlatformProfile {  const MFPlatformProfile({
    required this.platform,
    required this.supportedLayouts,
    required this.unsupportedLayouts,
    this.degradation = const {},
  });
  final String platform;
  final List<String> supportedLayouts;
  final List<String> unsupportedLayouts;

  /// capability id -> declared degradation (`alternative:<id>` | `error`).
  final Map<String, String> degradation;
}

/// 默认 Web 平台能力矩阵：核心布局能力全部支持。
const MFPlatformProfile mfDefaultPlatformProfile = MFPlatformProfile(
  platform: 'web',
  supportedLayouts: ['stack', 'grid', 'overlay', 'scroll', 'anchor', 'constraint', 'split', 'header', 'footer', 'content'],
  unsupportedLayouts: [],
);
