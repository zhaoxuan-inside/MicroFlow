// Run with Node >= 22.7: node --experimental-transform-types --test tests/client.test.mjs
// 沿用 scope.test.mjs 的“读源码-替换 import-临时目录-动态导入”模式；
// fetch 用 Node 24 内置 Response 打桩，验证统一分发的信封构建与错误路径。
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const HOST_STUB =
  'const host = { tokenKey: "test-token", eventNamespace: "test-console", endpoint: "https://host.example/dispatch" };';
const SCOPE_STUB =
  'const getScope = () => ({ tenantId: "tenant-1", projectId: "project-1", envKey: "online" });';

async function loadClient(dir) {
  const source = await readFile(
    new URL("../packages/api/src/client.ts", import.meta.url),
    "utf8",
  );
  const moduleSource = source
    .replace('import { host } from "./host";', HOST_STUB)
    .replace('import { getScope } from "./scope";', SCOPE_STUB);
  await writeFile(join(dir, "client.ts"), moduleSource);
  return import(pathToFileURL(join(dir, "client.ts")));
}

function withLocalStorage() {
  const items = new Map();
  globalThis.localStorage = {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => items.set(key, value),
    removeItem: (key) => items.delete(key),
  };
  globalThis.window = new EventTarget();
  return items;
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("dispatch posts the unified envelope with scope context and returns data", async () => {
  const dir = await mkdtemp(join(tmpdir(), "microflow-client-"));
  const items = withLocalStorage();
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return jsonResponse({ code: 200, data: { ok: 1 }, message: "", trace_id: "tr-1" });
  };
  try {
    const { dispatch, setToken } = await loadClient(dir);
    setToken("token-1");
    const data = await dispatch("bizops.overview", { range: "7d" }, "v2.0.0");
    assert.deepEqual(data, { ok: 1 });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "https://host.example/dispatch");
    assert.equal(calls[0].init.method, "POST");
    assert.equal(calls[0].init.headers.Authorization, "Bearer token-1");
    const body = JSON.parse(calls[0].init.body);
    assert.deepEqual(body, {
      scenario: "bizops.overview",
      version: "v2.0.0",
      payload: { range: "7d" },
      context: {
        client_timestamp: body.context.client_timestamp,
        token: "token-1",
        tenant_id: "tenant-1",
        project_id: "project-1",
        env_key: "online",
      },
    });
    assert.equal(typeof body.context.client_timestamp, "number");
  } finally {
    globalThis.fetch = originalFetch;
    delete globalThis.window;
    delete globalThis.localStorage;
    await rm(dir, { recursive: true, force: true });
    items.clear();
  }
});

test("dispatch omits the Authorization header and defaults the version", async () => {
  const dir = await mkdtemp(join(tmpdir(), "microflow-client-"));
  withLocalStorage();
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return jsonResponse({ code: 201, data: null });
  };
  try {
    const { dispatch, clearToken } = await loadClient(dir);
    clearToken();
    await dispatch("platform.scope.my");
    assert.equal(calls[0].init.headers.Authorization, undefined);
    const body = JSON.parse(calls[0].init.body);
    assert.equal(body.context.token, "");
    assert.equal(body.version, "v1.0.0");
    assert.equal(body.scenario, "platform.scope.my");
  } finally {
    globalThis.fetch = originalFetch;
    delete globalThis.window;
    delete globalThis.localStorage;
    await rm(dir, { recursive: true, force: true });
  }
});

test("dispatch raises ApiError for http failures and business envelope errors", async () => {
  const dir = await mkdtemp(join(tmpdir(), "microflow-client-"));
  withLocalStorage();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("boom", { status: 502 });
  try {
    const { dispatch, ApiError } = await loadClient(dir);
    await assert.rejects(dispatch("ops.runs.list"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, 502);
      assert.equal(error.message, "HTTP 502");
      return true;
    });
    globalThis.fetch = async () => jsonResponse({ code: 40003, message: "无权限", trace_id: "tr-9" }, 200);
    await assert.rejects(dispatch("platform.users.list"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, 40003);
      assert.equal(error.message, "无权限");
      assert.equal(error.traceId, "tr-9");
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
    delete globalThis.window;
    delete globalThis.localStorage;
    await rm(dir, { recursive: true, force: true });
  }
});
