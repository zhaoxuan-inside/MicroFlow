/// Motion surface model (§36.5 动效面 / §36.7 减少动效替代组).
///
/// 动效值只解析到 motion Token（基线 22）：`{"duration": <ms>, "curve": [x1,y1,x2,y2]}`；
/// 减少动效偏好命中替代组时应用替代 Token 并记录（基线 23）：替代组以
/// `<token>.reduced` 命名约定承载于同一 token 集，悬空替代组是静态错误。
library;

import 'diagnostics.dart';
import 'project.dart';
import 'styles.dart';

/// Motion spec resolved from a motion token.
class MFMotionSpec {
  const MFMotionSpec({required this.durationMs, required this.curve});

  /// 动效时长（毫秒）；0 = 该面在当前偏好下不产生动效（替代组常态）。
  final int durationMs;

  /// 三次贝塞尔控制点（CSS cubic-bezier(x1,y1,x2,y2) 口径）。
  final List<double> curve;

  /// 解析 motion token 值；形状不符返回 null（调用方产生 mf.motion.token-invalid）。
  static MFMotionSpec? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final m = raw.cast<String, Object?>();
    final duration = m['duration'];
    final curve = m['curve'];
    if (duration is! num || duration < 0 || duration > 10000) return null;
    if (curve is! List || curve.length != 4) return null;
    final points = <double>[];
    for (final p in curve) {
      if (p is! num) return null;
      points.add(p.toDouble());
    }
    return MFMotionSpec(durationMs: duration.toInt(), curve: points);
  }

  Map<String, Object?> toJson() =>
      {'duration': durationMs, 'curve': [for (final p in curve) p]};
}

/// Motion resolution result：spec + 是否命中减少动效替代组（基线 23「并记录」）。
class MFMotionResolution {
  const MFMotionResolution({required this.spec, required this.viaAlternative});

  final MFMotionSpec? spec;
  final bool viaAlternative;
}

extension MFMotionResolver on MFStyleResolver {
  /// 解析 motion token（§36.5：值只来自 motion Token，不接受字面量）。
  ///
  /// [reduceMotion] 命中时优先解析同集内 `<token>.reduced` 替代组（§36.7）；
  /// 替代组缺失回落基础 token（不虚报 viaAlternative）。
  MFMotionResolution resolveMotion(
    String token, {
    String? themeId,
    bool reduceMotion = false,
  }) {
    final effective = effectiveTokens(themeId ?? defaultThemeId);
    if (reduceMotion) {
      final alt = effective['$token.reduced'];
      final altSpec = MFMotionSpec.tryParse(alt);
      if (altSpec != null) {
        return MFMotionResolution(spec: altSpec, viaAlternative: true);
      }
    }
    return MFMotionResolution(spec: MFMotionSpec.tryParse(effective[token]), viaAlternative: false);
  }
}

/// Motion token 静态校验（§36.5）：motion.* 值形状必须可解析；`*.reduced`
/// 替代组必须有同名基础 token（悬空替代组是静态错误）。
List<MFDiag> validateMotionTokens(Iterable<MFTokenSet> tokenSets) {
  final diags = <MFDiag>[];
  for (final set in tokenSets) {
    for (final e in set.tokens.entries) {
      if (!e.key.startsWith('motion.')) continue;
      if (MFMotionSpec.tryParse(e.value) == null) {
        diags.add(MFDiag(MFCodes.motionTokenInvalid,
            'motion token ${set.id}.${e.key} 值形状不符（需 {"duration": ms, "curve": [4 点]}）（§36.5）'));
      }
    }
    for (final e in set.tokens.entries) {
      if (!e.key.endsWith('.reduced') || !e.key.startsWith('motion.')) continue;
      final base = e.key.substring(0, e.key.length - '.reduced'.length);
      if (!set.tokens.containsKey(base)) {
        diags.add(MFDiag(MFCodes.motionAlternativeDangling,
            '替代组 ${set.id}.${e.key} 缺少同名基础 motion token `$base`（§36.7）'));
      }
    }
  }
  return diags;
}
