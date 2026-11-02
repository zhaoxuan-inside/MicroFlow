/** 宿主配置单点：支撑平台与具体业务解耦的全部可变点。
 *
 * 默认值面向任意 MicroFlow 宿主；宿主经 Vite 构建环境变量覆盖
 * （VITE_CONSOLE_*），如与宿主 SSO 同源共享令牌键。
 */
const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env || {};

export const host = {
  /** 统一网关分发端点（中性默认；OpcHub 宿主同为 /api/v1/dispatch） */
  endpoint: env.VITE_CONSOLE_ENDPOINT || "/api/v1/dispatch",
  /** 会话令牌 localStorage 键（与宿主主站同源共享时覆盖） */
  tokenKey: env.VITE_CONSOLE_TOKEN_KEY || "mf_console_token",
  /** 活动租户/项目/环境 scope 存储键 */
  scopeKey: env.VITE_CONSOLE_SCOPE_KEY || "mf_console_scope",
  /** 主题存储键 */
  themeKey: env.VITE_CONSOLE_THEME_KEY || "mf_console_theme",
  /** scope 变更广播事件名 */
  eventNamespace: env.VITE_CONSOLE_EVENT_NAMESPACE || "mf-console",
  /** 品牌名（标题/登录页） */
  brand: env.VITE_CONSOLE_BRAND || "MicroFlow",
} as const;
