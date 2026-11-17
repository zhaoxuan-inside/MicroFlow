// Run with Node >= 22.7: node --experimental-transform-types --test tests/i18n.test.mjs
// i18n 资源守卫：每个命名空间 zh/en 键集合必须齐平、值非空、插值占位符跨语言一致。
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const KIT = new URL("../", import.meta.url);

function flatten(obj, prefix = "") {
  const keys = {};
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v !== null && typeof v === "object") Object.assign(keys, flatten(v, key));
    else keys[key] = v;
  }
  return keys;
}

function loadNamespace(ns, file) {
  const zh = JSON.parse(readFileSync(new URL(file.replace("{lng}", "zh"), KIT), "utf8"));
  const en = JSON.parse(readFileSync(new URL(file.replace("{lng}", "en"), KIT), "utf8"));
  return { ns, zh: flatten(zh), en: flatten(en) };
}

const NAMESPACES = [
  loadNamespace("ui", "packages/ui/src/i18n/resources/ui.{lng}.json"),
  loadNamespace("admin", "packages/admin/src/resources/admin.{lng}.json"),
  loadNamespace("bizops", "../MicroFlow4Bizops/src/resources/bizops.{lng}.json"),
];

const PLACEHOLDER = /\{\{\s*(\w+)\s*\}\}/g;

test("每个命名空间 zh/en 键集合完全齐平", () => {
  for (const { ns, zh, en } of NAMESPACES) {
    const zhKeys = Object.keys(zh).sort();
    const enKeys = Object.keys(en).sort();
    assert.deepEqual(enKeys, zhKeys, `${ns} 命名空间 zh/en 键不一致`);
  }
});

test("全部资源值非空字符串", () => {
  for (const { ns, zh, en } of NAMESPACES) {
    for (const [lang, dict] of [["zh", zh], ["en", en]]) {
      for (const [key, value] of Object.entries(dict)) {
        assert.equal(typeof value, "string", `${ns}.${key}（${lang}）必须是字符串`);
        assert.ok(value.trim().length > 0, `${ns}.${key}（${lang}）为空`);
      }
    }
  }
});

test("插值占位符跨语言一致（防参数丢失）", () => {
  for (const { ns, zh, en } of NAMESPACES) {
    for (const key of Object.keys(zh)) {
      const params = (s) => new Set([...String(s).matchAll(PLACEHOLDER)].map((m) => m[1]));
      assert.deepEqual(
        [...params(en[key])].sort(),
        [...params(zh[key])].sort(),
        `${ns}.${key} 的插值占位符 zh/en 不一致`,
      );
    }
  }
});
