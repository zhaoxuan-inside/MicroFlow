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

/** 事件帧（ops.events.list 行）：payload 里携带节点级事实（node_id/status/duration_ms）。 */
export interface EventFrameLike {
  seq: number;
  event_id: string;
  aggregate_key: string;
  sequence: number;
  kind: string;
  payload?: Record<string, unknown> | null;
}

/** 帧瀑布行：payload → 节点轨迹；缺字段时如实降级（UNKNOWN/0），不猜。 */
export interface FrameTrace {
  node_id: string;
  status: string;
  duration_ms: number;
  payload: Record<string, unknown>;
}

export function groupFramesByAggregate(frames: EventFrameLike[] | null | undefined) {
  const groups = new Map<string, EventFrameLike[]>();
  for (const frame of frames || []) {
    const bucket = groups.get(frame.aggregate_key);
    if (bucket) bucket.push(frame);
    else groups.set(frame.aggregate_key, [frame]);
  }
  return [...groups.entries()].map(([aggregateKey, bucket]) => ({
    aggregateKey,
    frames: [...bucket].sort((a, b) => a.sequence - b.sequence),
  }));
}

export function frameToTrace(frame: EventFrameLike): FrameTrace {
  const payload = frame.payload || {};
  const node = payload.node_id ?? payload.event_type ?? `${frame.aggregate_key}#${frame.sequence}`;
  const status = payload.status ?? payload.resolution ?? "UNKNOWN";
  return {
    node_id: String(node),
    status: String(status),
    duration_ms: Number(payload.duration_ms) || 0,
    payload,
  };
}
