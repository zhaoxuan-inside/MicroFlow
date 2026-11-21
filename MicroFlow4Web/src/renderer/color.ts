/// Token → CSS 值转换：模型 token 颜色为 Flutter 侧 #AARRGGBB（alpha 在前），
/// CSS 8 位 hex 是 #RRGGBBAA（alpha 在后）——直接透传会产生错色/错透明度。
/// 本模块是 Web 渲染器唯一的 token 值 → CSS 值出口（颜色与 px 数值族）。

const RGB_FAMILIES = ['radius.', 'blur.', 'space.', 'font.size.'];

/** 判定字符串是否为 #AARRGGBB / #RRGGBB 形态（模型颜色约定：alpha 在前）。 */
export function isHexColor(v: string): boolean {
  return /^#[0-9a-fA-F]{8}$/.test(v) || /^#[0-9a-fA-F]{6}$/.test(v);
}

/** #AARRGGBB → rgba(r,g,b,a)；#RRGGBB 原样；其余原样透传。 */
export function mfColorToCss(value: string): string {
  const m = /^#([0-9a-fA-F]{8})$/.exec(value);
  if (!m) return value;
  const hex = m[1]!;
  const a = Number.parseInt(hex.slice(0, 2), 16) / 255;
  const r = Number.parseInt(hex.slice(2, 4), 16);
  const g = Number.parseInt(hex.slice(4, 6), 16);
  const b = Number.parseInt(hex.slice(6, 8), 16);
  return `rgba(${r}, ${g}, ${b}, ${a.toFixed(3)})`;
}

/** token 值 → CSS 属性值：颜色换格式；px 族数值补单位；其余原样。 */
export function tokenToCssValue(tokenName: string, value: unknown): string | null {
  if (value === null || value === undefined || typeof value === 'object') return null;
  if (typeof value === 'string') {
    if (isHexColor(value)) return mfColorToCss(value);
    return value;
  }
  if (typeof value === 'number') {
    if (RGB_FAMILIES.some((f) => tokenName.startsWith(f))) return `${value}px`;
    return null; // 非 px 数值族（motion/ambient/tracking）不走 CSS 变量。
  }
  return null;
}
