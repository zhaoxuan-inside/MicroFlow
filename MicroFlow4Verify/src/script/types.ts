/// 验收脚本 v1 形态：声明式步骤，零可执行逻辑（三平面分离——脚本属配置平面，
/// 宿主实现属代码平面，经 CLI --impls 单独注册）。面中性：web/flutter 面共用同一格式。

export type VerifyStep =
  | { op: 'open'; page: string; params?: Record<string, unknown> }
  | { op: 'back' }
  | { op: 'tap'; node: string; event: string; payload?: Record<string, unknown>; item?: unknown }
  | { op: 'fill'; node: string; value: unknown }
  | { op: 'expect_binding'; expr: unknown; equals: unknown }
  | { op: 'expect_event'; event: string; payload?: Record<string, unknown> }
  | { op: 'expect_route'; page: string }
  | { op: 'screenshot' };

export interface VerifyScript {
  scriptVersion: 1;
  title: string;
  steps: VerifyStep[];
}

/** 实现的步骤集合；未实现步骤在静态门禁显式拒绝（诚实边界，不是静默忽略）。 */
export const IMPLEMENTED_OPS = ['open', 'back', 'tap', 'fill', 'expect_binding', 'expect_event', 'expect_route'] as const;
export const DECLARED_OPS = [...IMPLEMENTED_OPS, 'screenshot'] as const;
export type DeclaredOp = (typeof DECLARED_OPS)[number];
