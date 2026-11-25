/** 字段契约守卫：三个 SPA + Kit admin 的每个 dispatch 调用场景必须可分类。
 *
 * 分类四类（host-contract.fields.json v1 为单一来源）：
 *   contract  —— 在参考宿主契约内；
 *   delegated —— orchestration./experiment./configcenter. 前缀（控制面承载，宿主 501 属实）；
 *   external  —— 真实宿主（OpcHub）自有场景，契约里登记的已知缺口；
 *   unknown   —— 既不在契约、也不在缺口清单 → 测试失败（这就是那盏红灯：静默 404 不允许再发生）。
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const contract = JSON.parse(readFileSync(join(here, "..", "host-contract.fields.json"), "utf8"));
const declared = new Set(Object.keys(contract.scenarios));
const external = new Set(Object.keys(contract.externalScenarios));
const delegated = contract.delegatedPrefixes;

const roots = [
  join(here, "..", "..", "MicroFlow4Ops", "src"),
  join(here, "..", "..", "MicroFlow4Bizops", "src"),
  join(here, "..", "..", "MicroFlow4Orchestration", "src"),
  join(here, "..", "packages", "admin", "src"),
  join(here, "..", "packages", "api", "src"),
];

function walk(root, out = []) {
  for (const entry of readdirSync(root)) {
    const path = join(root, entry);
    if (statSync(path).isDirectory()) walk(path, out);
    else if (/\.(ts|tsx)$/.test(entry)) out.push(path);
  }
  return out;
}

function classify(scenario) {
  if (declared.has(scenario)) return "contract";
  if (delegated.some((prefix) => scenario.startsWith(prefix))) return "delegated";
  if (external.has(scenario)) return "external";
  return "unknown";
}

function scan() {
  const seen = new Map();
  const pattern = /dispatch\s*(?:<[^>]*>)?\s*\(\s*"([^"]+)"/g;
  for (const root of roots) {
    for (const file of walk(root)) {
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(pattern)) {
        const scenario = match[1];
        if (!seen.has(scenario)) seen.set(scenario, { scenario, file });
      }
    }
  }
  return [...seen.values()];
}

test("host-contract.fields.json: 声明互斥且类型词表封闭", () => {
  assert.equal(contract.protocol, "microflow-host-fields-v1");
  assert.ok(![...declared].some((name) => external.has(name)), "external 不得遮蔽契约场景");
  for (const [name, spec] of Object.entries(contract.scenarios)) {
    assert.ok(spec.payload && spec.data, `${name} 必须声明 payload 与 data`);
  }
});

test("SPA dispatch 调用场景全部可分类，unknown 即失败", () => {
  const calls = scan();
  assert.ok(calls.length > 20, `扫描到的调用场景过少（${calls.length}），守卫可能没扫到源码`);
  const unknown = calls.filter((call) => classify(call.scenario) === "unknown");
  assert.deepEqual(
    unknown.map((call) => `${call.scenario}  (${call.file.split("/").slice(-2).join("/")})`),
    [],
    "存在未分类场景：要么是拼写漂移，要么该补进契约/缺口清单",
  );
});

test("历史错位已修复：Ops 运行页走契约场景名", () => {
  const calls = scan().map((call) => call.scenario);
  assert.ok(calls.includes("ops.runs.list"));
  assert.ok(calls.includes("ops.runs.detail"));
  assert.ok(calls.includes("ops.events.list"));
  // 曾经的静默错位：ops.runs.detail 曾用 trace_id 取不到数据——那是字段级问题，
  // 属于后续切片；这里至少保证场景名本身不再漂移。
});
