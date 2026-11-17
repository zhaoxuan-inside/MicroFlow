import { test } from "node:test";
import assert from "node:assert/strict";
import { maxDurationOf, waterfallPct } from "../src/lib/waterfall.ts";

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
