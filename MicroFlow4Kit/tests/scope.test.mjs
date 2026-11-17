// Run with Node >= 22.7: node --experimental-transform-types --test tests/scope.test.mjs
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import test from "node:test";

test("scope events support custom namespaces, cross-tab updates and cleanup", async () => {
  const dir = await mkdtemp(join(tmpdir(), "microflow-scope-"));
  const source = await readFile(fileURLToPath(new URL("../packages/api/src/scope.ts", import.meta.url)), "utf8");
  // Configure the host exactly as a deployment with a custom namespace would.
  const moduleSource = source.replace('import { host } from "./host";',
    'const host = { scopeKey: "custom-scope", eventNamespace: "custom-console" };');
  await writeFile(join(dir, "scope.ts"), moduleSource);
  const items = new Map();
  globalThis.localStorage = {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => items.set(key, value),
    removeItem: (key) => items.delete(key),
  };
  globalThis.window = new EventTarget();
  try {
    const { onScopeChange, setScope, clearScope } = await import(pathToFileURL(join(dir, "scope.ts")));
    const received = [];
    const unsubscribe = onScopeChange((value) => received.push(value));
    const first = { tenantId: "tenant-a", projectId: "project-a", envKey: "dev" };
    setScope(first);
    assert.deepEqual(received, [first]);
    const second = { tenantId: "tenant-b", projectId: "project-b", envKey: "online" };
    localStorage.setItem("custom-scope", JSON.stringify(second));
    const storage = new Event("storage");
    Object.defineProperties(storage, { key: { value: "custom-scope" }, storageArea: { value: localStorage } });
    window.dispatchEvent(storage);
    assert.deepEqual(received.at(-1), second);
    clearScope();
    assert.deepEqual(received.at(-1), { tenantId: "", projectId: "", envKey: "" });
    unsubscribe();
    setScope(first);
    window.dispatchEvent(storage);
    assert.equal(received.length, 3);
  } finally {
    delete globalThis.window;
    delete globalThis.localStorage;
    await rm(dir, { recursive: true, force: true });
  }
});

test("session changes notify local and other tabs and stop after unsubscribe", async () => {
  const dir = await mkdtemp(join(tmpdir(), "microflow-session-"));
  const source = await readFile(fileURLToPath(new URL("../packages/api/src/client.ts", import.meta.url)), "utf8");
  const moduleSource = source
    .replace('import { host } from "./host";', 'const host = { tokenKey: "custom-token", eventNamespace: "custom-console" };')
    .replace('import { getScope } from "./scope";', 'const getScope = () => ({});');
  await writeFile(join(dir, "client.ts"), moduleSource);
  const items = new Map();
  globalThis.localStorage = {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => items.set(key, value),
    removeItem: (key) => items.delete(key),
  };
  globalThis.window = new EventTarget();
  try {
    const { onSessionChange, setToken, clearToken } = await import(pathToFileURL(join(dir, "client.ts")));
    let changes = 0;
    const unsubscribe = onSessionChange(() => changes++);
    setToken("first");
    clearToken();
    const storage = new Event("storage");
    Object.defineProperties(storage, { key: { value: "custom-token" }, storageArea: { value: localStorage } });
    window.dispatchEvent(storage);
    assert.equal(changes, 3);
    unsubscribe();
    setToken("second");
    window.dispatchEvent(storage);
    assert.equal(changes, 3);
  } finally {
    delete globalThis.window;
    delete globalThis.localStorage;
    await rm(dir, { recursive: true, force: true });
  }
});
