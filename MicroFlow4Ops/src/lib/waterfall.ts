/** 运行记录节点级瀑布的真实时长换算（纯函数；时长来自框架 durationMs 上报）。
 * 页面不内联算式：min/max 语义在测试中固定——分母恒 ≥1，条宽恒 ≥3% 保可见性。 */
export interface NodeTraceLike {
  duration_ms?: number | null;
}

export function maxDurationOf(traces: NodeTraceLike[] | null | undefined): number {
  return Math.max(1, ...(traces || []).map((t) => t.duration_ms || 0));
}

export function waterfallPct(durationMs: number | null | undefined, maxDuration: number): number {
  const safeMax = maxDuration > 0 ? maxDuration : 1;
  // 夹紧 [3, 100]：条宽不溢出容器；正常调用方传 maxDurationOf 的结果，
  // 上限夹紧只影响异常入参，不改变正常相对关系。
  return Math.min(100, Math.max(3, ((durationMs || 0) / safeMax) * 100));
}
