/// 动效面（§36.5/§36.7）：值只解析到 motion token；未声明面拒绝并记录；
/// 减少动效替代组命中直出。CSS 侧由 styles.css 的入场/过渡实现承接。

import { mfDiag, MFCodes, type MFDiag } from '../diagnostics.ts';

export interface MFMotionSpec {
  durationMs: number;
  curve: [number, number, number, number];
}

export interface MFMotionResolution {
  spec: MFMotionSpec | null;
  viaAlternative: boolean;
}

export function asSpec(value: unknown): MFMotionSpec | null {
  if (typeof value !== 'object' || value === null) return null;
  const rec = value as Record<string, unknown>;
  const duration = rec.duration;
  const curve = rec.curve;
  if (typeof duration !== 'number' || !Number.isFinite(duration)) return null;
  if (!Array.isArray(curve) || curve.length !== 4) return null;
  if (!curve.every((c) => typeof c === 'number' && Number.isFinite(c))) return null;
  return { durationMs: duration, curve: curve as [number, number, number, number] };
}

export function resolveMotion(
  token: string,
  effectiveTokens: Record<string, unknown>,
  reduceMotion: boolean,
  recordDiag: (diag: MFDiag) => void,
): MFMotionResolution {
  const raw = effectiveTokens[token];
  const spec = asSpec(raw);
  if (!spec) {
    recordDiag(mfDiag(MFCodes.motionTokenInvalid,
      `motion token ${token} 缺失或形状不符，动效未生效（§36.5）`));
    return { spec: null, viaAlternative: false };
  }
  if (reduceMotion) {
    const reduced = asSpec(effectiveTokens[`${token}.reduced`]);
    if (reduced) {
      recordDiag(mfDiag(MFCodes.motionAlternativeApplied,
        `减少动效偏好命中替代组 ${token}.reduced，已应用替代 Token（§36.7）`, 'info', 'runtime'));
      return { spec: reduced, viaAlternative: true };
    }
    return { spec, viaAlternative: false };
  }
  return { spec, viaAlternative: false };
}

export function cubicBezierCss(curve: [number, number, number, number]): string {
  return `cubic-bezier(${curve.map((c) => c).join(', ')})`;
}
