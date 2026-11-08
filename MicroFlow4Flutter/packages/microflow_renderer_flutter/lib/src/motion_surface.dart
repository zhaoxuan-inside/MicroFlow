/// Motion surface application (§36.5 动效面 / §36.7 减少动效替代组).
///
/// 渲染侧唯一动效入口：只作用于组件契约已声明的动效面（未声明面记录
/// mf.motion.surface-undeclared 且不生效）；值只解析到 motion Token；
/// 减少动效替代组命中时应用替代 spec 并记录（基线 22/23）。
library;

import 'package:flutter/material.dart';
import 'package:microflow_model/microflow_model.dart';

import 'primitives.dart';

/// 入场动效：淡入 + 上移距离 [slide]（逻辑像素）。
///
/// - 未声明 `surface` → 记录 mf.motion.surface-undeclared，原样返回；
/// - token 缺失/形状不符 → 记录 mf.motion.token-invalid，原样返回；
/// - 替代组命中（duration 0 或 reduceMotion）→ 记录
///   mf.motion.alternative-applied（基线 23「并记录」），无动画直出；
/// - 正常 spec → 一次性 fade+slide 入场（scheduler 驱动，首帧即开始）。
Widget mfMotionEntrance(
  MFRenderContext ctx,
  Widget child, {
  String surface = 'entrance',
  String token = 'motion.entrance',
  double slide = 14,
}) {
  if (!ctx.motionSurfaces.contains(surface)) {
    ctx.recordMotionDiag?.call(MFDiag(MFCodes.motionSurfaceUndeclared,
        '动效请求落在未声明的动效面 `$surface`，已按 §36.5 拒绝并记录'));
    return child;
  }
  final res = ctx.resolveMotion?.call(token);
  final spec = res?.spec;
  if (res == null || spec == null) {
    ctx.recordMotionDiag?.call(MFDiag(MFCodes.motionTokenInvalid,
        'motion token `$token` 缺失或形状不符，入场动效未生效（§36.5）'));
    return child;
  }
  if (res.viaAlternative) {
    ctx.recordMotionDiag?.call(MFDiag(MFCodes.motionAlternativeApplied,
        '减少动效偏好命中替代组 `$token.reduced`，已应用替代 Token（§36.7）',
        severity: Severity.info));
  }
  if (spec.durationMs <= 0) {
    return child;
  }
  return _MotionEntranceHost(
    spec: spec,
    slide: slide,
    child: child,
  );
}

class _MotionEntranceHost extends StatefulWidget {
  const _MotionEntranceHost({required this.spec, required this.slide, required this.child});

  final MFMotionSpec spec;
  final double slide;
  final Widget child;

  @override
  State<_MotionEntranceHost> createState() => _MotionEntranceHostState();
}

class _MotionEntranceHostState extends State<_MotionEntranceHost>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl = AnimationController(
    vsync: this,
    duration: Duration(milliseconds: widget.spec.durationMs),
  )..forward();
  late final Animation<double> _ease = CurvedAnimation(
    parent: _ctrl,
    curve: Cubic(widget.spec.curve[0], widget.spec.curve[1], widget.spec.curve[2], widget.spec.curve[3]),
  );

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _ease,
      builder: (context, _) => Opacity(
        opacity: _ease.value,
        child: Transform.translate(
          offset: Offset(0, (1 - _ease.value) * widget.slide),
          child: widget.child,
        ),
      ),
    );
  }
}

/// 悬停液态过渡参数（§36.5 hover 面）：由 motion token 驱动的
/// duration + curve，供宿主原语的 AnimatedContainer 等消费。
class MFMotionLerp {
  const MFMotionLerp({required this.duration, required this.curve, required this.enabled});

  final Duration duration;
  final Curve curve;
  final bool enabled;

  static final MFMotionLerp _disabled = MFMotionLerp(
      duration: Duration.zero, curve: Curves.linear, enabled: false);

  /// 从渲染上下文解析 `token`（缺面/缺 token → 退化为禁用并记录，
  /// 保持「不静默」口径）。悬停面声明约定为 `hover`。
  static MFMotionLerp hover(MFRenderContext ctx, {String token = 'motion.liquid'}) {
    if (!ctx.motionSurfaces.contains('hover')) {
      ctx.recordMotionDiag?.call(const MFDiag(MFCodes.motionSurfaceUndeclared,
          '悬停动效落在未声明的动效面 `hover`，已按 §36.5 退化为无动效并记录'));
      return _disabled;
    }
    final spec = ctx.resolveMotion?.call(token)?.spec;
    if (spec == null) {
      ctx.recordMotionDiag?.call(MFDiag(MFCodes.motionTokenInvalid,
          'motion token `$token` 缺失或形状不符，悬停动效未生效（§36.5）'));
      return _disabled;
    }
    return MFMotionLerp(
      duration: Duration(milliseconds: spec.durationMs),
      curve: Cubic(spec.curve[0], spec.curve[1], spec.curve[2], spec.curve[3]),
      enabled: spec.durationMs > 0,
    );
  }
}
