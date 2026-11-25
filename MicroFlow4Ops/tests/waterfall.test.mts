import { test } from "node:test";
import assert from "node:assert/strict";
import { frameToTrace, groupFramesByAggregate, maxDurationOf, waterfallPct } from "../src/lib/waterfall.ts";

test("maxDurationOf: 空轨迹与零时长分母恒为 1", () => {
  assert.equal(maxDurationOf(null), 1);
  assert.equal(maxDurationOf([]), 1);
  assert.equal(maxDurationOf([{ duration_ms: 0 }, { duration_ms: null }]), 1);
});

test("maxDurationOf: 取真实最大时长（框架 durationMs）", () => {
  assert.equal(maxDurationOf([{ duration_ms: 12 }, { duration_ms: 340 }, { duration_ms: 7 }]), 340);
});

test("waterfallPct: 归一化到 maxDuration，最短 3% 保可见性", () => {
  assert.equal(waterfallPct(340, 340), 100);
  assert.equal(waterfallPct(170, 340), 50);
  assert.equal(waterfallPct(0, 340), 3);
  assert.equal(waterfallPct(null, 340), 3);
  assert.equal(waterfallPct(5, 0), 100); // 分母 0 退化时全宽（不伪造相对关系）
});

test("groupFramesByAggregate: 按聚合键分组、组内按 sequence 排序、保持首现顺序", () => {
  const frames = [
    { seq: 3, event_id: "c", aggregate_key: "exec-2", sequence: 1, kind: "runtime_record", payload: {} },
    { seq: 2, event_id: "b", aggregate_key: "exec-1", sequence: 2, kind: "runtime_record", payload: {} },
    { seq: 1, event_id: "a", aggregate_key: "exec-1", sequence: 1, kind: "runtime_record", payload: {} },
  ];
  const groups = groupFramesByAggregate(frames);
  assert.deepEqual(groups.map((g) => g.aggregateKey), ["exec-2", "exec-1"]);
  assert.deepEqual(groups[1].frames.map((f) => f.event_id), ["a", "b"]);
  assert.deepEqual(groupFramesByAggregate(null), []);
});

test("frameToTrace: payload 里的节点事实如实映射；缺字段降级为 UNKNOWN/0，不猜", () => {
  const trace = frameToTrace({
    seq: 1, event_id: "x", aggregate_key: "exec-1", sequence: 1, kind: "runtime_record",
    payload: { node_id: "calc", status: "SUCCEEDED", duration_ms: 12 },
  });
  assert.deepEqual(trace, { node_id: "calc", status: "SUCCEEDED", duration_ms: 12,
    payload: { node_id: "calc", status: "SUCCEEDED", duration_ms: 12 } });

  const bare = frameToTrace({
    seq: 2, event_id: "y", aggregate_key: "exec-9", sequence: 4, kind: "runtime_record", payload: null,
  });
  assert.equal(bare.node_id, "exec-9#4");
  assert.equal(bare.status, "UNKNOWN");
  assert.equal(bare.duration_ms, 0);

  const intent = frameToTrace({
    seq: 3, event_id: "z", aggregate_key: "exec-1", sequence: 2, kind: "event_intent",
    payload: { event_type: "order.placed", resolution: "COMMITTED" },
  });
  assert.equal(intent.node_id, "order.placed");
  assert.equal(intent.status, "COMMITTED");
});
