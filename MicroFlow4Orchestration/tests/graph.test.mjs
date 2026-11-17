// Run with Node >= 22.7: node --experimental-transform-types --test tests/graph.test.mjs
// graphLayout.ts 只含 type import（运行时擦除），直接动态导入；
// catalog.ts 对 dispatch 的裸说明符 import 打桩替换后测纯工具函数。
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const { topoLayout, reaches } = await import(
  new URL("../src/features/graphLayout.ts", import.meta.url)
);

test("topoLayout assigns topological columns and packs rows per column", () => {
  const nodes = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }].map((n) => ({ type: "BIZ", ...n }));
  const edges = [
    { from_node: "a", to_node: "b" },
    { from_node: "c", to_node: "b" },
  ];
  const layout = topoLayout(nodes, edges);
  assert.deepEqual(layout.get("a"), { col: 0, row: 0 });
  assert.deepEqual(layout.get("c"), { col: 0, row: 1 });
  assert.deepEqual(layout.get("b"), { col: 1, row: 0 });
  assert.deepEqual(layout.get("d"), { col: 0, row: 2 }); // 无入度节点在首列
});

test("topoLayout places unreachable and cyclic nodes in the fallback column", () => {
  const nodes = [{ id: "a" }, { id: "b" }, { id: "d" }].map((n) => ({ type: "BIZ", ...n }));
  const edges = [
    { from_node: "a", to_node: "b" },
    { from_node: "b", to_node: "a" }, // a↔b 成环：无入度起点
  ];
  const layout = topoLayout(nodes, edges);
  assert.deepEqual(layout.get("d"), { col: 0, row: 0 });
  const cyclic = [layout.get("a"), layout.get("b")];
  // 成环节点兜底进末列且行号不同，保证全部可见
  assert.ok(cyclic.every((p) => p.col === 1));
  assert.notEqual(cyclic[0].row, cyclic[1].row);
});

test("topoLayout lays a linear chain into one column per hop", () => {
  const nodes = ["a", "b", "c"].map((id) => ({ id, type: "BIZ" }));
  const edges = [
    { from_node: "a", to_node: "b" },
    { from_node: "b", to_node: "c" },
  ];
  const layout = topoLayout(nodes, edges);
  assert.equal(layout.get("a").col, 0);
  assert.equal(layout.get("b").col, 1);
  assert.equal(layout.get("c").col, 2);
});

test("reaches detects direct, indirect and self reachability without cycles", () => {
  const edges = [
    { from_node: "a", to_node: "b" },
    { from_node: "b", to_node: "c" },
    { from_node: "c", to_node: "a" }, // 环不造成死循环
  ];
  assert.equal(reaches("a", "b", edges), true);
  assert.equal(reaches("a", "c", edges), true);
  assert.equal(reaches("a", "a", edges), true);
  assert.equal(reaches("b", "d", edges), false);
  assert.equal(reaches("d", "a", edges), false);
});

test("catalog helpers classify ids and labels without network access", async () => {
  const dir = await mkdtemp(join(tmpdir(), "microflow-catalog-"));
  try {
    const source = await readFile(new URL("../src/features/catalog.ts", import.meta.url), "utf8");
    const moduleSource = source.replace(
      'import { dispatch } from "@microflow4kit/api";',
      'const dispatch = async () => { throw new Error("dispatch is not exercised by these tests"); };',
    );
    await writeFile(join(dir, "catalog.ts"), moduleSource);
    const { assetId, assetKindLabel, assetIdField, inferNodeType, versionTone } = await import(
      pathToFileURL(join(dir, "catalog.ts"))
    );
    assert.equal(assetId({ name: "op.a" }), "op.a");
    assert.equal(assetId({ code: "sub.b" }), "sub.b");
    assert.equal(assetId({}), "");
    assert.equal(assetKindLabel("operator"), "算子");
    assert.equal(assetKindLabel("subgraph"), "子图");
    assert.equal(assetKindLabel("scenario"), "场景");
    assert.equal(assetIdField("operator"), "name");
    assert.equal(assetIdField("scenario"), "code");
    assert.equal(inferNodeType("guard_input"), "GUARD");
    assert.equal(inferNodeType("validate_order"), "GUARD");
    assert.equal(inferNodeType("persist_record"), "STORAGE");
    assert.equal(inferNodeType("cache_price"), "CACHE");
    assert.equal(inferNodeType("compose_total"), "BIZ");
    assert.equal(versionTone.PUBLISHED, "success");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
