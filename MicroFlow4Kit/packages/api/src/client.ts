/** Unified-gateway client shared by all console SPAs.
 *
 * Every call goes through the single dispatch endpoint with the standard
 * envelope {code, data, message}; the session token rides both the
 * Authorization header and the context payload, mirroring the main app.
 */
import { host } from "./host";

const TOKEN_KEY = host.tokenKey;

import { getScope } from "./scope";

export class ApiError extends Error {
  constructor(
    public code: number,
    message: string,
    public traceId?: string,
  ) {
    super(message);
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new Event(`${host.eventNamespace}:session-changed`));
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event(`${host.eventNamespace}:session-changed`));
}

/** Notify all console views when the current identity changes. */
export function onSessionChange(cb: () => void): () => void {
  const eventName = `${host.eventNamespace}:session-changed`;
  const storageHandler = (event: StorageEvent) => {
    if (event.storageArea === localStorage && (event.key === TOKEN_KEY || event.key === null)) cb();
  };
  window.addEventListener(eventName, cb);
  window.addEventListener("storage", storageHandler);
  return () => {
    window.removeEventListener(eventName, cb);
    window.removeEventListener("storage", storageHandler);
  };
}

/** 0.11.1 可靠性：请求超时控制——网关挂起不再拖死调用方（AbortController）。 */
async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") {
      throw new ApiError(408, `请求超时（${timeoutMs}ms）`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function dispatch<T = any>(
  scenario: string,
  payload: Record<string, unknown> = {},
  version = "v1.0.0",
): Promise<T> {
  const token = getToken();
  const scope = getScope();
  const context: Record<string, unknown> = { client_timestamp: Date.now(), token };
  // 活动租户/项目上下文：网关 scope 隔离授权与目录过滤都依赖它
  if (scope.tenantId) context.tenant_id = scope.tenantId;
  if (scope.projectId) context.project_id = scope.projectId;
  if (scope.envKey) context.env_key = scope.envKey;
  const res = await fetchWithTimeout(
    host.endpoint,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        scenario,
        version,
        payload,
        context,
      }),
    },
    host.requestTimeoutMs ?? 15000,
  );
  if (!res.ok) {
    throw new ApiError(res.status, `HTTP ${res.status}`);
  }
  const envelope = await res.json();
  if (envelope.code !== 200 && envelope.code !== 201) {
    throw new ApiError(envelope.code, envelope.message || "请求失败", envelope.trace_id);
  }
  return envelope.data as T;
}
