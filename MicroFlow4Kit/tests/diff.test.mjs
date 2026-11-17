// Run with Node >= 22.7: node --experimental-transform-types --test tests/diff.test.mjs
// diff.ts 是零依赖纯函数，直接动态导入源码即可，无需补丁。
import assert from "node:assert/strict";
import test from "node:test";

const { diffLines } = await import(new URL("../packages/ui/src/diff.ts", import.meta.url));

test("diffLines marks common, removed and added lines in deterministic order", () => {
  const rows = diffLines("a\nb\nc", "a\nx\nc");
  assert.deepEqual(rows, [
    { kind: "same", left: "a", right: "a" },
    { kind: "removed", left: "b" },
    { kind: "added", right: "x" },
    { kind: "same", left: "c", right: "c" },
  ]);
});

test("diffLines emits trailing additions and removals beyond the common core", () => {
  assert.deepEqual(diffLines("a", "a\nb\nc"), [
    { kind: "same", left: "a", right: "a" },
    { kind: "added", right: "b" },
    { kind: "added", right: "c" },
  ]);
  assert.deepEqual(diffLines("a\nb\nc", "a"), [
    { kind: "same", left: "a", right: "a" },
    { kind: "removed", left: "b" },
    { kind: "removed", left: "c" },
  ]);
});

test("diffLines collapses identical inputs to same rows", () => {
  assert.deepEqual(diffLines("x\ny", "x\ny"), [
    { kind: "same", left: "x", right: "x" },
    { kind: "same", left: "y", right: "y" },
  ]);
});

test("diffLines falls back to summary rows beyond the cell budget", () => {
  const big = "\n".repeat(2001); // 2002 × 2002 = 4_008_004 > 4_000_000
  assert.deepEqual(diffLines(big, big), [
    { kind: "removed", left: "（左侧 2002 行）" },
    { kind: "added", right: "（右侧 2002 行）" },
  ]);
});
