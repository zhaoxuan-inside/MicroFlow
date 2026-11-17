/** 框架名称词标（Logo）——字母组合徽标 + 双色词标 + 可选产品后缀。
 *
 * 品牌资产语义：徽标与 "Flow" 用固定的品牌蓝 #0070f3（Vercel 风格 token
 * 的品牌语义色），不随主题换色；文字对比度走主题 token。camelCase 分词后
 * 末段着色（MicroFlow → Micro·Flow），字母组合取各词首字母（MicroFlow → MF）。
 */
import { cn } from "./primitives";

const BRAND_BLUE = "#0070f3";

function splitName(name: string): string[] {
  return name.match(/[A-Z][a-z]+|[a-z]+|[0-9]+/g) || [name];
}

export function Logo({
  name = "MicroFlow",
  product,
  size = "sm",
  className,
}: {
  /** 框架名称；与宿主配置 brand（MicroFlow4Kit host.ts）保持一致 */
  name?: string;
  /** 产品后缀（如「运维平台」），弱化色显示 */
  product?: string;
  /** sm=侧栏头部；lg=登录页标题 */
  size?: "sm" | "lg";
  className?: string;
}) {
  const parts = splitName(name);
  const monogram = parts.map((part) => part[0]).join("").slice(0, 2).toUpperCase();
  const last = parts.length - 1;
  return (
    <span className={cn("inline-flex items-center gap-2 whitespace-nowrap", className)}>
      <span
        aria-hidden
        className={cn(
          "flex shrink-0 items-center justify-center rounded-md font-mono font-bold text-white",
          size === "sm" ? "h-6 w-6 text-[11px]" : "h-10 w-10 text-lg",
        )}
        style={{ backgroundColor: BRAND_BLUE }}
      >
        {monogram}
      </span>
      <span className={cn("font-semibold tracking-tight", size === "sm" ? "text-sm" : "text-xl")}>
        {parts.map((part, index) => (
          <span key={index} style={index === last ? { color: BRAND_BLUE } : undefined}>
            {part}
          </span>
        ))}
      </span>
      {product && (
        <span
          className={cn(
            "text-muted-foreground",
            size === "sm" ? "text-sm" : "text-base",
          )}
        >
          {product}
        </span>
      )}
    </span>
  );
}
